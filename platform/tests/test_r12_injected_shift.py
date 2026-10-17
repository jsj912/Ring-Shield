from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

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
