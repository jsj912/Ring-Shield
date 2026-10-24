from __future__ import annotations

import json
from pathlib import Path
import sys
from contextlib import contextmanager

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from types import SimpleNamespace

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from experiments import r12_injected_shift as r12
from jobs.drift_monitor import DriftStream, detect_events


def test_fixture_dry_mode_reports_injected_drift_and_never_claims_a_retrain(monkeypatch, tmp_path):
    config = {"_path": tmp_path / "config.yaml", "l6": {"drift": {"delta": 0.002}}}
    config["_path"].write_text("test: true\n", encoding="utf-8")
    monkeypatch.setattr(r12, "load_platform_config", lambda: config)
    monkeypatch.setattr(r12, "REPO_ROOT", tmp_path)
    result = r12.run_experiment(dry=True, pattern="BIPARTITE")
    report = Path(result["markdown"]).read_text(encoding="utf-8")
    run_log = json.loads(Path(result["run_json"]).read_text(encoding="utf-8"))
    assert result["dry_run"] is True
    assert "DRY RUN FIXTURE ONLY" in report
    assert "drift was injected, not observed." in report
    assert "gated retrain was not executed" in report
    assert result["detection_delay_simulated_days"] == 31
    assert run_log["fixture_only"] is True
    assert run_log["dry_run"] is True


def test_prepare_shift_moves_only_first_half_pattern_transactions(monkeypatch, tmp_path):
    source = tmp_path / "scored_edges.parquet"
    output = tmp_path / "shift"
    first_time = 10 + 8 * 86_400
    second_time = 10 + 14 * 86_400
    table = pa.table({
        "edge_id": [1, 2, 3], "from_id": [11, 21, 31], "to_id": [12, 22, 32],
        "timestamp": [first_time, second_time, first_time], "score_raw": [0.9, 0.8, 0.1],
        "model_id": ["fixture"] * 3, "seed": [1] * 3,
    })
    pq.write_table(table, source)
    Path(str(source) + ".log.json").write_text(json.dumps({
        "split": "test", "model_id": "fixture", "seed": 1,
        "seed_rule": {"q": 0.5}, "inputs": {},
    }), encoding="utf-8")
    truth_rows = pd.DataFrame([
        {"ring_id": 9, "pattern_type": "BIPARTITE", "from_id": 11, "to_id": 12,
         "timestamp_int": first_time},
        {"ring_id": 9, "pattern_type": "BIPARTITE", "from_id": 21, "to_id": 22,
         "timestamp_int": second_time},
    ])
    monkeypatch.setattr(r12, "load_window_truth_details", lambda *args, **kwargs: (
        {9: frozenset({11, 12, 21, 22})}, {9: "BIPARTITE"}, truth_rows,
    ))
    result = r12.prepare_shifted_scores(
        scores_path=source, truth_path=tmp_path / "truth.parquet",
        pattern="BIPARTITE", output_dir=output,
    )
    before = pq.read_table(result["before_path"]).to_pydict()
    after = pq.read_table(result["after_path"]).to_pydict()
    assert result["moved_edge_rows"] == 1
    assert before["edge_id"] == [2, 3]
    assert sorted(after["edge_id"]) == [1, 2, 3]
    moved = after["edge_id"].index(1)
    assert after["timestamp"][moved] == first_time + 5 * 86_400
    assert json.loads(Path(str(result["after_path"]) + ".log.json").read_text())["split"] == "test"


def test_drift_streaming_replay_matches_batch_detector_events():
    daily = [(day, 0.0 if day < 128 else 1.0, 0.0 if day < 128 else 1.0)
             for day in range(256)]
    stream = DriftStream(delta=0.002, tenant_id=21)
    online = [event for point in daily for event in stream.update(*point)]
    assert online == detect_events(daily, delta=0.002, tenant_id=21)
    assert {event["monitor"] for event in online} == {"adwin_score_mean", "adwin_score_p99"}


def test_r12_evaluation_excludes_training_ring_ids_from_truth_and_predictions(tmp_path, monkeypatch):
    rings_path = tmp_path / "rings.parquet"
    pq.write_table(pa.table({"ring_id": ["12", "38", "104", "trained-prediction"]}), rings_path)
    observed = {}

    def evaluate(**kwargs):
        observed.update(json.loads(kwargs["holdout"].read_text(encoding="utf-8")))
        return SimpleNamespace(metrics={"ring_recall": 0.75, "member_coverage": 0.9})

    monkeypatch.setattr(r12.research_cli, "eval_rings", evaluate)
    result = r12._eval_pattern(
        rings_path, tmp_path / "truth.parquet", {12, 38},
        tmp_path / "metrics.json", excluded_ring_ids={"38", "trained-prediction"},
    )

    assert observed == {"pred_ring_ids": ["12", "104"], "truth_ring_ids": [12]}
    assert result["ring_recall"] == 0.75
    assert result["n_truth_rings"] == 1
    assert result["n_excluded_truth_rings"] == 1


