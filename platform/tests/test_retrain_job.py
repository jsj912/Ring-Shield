from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import contextmanager, nullcontext
from uuid import uuid4

import pytest
import pyarrow as pa
import pyarrow.parquet as pq

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from jobs.retrain import (RetrainError, build_label_rows, candidate_evaluation_policy,
                          run_retrain_job, should_promote, verify_holdout)
from adapters.research_cli import EvalResult, RingRunResult, TrainResult


def test_holdout_verifier_accepts_fixture_manifest_and_rejects_changed_bytes(tmp_path):
    fixture_dir = PLATFORM_ROOT / "tests/fixtures"
    manifest = fixture_dir / "holdout_manifest_fixture.json"
    checksum = fixture_dir / "holdout_manifest_fixture.sha256"
    assert verify_holdout(manifest, checksum)["truth_ring_ids"] == [12, 38, 104]

    changed = tmp_path / "changed.json"
    changed.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(RetrainError, match="SHA-256"):
        verify_holdout(changed, checksum)


def test_gate_refuses_candidate_below_epsilon_with_a_specific_reason():
    promote, reason = should_promote(0.5123, 0.5601, 0.005)

    assert promote is False
    assert reason == "holdout ring_f1 0.5123 < current 0.5601 - 0.005"


def test_gate_promotes_at_epsilon_boundary_or_above():
    assert should_promote(0.5551, 0.5601, 0.005)[0] is True
    assert should_promote(0.7, 0.56, 0.005)[0] is True


def test_retrained_false_skips_evaluation_and_cannot_promote():
    should_evaluate, reason = candidate_evaluation_policy(False)

    assert should_evaluate is False
    assert reason == "train CLI reported retrained=false; candidate identical to base"


def test_labels_use_verdict_specific_members_and_partial_edge_fallback():
    confirm_ring = SimpleNamespace(ring_id="c", member_accounts=[1, 2], member_edges=[10, 11])
    partial_ring = SimpleNamespace(ring_id="p", member_accounts=[3, 4, 5], member_edges=[20, 21])
    reject_ring = SimpleNamespace(ring_id="r", member_accounts=[6, 7], member_edges=[30])
    rows = build_label_rows([
        (SimpleNamespace(verdict="confirm", corrected_members=[], corrected_edges=[]), confirm_ring),
        (SimpleNamespace(verdict="partial", corrected_members=[3, 4], corrected_edges=[]), partial_ring),
        (SimpleNamespace(verdict="reject", corrected_members=[], corrected_edges=[]), reject_ring),
    ], {20: (3, 4), 21: (4, 5)})

    assert rows == [
        {"ring_id": "c", "member_accounts": [1, 2], "member_edges": [10, 11], "verdict": "confirm"},
        {"ring_id": "p", "member_accounts": [3, 4], "member_edges": [20], "verdict": "partial"},
        {"ring_id": "r", "member_accounts": [6, 7], "member_edges": [30], "verdict": "reject"},
    ]


def test_partial_labels_require_corrected_members():
    ring = SimpleNamespace(ring_id="p", member_accounts=[3], member_edges=[20])
    verdict = SimpleNamespace(verdict="partial", corrected_members=[], corrected_edges=[])

    with pytest.raises(RetrainError, match="no corrected members"):
        build_label_rows([(verdict, ring)], {20: (3, 3)})


