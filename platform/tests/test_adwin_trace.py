"""The instrumented ADWIN used to diagnose R12 must behave exactly like river's (docs/R12.md)."""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pytest

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLATFORM_ROOT))

from experiments.adwin_trace import TracedADWIN, assert_matches_river  # noqa: E402
from jobs.drift_monitor import MONITORS, DriftStream  # noqa: E402


@pytest.mark.parametrize("clock", [32, 1])
def test_traced_adwin_matches_river_through_detections_and_resets(clock):
    rng = np.random.default_rng(7)
    values = np.concatenate([rng.normal(0.2, 0.05, 300), rng.normal(0.7, 0.05, 300)]).clip(0, 1)
    assert_matches_river(list(values), delta=0.002, clock=clock)
    traced = TracedADWIN(delta=0.002, clock=clock)
    assert any(traced.update(value)["drift_detected"] for value in values)


def test_clock_32_tests_once_in_48_steps_and_clock_1_every_step_after_the_grace_period():
    tested = {clock: [record["tick"] for record in _records(clock) if record["tested"]] for clock in (32, 1)}
    assert tested[32] == [32]
    assert tested[1] == list(range(11, 49))


def _records(clock):
    detector = TracedADWIN(clock=clock)
    return [detector.update(0.5) for _ in range(48)]


def test_the_bound_has_a_floor_no_hourly_score_shift_can_clear():
    detector = TracedADWIN(clock=1)
    for value in [0.001] * 36 + [0.003] * 12:      # a tripling of an hourly mean of calibrated scores
        record = detector.update(value)
    assert not record["drift_detected"]
    assert min(cut["epsilon"] for cut in record["cuts"] if cut["epsilon"] is not None) > 0.5


def test_drift_stream_passes_clock_to_both_detectors_and_keeps_river_default():
    assert all(d.clock == 1 for d in DriftStream(delta=0.002, tenant_id=1, clock=1).detectors.values())
    default = DriftStream(delta=0.002, tenant_id=1).detectors[MONITORS["mean"]]
    assert default.clock == 32