def test_r12_reports_undefined_recall_when_training_excludes_all_truth(tmp_path, monkeypatch):
    rings_path = tmp_path / "rings.parquet"
    pq.write_table(pa.table({"ring_id": ["38"]}), rings_path)
    monkeypatch.setattr(
        r12.research_cli, "eval_rings",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not evaluate empty truth")),
    )

    result = r12._eval_pattern(
        rings_path, tmp_path / "truth.parquet", {38}, tmp_path / "metrics.json",
        excluded_ring_ids={"38"},
    )

    assert result["ring_recall"] is None
    assert result["n_truth_rings"] == 0
    assert result["undefined_reason"] == "no truth rings remain after training-ring exclusion"


def test_r12_promotion_orchestration_keeps_component_version_rings_and_training_ids_paired(
        tmp_path, monkeypatch):
    from jobs.promotion_artifacts import write_manifest

    promotions = []
    versions = []
    for component, version_id, training_ids in (
            ("expansion", 101, ["trained-exp"]),
            ("affinity", 202, ["trained-aff", "trained-aff-2"])):
        model_dir = tmp_path / f"model-{version_id}"
        model_dir.mkdir()
        (model_dir / "version.json").write_text(json.dumps({
            "retrained": True, "training_labels": {"rings": training_ids},
        }), encoding="utf-8")
        rings_path = tmp_path / f"rings-{version_id}.parquet"
        pq.write_table(pa.table({
            "tenant_id": [21, 21], "ring_id": [f"ring-{version_id}", training_ids[0]],
        }), rings_path)
        promotions.append({
            "component": component, "model_version_id": version_id,
            "version_tag": f"v{version_id}", "training_ring_ids": training_ids,
            "rings_path": str(rings_path),
        })
        versions.append(SimpleNamespace(
            artifact_path=str(model_dir), component=component,
            version_tag=f"v{version_id}", promoted=True,
        ))
    run_dir = tmp_path / "run"
    write_manifest(run_dir, {
        "tenant_id": 21, "run_id": "r12-test", "status": "succeeded",
        "promotions": promotions,
    })

    @contextmanager
    def fake_db_session(**kwargs):
        assert kwargs == {"tenant_id": 21, "role": "supervisor"}
        version = versions.pop(0)
        yield SimpleNamespace(scalar=lambda _query: version)

    evaluations = []

    def fake_eval(rings_path, _truth_path, ids, out, *, excluded_ring_ids=None):
        evaluations.append((Path(rings_path), set(ids), set(excluded_ring_ids or set())))
        return {"ring_recall": 0.7, "member_coverage": 0.8,
                "n_truth_rings": len(ids) - len(excluded_ring_ids or set())}

    monkeypatch.setattr(r12, "db_session", fake_db_session)
    monkeypatch.setattr(r12, "_eval_pattern", fake_eval)
    results = r12._evaluate_promoted_artifacts(
        run_dir=run_dir, tenant_id=21, run_id="r12-test", truth_path=tmp_path / "truth.parquet",
        pattern_ids={1, 2, 3}, cycle_truth_ids={2, 3}, output_dir=tmp_path / "metrics",
    )

    assert [(row["component"], row["model_version_id"]) for row in results] == [
        ("expansion", 101), ("affinity", 202),
    ]
    assert len(evaluations) == 4
    for row in results:
        own_path = Path(row["rings_path"])
        assert [evaluation[0] for evaluation in evaluations if evaluation[0] == own_path] == [
            own_path, own_path,
        ]
        assert all(evaluation[2] == set(row["training_ring_ids"])
                   for evaluation in evaluations if evaluation[0] == own_path)


def test_r12_no_promotion_report_has_no_post_retrain_baseline_metrics():
    rows = r12._promotion_report_rows(
        before_metrics={"ring_recall": 0.2},
        after_metrics={"ring_recall": 0.6},
        cycle_before_metrics={"ring_recall": 0.3},
        promotions=[],
    )

    assert rows[0]["lane"] == "no_retrain_control"
    assert rows[0]["recall_after_insertion_without_retrain"] == 0.6
    assert rows[0]["recall_after_gated_retrain"] is None
    assert rows[1] == {
        "lane": "gated_retrain_no_promotion", "recall_after_gated_retrain": None,
        "cycle_recall_after_gated_retrain": None,
        "cycle_truth_rings_after_training_exclusion": None, "promotion_status": "none",
    }
    assert all("rings_path" not in row for row in rows)