@pytest.mark.parametrize(("candidate_f1", "retrained", "expected_promoted"), [
    (0.5551, True, True), (0.5123, True, False), (None, False, False),
])
@pytest.mark.parametrize("refresh_returncode", [0, 1])
def test_retrain_job_gates_candidate_and_runs_refresh_as_a_separate_step(
        monkeypatch, candidate_f1, retrained, expected_promoted, refresh_returncode):
    import jobs.retrain as retrain

    run_id = uuid4().hex
    log_path = PLATFORM_ROOT / "out" / "retrain" / f"{run_id}.log"
    base_dir = PLATFORM_ROOT / "out" / "fake-base"
    current = SimpleNamespace(trained_at=__import__("datetime").datetime(2026, 1, 1),
                              holdout_ring_f1=0.5601, artifact_path=str(base_dir))
    l6 = {"retrain": {"components": ["expansion"], "min_new_labels": 5,
                       "epsilon": 0.005, "eval_window": "val", "eval_scope": "test_visible"}}
    paths = {key: PLATFORM_ROOT / "out" / f"{key}.parquet" for key in
             ("val_scored_edges", "val_gfp", "val_embeddings", "truth_parquet")}
    paths.update({"holdout_manifest": PLATFORM_ROOT / "out/holdout.json",
                  "holdout_sha256_file": PLATFORM_ROOT / "out/holdout.sha256",
                  "base_model_dir": base_dir})
    config = {"active_model_id": "gine_causal", "active_seed": 1}
    inserted = []
    refresh_calls = []
    states = []
    log_messages = []

    class FakeCLI:
        eval_calls = 0
        eval_manifests = []

        def train(self, **kwargs):
            version = {"version": 2, "retrained": retrained,
                       "training_labels": {"rings": ["12", "full-model-1-0"]}}
            return TrainResult(model_dir=kwargs["out_dir"], version=version, retrained=retrained)

        def run_rings(self, **kwargs):
            kwargs["out"].parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table({"ring_id": ["12", "full-model-1-0", "fresh-ring"]}),
                           kwargs["out"])
            return RingRunResult(rings_path=kwargs["out"], run_log={"command": "run", "n_rings": 1}, ring_count=1)

        def eval_rings(self, **kwargs):
            self.eval_calls += 1
            self.eval_manifests.append(__import__("json").loads(kwargs["holdout"].read_text()))
            return EvalResult(metrics_path=kwargs["out"], metrics={"ring_f1": candidate_f1},
                              ring_f1=candidate_f1)

    class FakeDBSession:
        def __init__(self):
            self.run = SimpleNamespace(log_path=None)

        def scalar(self, query):
            return self.run

        def execute(self, statement):
            return SimpleNamespace(rowcount=1)

    @contextmanager
    def fake_db_session(**kwargs):
        yield FakeDBSession()

    @contextmanager
    def fake_loader_session(*, tenant_id):
        assert tenant_id == 21
        yield object()

    def fake_refresh_process(command, **kwargs):
        refresh_calls.append((command, kwargs))
        rings_path = log_path.parent / run_id / "refreshed-rings.parquet"
        rings_path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"ring_id": ["fresh"]}), rings_path)
        return SimpleNamespace(
            returncode=refresh_returncode,
            stdout=__import__("json").dumps({
                "tenant_id": 21, "model_version_id": 91,
                "rings_path": str(rings_path), "rings_loaded": 1,
            }),
            stderr="injected refresh failure" if refresh_returncode else "",
        )

    monkeypatch.setattr(retrain, "load_platform_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(retrain, "load_l6_config", lambda *args, **kwargs: l6)
    monkeypatch.setattr(retrain, "_validate_inputs", lambda *args, **kwargs: paths)
    monkeypatch.setattr(retrain, "_validation_edge_ids", lambda _path: set())
    monkeypatch.setattr(retrain, "verify_holdout", lambda *_args: {"truth_ring_ids": [12, 38, 104], "n": 3})
    monkeypatch.setattr(retrain, "_run_log_path", lambda value: log_path)
    monkeypatch.setattr(retrain, "_tenant_lock", lambda tenant: nullcontext())
    monkeypatch.setattr(retrain, "_set_run_state", lambda *args, **kwargs: states.append(kwargs["status"]))
    monkeypatch.setattr(retrain, "_promoted_version", lambda *args, **kwargs: current)
    monkeypatch.setattr(retrain, "_ensure_baseline", lambda **kwargs: current)
    monkeypatch.setattr(retrain, "_new_verdicts", lambda *args, **kwargs: [
        {"ring_id": str(index), "member_accounts": [index], "member_edges": [index], "verdict": "confirm"}
        for index in range(5)
    ])
    monkeypatch.setattr(retrain, "_insert_model_version", lambda **kwargs: inserted.append(kwargs) or 91)
    monkeypatch.setattr(retrain, "db_session", fake_db_session)
    monkeypatch.setattr(retrain, "loader_db_session", fake_loader_session)
    monkeypatch.setattr(retrain.subprocess, "run", fake_refresh_process)
    monkeypatch.setattr(retrain, "_write_log", lambda _path, message: log_messages.append(message))

    fake_cli = FakeCLI()
    promotion_manifest = None
    try:
        run_retrain_job(21, run_id, cli=fake_cli)
        manifest_path = log_path.parent / run_id / "promotion-manifest.json"
        if manifest_path.is_file():
            promotion_manifest = __import__("json").loads(manifest_path.read_text(encoding="utf-8"))
    finally:
        log_path.unlink(missing_ok=True)
        run_directory = log_path.parent / run_id
        if run_directory.exists():
            import shutil
            shutil.rmtree(run_directory)

    assert inserted[0]["promoted"] is expected_promoted
    assert fake_cli.eval_calls == (1 if retrained else 0)
    assert bool(refresh_calls) is expected_promoted
    if expected_promoted:
        assert refresh_calls[0][0][1:3] == ["-m", "jobs.refresh_rings"]
        assert refresh_calls[0][0][-3:] == ["21", "91", f"{run_id}-v91"]
        if refresh_returncode:
            assert states[-1] == "failed"
            assert any("injected refresh failure" in message for message in log_messages)
        else:
            assert states[-1] == "succeeded"
    else:
        assert states[-1] == "succeeded"
        assert all(call[0][-3:] != ["21", "91", run_id] for call in refresh_calls)
    if not retrained:
        assert inserted[0]["f1"] is None
        assert inserted[0]["gate_reason"] == "train CLI reported retrained=false; candidate identical to base"
    else:
        assert fake_cli.eval_manifests == [{
            "truth_ring_ids": [38, 104], "pred_ring_ids": ["fresh-ring"],
        }]
    assert promotion_manifest["status"] == ("failed" if expected_promoted and refresh_returncode else "succeeded")
    assert len(promotion_manifest["promotions"]) == int(expected_promoted and not refresh_returncode)


def test_promotion_manifest_keeps_component_version_training_and_refresh_associated(tmp_path):
    from jobs.promotion_artifacts import read_manifest, write_manifest

    rings_a = tmp_path / "expansion.parquet"
    rings_b = tmp_path / "affinity.parquet"
    rings_a.touch()
    rings_b.touch()
    write_manifest(tmp_path, {
        "tenant_id": 21, "run_id": "multi", "status": "succeeded",
        "promotions": [
            {"component": "expansion", "model_version_id": 101,
             "version_tag": "exp-v1", "training_ring_ids": ["a", "b"],
             "rings_path": str(rings_a)},
            {"component": "affinity", "model_version_id": 102,
             "version_tag": "aff-v1", "training_ring_ids": ["c"],
             "rings_path": str(rings_b)},
        ],
    })

    manifest = read_manifest(tmp_path, tenant_id=21, run_id="multi")
    by_version = {item["model_version_id"]: item for item in manifest["promotions"]}
    assert by_version[101]["training_ring_ids"] == ["a", "b"]
    assert Path(by_version[101]["rings_path"]) == rings_a
    assert by_version[102]["training_ring_ids"] == ["c"]
    assert Path(by_version[102]["rings_path"]) == rings_b


def test_promotion_manifest_refuses_missing_promoted_refresh_output(tmp_path):
    from jobs.promotion_artifacts import PromotionArtifactError, read_manifest, write_manifest

    write_manifest(tmp_path, {
        "tenant_id": 21, "run_id": "missing", "status": "succeeded",
        "promotions": [{"component": "expansion", "model_version_id": 101,
                        "training_ring_ids": ["a"],
                        "rings_path": str(tmp_path / "missing.parquet")}],
    })
    with pytest.raises(PromotionArtifactError, match="refreshed rings are missing"):
        read_manifest(tmp_path, tenant_id=21, run_id="missing")


def test_retrain_refresh_requires_existing_output_file(monkeypatch, tmp_path):
    import json
    import jobs.retrain as retrain

    missing = tmp_path / "missing.parquet"
    monkeypatch.setattr(retrain.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"tenant_id": 21, "model_version_id": 91,
                           "rings_path": str(missing)}), stderr="",
    ))
    with pytest.raises(RetrainError, match="output does not match.*missing"):
        retrain._run_ring_refresh_process(
            tenant_id=21, model_version_id=91, run_id="run-v91", log_path=tmp_path / "run.log",
        )


