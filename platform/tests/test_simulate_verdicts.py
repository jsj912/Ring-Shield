from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from api.identity import Principal
from jobs.simulate_verdicts import (DAY_ZERO_TIMESTAMP, SECONDS_PER_DAY,
                                    deterministic_rng, review_limit, simulate_cycle,
                                    simulate_decision, validate_review_interval)
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


@pytest.mark.parametrize("cycle_day,cycle_days", [(6, 1), (7, 2), (17, 2), (18, 1)])
def test_simulator_refuses_cycles_outside_test_window_before_truth_or_database(
        tmp_path, cycle_day, cycle_days):
    actor = Principal(user_id=2, tenant_id=21, role="analyst", email="a@example.test")

    with pytest.raises(ValueError, match="test days 8-17"):
        simulate_cycle(tenant_id=21, cycle_day=cycle_day, cycle_days=cycle_days,
                       actor=actor, truth_path=tmp_path / "missing.parquet", seed=0,
                       accuracy=1, review_fraction=0.05, match_jaccard=0.5,
                       full_confirm_jaccard=0.9)


@pytest.mark.parametrize(("day", "duration", "window"), [
    (8, 1, "primary"), (8, 2, "primary"), (9, 2, "whole"), (17, 1, "whole"),
])
def test_review_interval_uses_actual_timestamp_bounds(day, duration, window):
    start, end = validate_review_interval(day, duration, window)
    assert start == DAY_ZERO_TIMESTAMP + day * SECONDS_PER_DAY
    assert end == start + duration * SECONDS_PER_DAY


@pytest.mark.parametrize(("day", "duration", "window"), [
    (17, 2, "whole"), (9, 2, "primary"), (8, 1, "val"),
])
def test_review_interval_rejects_outside_test_or_truth_window(day, duration, window):
    with pytest.raises(ValueError):
        validate_review_interval(day, duration, window)


def test_main_rejects_invalid_interval_before_opening_analyst_session(monkeypatch, tmp_path):
    import jobs.simulate_verdicts as simulator

    truth = tmp_path / "truth.parquet"
    truth.touch()
    config = {
        "simulator": {"seed": 0, "accuracy": 0.9, "review_fraction": 0.05,
                      "cycle_days": 2, "match_jaccard": 0.5, "full_confirm_jaccard": 0.9},
        "retrain": {"truth_parquet": truth}, "paths": {"truth_parquet": truth},
    }
    calls = []
    monkeypatch.setattr(simulator, "load_l6_config", lambda **_kwargs: config)
    monkeypatch.setattr(simulator, "db_session", lambda **_kwargs: calls.append("session"))

    with pytest.raises(SystemExit):
        simulator.main(["--tenant-id", "21", "--cycle-day", "17"])
    assert calls == []


def test_main_reports_invalid_interval_before_missing_truth_file(monkeypatch, tmp_path, capsys):
    import jobs.simulate_verdicts as simulator

    missing_truth = tmp_path / "missing-truth.parquet"
    config = {
        "simulator": {"seed": 0, "accuracy": 0.9, "review_fraction": 0.05,
                      "cycle_days": 2, "match_jaccard": 0.5, "full_confirm_jaccard": 0.9},
        "retrain": {"truth_parquet": missing_truth}, "paths": {"truth_parquet": missing_truth},
    }
    opened_sessions = []
    monkeypatch.setattr(simulator, "load_l6_config", lambda **_kwargs: config)
    monkeypatch.setattr(simulator, "db_session", lambda **_kwargs: opened_sessions.append(True))

    with pytest.raises(SystemExit):
        simulator.main(["--tenant-id", "21", "--cycle-day", "17"])

    assert "test days 8-17" in capsys.readouterr().err
    assert opened_sessions == []


def test_cli_default_truth_window_is_whole_and_accepts_compatible_primary(monkeypatch, tmp_path):
    import jobs.simulate_verdicts as simulator
    from contextlib import contextmanager

    truth = tmp_path / "truth.parquet"
    truth.touch()
    config = {
        "simulator": {"seed": 0, "accuracy": 0.9, "review_fraction": 0.05,
                      "cycle_days": 1, "match_jaccard": 0.5, "full_confirm_jaccard": 0.9},
        "retrain": {"truth_parquet": truth}, "paths": {"truth_parquet": truth},
    }
    observed = []

    class Session:
        def execute(self, _query):
            return self
        def one_or_none(self):
            return SimpleNamespace(user_id=2, email="simulated.analyst@tenant21.local")

    @contextmanager
    def fake_session(**_kwargs):
        yield Session()

    monkeypatch.setattr(simulator, "load_l6_config", lambda **_kwargs: config)
    monkeypatch.setattr(simulator, "db_session", fake_session)
    monkeypatch.setattr(simulator, "simulate_cycle", lambda **kwargs: observed.append(kwargs) or {})
    assert simulator.main(["--tenant-id", "21", "--cycle-day", "8"]) == 0
    assert observed[-1]["truth_window"] == "whole"
    assert simulator.main(["--tenant-id", "21", "--cycle-day", "8",
                           "--truth-window", "primary"]) == 0
    assert observed[-1]["truth_window"] == "primary"


def test_shared_verdict_service_marks_simulated_row_and_updates_ring():
    class Session:
        def __init__(self):
            self.rows = []
            self.statements = []

        def add(self, row):
            self.rows.append(row)

        def execute(self, statement):
            self.statements.append(statement)

        def flush(self):
            for row in self.rows:
                if row.__class__.__name__ == "Verdict" and row.verdict_id is None:
                    row.verdict_id = 55

    ring = SimpleNamespace(tenant_id=21, ring_id="same-key", status="open")
    session = Session()
    verdict = record_verdict(session, ring=ring, tenant_id=21, ring_id="same-key",
                             user_id=77, verdict="confirm", is_simulated=True)

    assert ring.status == "confirmed"
    assert verdict.is_simulated is True
    assert len(session.rows) == 1
    audit_params = session.statements[0].compile(dialect=postgresql.dialect()).params
    assert audit_params["action"] == "verdict.recorded"
    assert audit_params["details"] == {
        "verdict": "confirm", "is_simulated": True, "status": "confirmed"
    }
