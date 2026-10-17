from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace
from contextlib import contextmanager, nullcontext
from uuid import uuid4

import pytest

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
def test_retrain_job_gates_a_fake_candidate_without_writing_rings(
        monkeypatch, candidate_f1, retrained, expected_promoted):
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

    class FakeCLI:
        eval_calls = 0

        def train(self, **kwargs):
            return TrainResult(model_dir=kwargs["out_dir"], version={"version": 2}, retrained=retrained)

        def run_rings(self, **kwargs):
            return RingRunResult(rings_path=kwargs["out"], run_log={"command": "run", "n_rings": 1}, ring_count=1)

        def eval_rings(self, **kwargs):
            self.eval_calls += 1
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

    monkeypatch.setattr(retrain, "load_platform_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(retrain, "load_l6_config", lambda *args, **kwargs: l6)
    monkeypatch.setattr(retrain, "_validate_inputs", lambda *args, **kwargs: paths)
    monkeypatch.setattr(retrain, "_run_log_path", lambda value: log_path)
    monkeypatch.setattr(retrain, "_tenant_lock", lambda tenant: nullcontext())
    monkeypatch.setattr(retrain, "_set_run_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(retrain, "_promoted_version", lambda *args, **kwargs: current)
    monkeypatch.setattr(retrain, "_ensure_baseline", lambda **kwargs: current)
    monkeypatch.setattr(retrain, "_new_verdicts", lambda *args, **kwargs: [
        {"ring_id": str(index), "member_accounts": [index], "member_edges": [index], "verdict": "confirm"}
        for index in range(5)
    ])
    monkeypatch.setattr(retrain, "_insert_model_version", lambda **kwargs: inserted.append(kwargs) or 91)
    monkeypatch.setattr(retrain, "db_session", fake_db_session)
    monkeypatch.setattr(retrain, "loader_db_session", fake_loader_session)

    fake_cli = FakeCLI()
    try:
        run_retrain_job(21, run_id, cli=fake_cli)
    finally:
        log_path.unlink(missing_ok=True)
        run_directory = log_path.parent / run_id
        if run_directory.exists():
            import shutil
            shutil.rmtree(run_directory)

    assert inserted[0]["promoted"] is expected_promoted
    assert fake_cli.eval_calls == (1 if retrained else 0)
    if not retrained:
        assert inserted[0]["f1"] is None
        assert inserted[0]["gate_reason"] == "train CLI reported retrained=false; candidate identical to base"