def test_run_state_clears_stale_model_version_when_success_has_no_promotion(monkeypatch):
    import jobs.retrain as retrain

    statements = []

    class Session:
        def execute(self, statement):
            statements.append(statement)
            return SimpleNamespace(rowcount=1)

    @contextmanager
    def fake_session(**_kwargs):
        yield Session()

    monkeypatch.setattr(retrain, "db_session", fake_session)
    retrain._set_run_state(21, "run", status="succeeded", model_version_id=None, finished=True)
    assert statements[0].compile().params["model_version_id"] is None


def test_retrain_missing_holdout_fails_run_with_safe_reason(monkeypatch):
    import jobs.retrain as retrain

    run_id = f"missing-holdout-{uuid4().hex}"
    log_path = PLATFORM_ROOT / "out" / "retrain" / f"{run_id}.log"
    states = []
    messages = []

    @contextmanager
    def fake_db_session(**_kwargs):
        yield SimpleNamespace(execute=lambda _statement: None)

    def reject_holdout(*_args, **_kwargs):
        raise RetrainError("holdout manifest or SHA-256 file is missing or invalid")

    monkeypatch.setattr(retrain, "load_platform_config", lambda: {})
    monkeypatch.setattr(retrain, "load_l6_config", lambda _config: {})
    monkeypatch.setattr(retrain, "_validate_inputs", lambda *_args: {
        "holdout_manifest": Path("missing-holdout.json"),
        "holdout_sha256_file": Path("missing-holdout.sha256"),
    })
    monkeypatch.setattr(retrain, "verify_holdout", reject_holdout)
    monkeypatch.setattr(retrain, "_run_log_path", lambda _run_id: log_path)
    monkeypatch.setattr(retrain, "_write_log", lambda _path, message: messages.append(message))
    monkeypatch.setattr(retrain, "_set_run_state", lambda *_args, **kwargs: states.append(kwargs))
    monkeypatch.setattr(retrain, "db_session", fake_db_session)

    run_retrain_job(21, run_id)

    assert [state["status"] for state in states] == ["failed"]
    assert states[0]["model_version_id"] is None
    assert any("holdout manifest or SHA-256 file is missing or invalid" in message
               for message in messages)
    assert all(str(PLATFORM_ROOT) not in message for message in messages)
