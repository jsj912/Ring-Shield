from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from jobs.simulate_verdicts import deterministic_rng, review_limit, simulate_cycle, simulate_decision
from services.verdicts import record_verdict


TRUTH = {"full": {1, 2, 3}, "partial": {10, 11, 12, 13}}


def _decision(accuracy: float, seed: int = 7):
    return simulate_decision(
        ring_members={1, 2, 3}, truth_rings=TRUTH,
        match_jaccard=0.5, full_confirm_jaccard=0.9,
        accuracy=accuracy, rng=deterministic_rng(21, 6, seed),
    )


def test_accuracy_one_reproduces_true_verdict_and_members():
    confirmed = _decision(1.0)
    partial = simulate_decision(
        ring_members={10, 11, 12, 99}, truth_rings=TRUTH,
        match_jaccard=0.5, full_confirm_jaccard=0.9,
        accuracy=1.0, rng=deterministic_rng(21, 6, 7),
    )

    assert confirmed.verdict == "confirm"
    assert confirmed.corrected_members == ()
    assert partial.verdict == "partial"
    assert partial.corrected_members == (10, 11, 12)
    assert partial.note == "simulated partial verdict"


def test_accuracy_zero_flips_confirm_and_reject():
    confirm = simulate_decision(ring_members={1, 2, 3}, truth_rings=TRUTH,
                                match_jaccard=0.5, full_confirm_jaccard=0.9,
                                accuracy=0.0, rng=deterministic_rng(21, 6, 1))
    reject = simulate_decision(ring_members={100, 101}, truth_rings=TRUTH,
                               match_jaccard=0.5, full_confirm_jaccard=0.9,
                               accuracy=0.0, rng=deterministic_rng(21, 6, 1))

    assert confirm.verdict == "reject"
    assert reject.verdict == "confirm"


def test_same_seed_is_deterministic_and_partial_noise_perturbs_members():
    left = simulate_decision(ring_members={10, 11, 12, 99}, truth_rings=TRUTH,
                             match_jaccard=0.5, full_confirm_jaccard=0.9,
                             accuracy=0.0, rng=deterministic_rng(21, 6, 7))
    right = simulate_decision(ring_members={10, 11, 12, 99}, truth_rings=TRUTH,
                              match_jaccard=0.5, full_confirm_jaccard=0.9,
                              accuracy=0.0, rng=deterministic_rng(21, 6, 7))

    assert left == right
    assert left.verdict == "partial"
    assert left.corrected_members != (10, 11, 12)
    assert left.is_simulated is True


def test_review_count_is_ceiling_of_configured_fraction():
    assert review_limit(21, 0.05) == 2
    assert review_limit(0, 0.05) == 0


def test_admin_cannot_invoke_simulator_before_truth_or_database_access(tmp_path):
    admin = Principal(user_id=1, tenant_id=None, role="admin", email="admin@example.test")

    with pytest.raises(PermissionError, match="non-admin actor"):
        simulate_cycle(tenant_id=21, cycle_day=6, actor=admin,
                       truth_path=tmp_path / "missing.parquet", seed=0, accuracy=1,
                       review_fraction=0.05, match_jaccard=0.5,
                       full_confirm_jaccard=0.9)


def test_shared_verdict_service_marks_simulated_row_and_updates_ring():
    class Session:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

        def flush(self):
            for row in self.rows:
                if row.__class__.__name__ == "Verdict" and row.verdict_id is None:
                    row.verdict_id = 55

    ring = SimpleNamespace(tenant_id=21, ring_id="same-key", status="open")
    session = Session()
    verdict = record_verdict(session, ring=ring, tenant_id=21, ring_id="same-key",
                             user_id=77, verdict="confirm", is_simulated=True)

    assert ring.status == "confirm"
    assert verdict.is_simulated is True
    assert len(session.rows) == 2
