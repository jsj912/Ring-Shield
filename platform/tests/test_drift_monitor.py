from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
import time

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(PLATFORM_ROOT))

from api.scheduler import start_scheduler
from jobs import drift_monitor


def _daily(values):
    return [(day, value, value) for day, value in enumerate(values)]


def test_each_adwin_series_detects_one_step_change_after_shift():
    events = drift_monitor.detect_events(_daily([0.0] * 128 + [1.0] * 128),
                                         delta=0.002, tenant_id=21)
    assert len(events) == 2
    assert {event["monitor"] for event in events} == {
        "adwin_score_mean", "adwin_score_p99",
    }
    assert all(event["window_end"] > event["window_start"] for event in events)
    assert all(event["threshold"] == 0.002 and event["acted_on"] is False for event in events)


def test_flat_series_has_no_events():
    assert drift_monitor.detect_events(_daily([0.25] * 300), delta=0.002, tenant_id=21) == []


def test_daily_statistics_skip_missing_days_and_order_observed_days():
    rows = [
        (10 + 2 * 86_400, 0.8),
        (10, 0.2),
        (10 + 2 * 86_400, 0.6),
        (10 + 86_400, None),
    ]
    result = drift_monitor.daily_statistics(rows)
    assert [row[0] for row in result] == [0, 2]
    assert result[0] == (0, 0.2, 0.2)
    assert result[1][1] == pytest.approx(0.7)
    assert result[1][2] == pytest.approx(0.798)


def test_drift_monitor_has_no_retrain_dependency_or_call():
    source = (PLATFORM_ROOT / "jobs" / "drift_monitor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = [node.module or "" for node in ast.walk(tree)
               if isinstance(node, ast.ImportFrom)]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any("retrain" in name for name in imports)
    assert not any(isinstance(node.func, ast.Name) and "retrain" in node.func.id
                   for node in calls)


def test_scheduler_disabled_by_default_and_date_trigger_dispatches_jobs(repo_platform_config):
    from settings import load_platform_config

    assert start_scheduler(load_platform_config()) is None
    completed = Event()
    calls = []

    def record(name):
        calls.append(name)
        if len(calls) == 2:
            completed.set()

    scheduler = start_scheduler(
        {"scheduler": {"enabled": True}}, date_trigger=True,
        retrain_job=lambda: record("retrain"), drift_job=lambda: record("drift"),
    )
    try:
        assert completed.wait(5), "date-triggered scheduler jobs did not execute"
        assert sorted(calls) == ["drift", "retrain"]
    finally:
        scheduler.shutdown(wait=True)
