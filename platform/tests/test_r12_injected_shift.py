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


def test_drift_streaming_replay_matches_batch_detector_events():
    daily = [(day, 0.0 if day < 128 else 1.0, 0.0 if day < 128 else 1.0)
             for day in range(256)]
    stream = DriftStream(delta=0.002, tenant_id=21)
    online = [event for point in daily for event in stream.update(*point)]
    assert online == detect_events(daily, delta=0.002, tenant_id=21)
    assert {event["monitor"] for event in online} == {"adwin_score_mean", "adwin_score_p99"}


DAY8 = 10 + 8 * 86_400


def test_day8_removal_drops_only_the_patterns_day8_transactions():
    scores = pd.DataFrame({"edge_id": [1, 2, 3, 4], "from_id": [10, 10, 20, 10], "to_id": [11, 11, 21, 11],
                           "timestamp": [DAY8 + 5, DAY8 + 86_400 + 5, DAY8 + 5, DAY8 + 7]})
    truth_rows = pd.DataFrame({"ring_id": [1, 1, 2], "from_id": [10, 10, 20], "to_id": [11, 11, 21],
                               "timestamp_int": [DAY8 + 5, DAY8 + 86_400 + 5, DAY8 + 5]})
    shifted, removed = r12.remove_day8_pattern(scores, truth_rows, {1}, DAY8)
    # ring 1's day-8 row goes; its day-9 row, ring 2 and an unrelated edge stay
    assert removed == 1
    assert shifted["edge_id"].tolist() == [2, 3, 4]


def test_synthetic_control_adds_three_sd_of_day8_from_hour_36_only():
    series = [(hour, 0.001 * (hour % 3), 0.01 + 0.001 * (hour % 2)) for hour in range(48)]
    shifted, step = r12.with_synthetic_step(series)
    day8_means = pd.Series([m for _, m, _ in series[:24]])
    day8_p99 = pd.Series([p for _, _, p in series[:24]])
    assert step["mean"] == 3 * day8_means.std(ddof=1)
    assert step["p99"] == 3 * day8_p99.std(ddof=1)
    assert shifted[:36] == series[:36]
    assert all(abs(s[1] - o[1] - step["mean"]) < 1e-12 and abs(s[2] - o[2] - step["p99"]) < 1e-12
               for s, o in zip(shifted[36:], series[36:]))


def test_hourly_stream_timestamps_its_windows_in_hours():
    stream = DriftStream(delta=0.002, tenant_id=900_001, step_seconds=3_600)
    for hour in range(5):
        stream.update(hour, 0.0, 0.0)
    assert stream.step_seconds == 3_600


def test_default_adwin_cannot_fire_within_48_steps_even_on_a_large_step():
    """Documents F8 (docs/FUTURE_IMPLEMENTATIONS.md): river's ADWIN(clock=32) tests for a change once
    per 32 updates, so a step at step 37 of 48 is never tested. Fixing the monitor must flip this."""
    series = [(hour, 0.001 + 0.0001 * (hour % 2), 0.015) for hour in range(48)]
    shifted = [(h, m + (1.0 if i >= 36 else 0.0), p) for i, (h, m, p) in enumerate(series)]
    _, detection = r12.replay_monitor(shifted, delta=0.002, tenant_id=900_001, onset_step=36)
    assert detection["detected"] is False


def test_registered_run_stops_and_says_so_when_the_control_does_not_fire(monkeypatch, tmp_path):
    undetected = {"detected": False, "first_detection_step": None, "delay_hours": None, "monitors": []}
    monkeypatch.setattr(r12, "monitor_stage", lambda **kwargs: {
        "removed_cycle_transactions": 31, "real": dict(undetected), "control": dict(undetected)})
    monkeypatch.setattr(r12, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(r12, "configured_path", lambda config, key: tmp_path / key)
    monkeypatch.setattr(r12, "write_run_manifest", lambda output_dir, **kwargs: output_dir / "run.json")
    result = r12.registered_run(config={"l6": {"retrain": {"truth_parquet": "t"}, "drift": {"delta": 0.002}}},
                                tenant_id=900_001)
    assert result["statement"] == "drift was injected, not observed"
    assert "the monitor is broken" in result["stopped"]
