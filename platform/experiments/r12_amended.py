"""R12 as amended on 2026-10-25, after the positive control failed (docs/R12.md).

    python -m experiments.r12_amended            # -> results/platform/r12/amended/

A. The hourly real stream and control again, with ADWIN clock=1 and everything else unchanged.
B. The same monitor on the per-transaction calibrated-score stream for days 8-9 (mean monitor
   only): the real stream (CYCLE removed from day 8) and the control (+the registered step on every
   score from hour 12 of day 9).
Also: panel.json for the admin R12 panel (the original clock=32 run, A and B: hourly series with
ADWIN state, and events), and tenant_hourly.json for the supervisor drift screen (banks 1, 20, 11,
118, 12; real scores, no synthetic step; ADWIN under A). Drift was injected, not observed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from river.drift import ADWIN

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from experiments import r12_injected_shift as r12  # noqa: E402
from experiments.r12_diagnose import registered_streams  # noqa: E402
from jobs.drift_monitor import MONITORS, DriftStream, daily_statistics  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402

OUT = REPO_ROOT / "results" / "platform" / "r12" / "amended"
TIME_ORIGIN = datetime(2022, 8, 31, 23, 59, 50, tzinfo=timezone.utc)   # loader timestamp 0
TENANTS = (1, 20, 11, 118, 12)
AMENDED_CLOCK = 1
HOUR = r12.SECONDS_PER_HOUR


def instant(loader_seconds: int) -> str:
    return (TIME_ORIGIN + timedelta(seconds=int(loader_seconds))).isoformat()


def hourly_replay(series: list[tuple[int, float, float]], *, delta: float, clock: int | None,
                  onset_step: int) -> dict:
    """The platform's two-statistic monitor over hourly points; rows for the panel and events."""
    stream = DriftStream(delta=delta, tenant_id=-1, step_seconds=HOUR, clock=clock)
    rows, events = [], []
    for index, (hour, mean, p99) in enumerate(series):
        fired = stream.update(hour, mean, p99)
        mean_d, p99_d = stream.detectors[MONITORS["mean"]], stream.detectors[MONITORS["p99"]]
        rows.append({"step": index + 1, "hour": instant(hour * HOUR + 10), "mean": mean, "p99": p99,
                     "adwin_mean_width": int(mean_d.width), "adwin_mean_drift": bool(mean_d.drift_detected),
                     "adwin_p99_width": int(p99_d.width), "adwin_p99_drift": bool(p99_d.drift_detected)})
        events += [{"step": index + 1, "monitor": event["monitor"], "detected_at": instant(hour * HOUR + 10 + HOUR),
                    "statistic": event["statistic"], "threshold": event["threshold"]} for event in fired]
    first = min((event["step"] for event in events), default=None)
    return {"rows": rows, "events": events, "detected": first is not None, "first_detection_step": first,
            "delay_hours": None if first is None else first - 1 - onset_step}


def transaction_replay(scores: pd.DataFrame, *, delta: float, start: int, onset_seconds: int) -> dict:
    """ADWIN (clock=1) on every calibrated score in timestamp order; hourly rows with the window
    width at the end of each hour, and every detection."""
    detector = ADWIN(delta=delta, clock=AMENDED_CLOCK)
    values, stamps, edges = (scores["score_calibrated"].to_numpy(float), scores["timestamp"].to_numpy(np.int64),
                             scores["edge_id"].to_numpy(np.int64))
    hours = (stamps - start) // HOUR
    events, rows, n_in_hour = [], [], 0
    for i, value in enumerate(values):
        detector.update(float(value))
        n_in_hour += 1
        if detector.drift_detected:
            events.append({"transaction": i + 1, "edge_id": int(edges[i]), "detected_at": instant(stamps[i]),
                           "hour_step": int(hours[i]) + 1, "width_after": int(detector.width)})
        if i + 1 == len(values) or hours[i + 1] != hours[i]:
            rows.append({"step": int(hours[i]) + 1, "hour": instant(start + int(hours[i]) * HOUR),
                         "n_transactions": n_in_hour, "adwin_width_end": int(detector.width),
                         "detections_in_hour": sum(event["hour_step"] == int(hours[i]) + 1 for event in events)})
            n_in_hour = 0
    after = [event for event in events if stamps[event["transaction"] - 1] >= onset_seconds]
    first = after[0] if after else None
    return {"rows": rows, "events": events, "n_transactions": len(values),
            "n_detections": len(events), "n_detections_before_onset": len(events) - len(after),
            "detected_after_onset": first is not None, "first_detection_after_onset": first,
            "delay_hours": None if first is None else round((stamps[first["transaction"] - 1] - onset_seconds) / HOUR, 3)}


def main() -> int:
    started = time.monotonic()
    config = load_platform_config()
    delta = float(config["l6"]["drift"]["delta"])
    s = registered_streams(config)
    start, step = s["start"], s["step"]
    day9, control_onset = start + 24 * HOUR, start + r12.CONTROL_START_STEP * HOUR
    onset = {"real": 24, "control": r12.CONTROL_START_STEP}

    original = {name: hourly_replay(s[name], delta=delta, clock=None, onset_step=onset[name]) for name in onset}
    recorded = json.loads((REPO_ROOT / "results/platform/r12/registered/run.json").read_text(encoding="utf-8"))
    for name in onset:      # the replay must reproduce the recorded run before anything new is reported
        if original[name]["detected"] != recorded[name]["detected"]:
            raise SystemExit(f"the clock=32 replay of the {name} stream does not reproduce the recorded run")
    arm_a = {name: hourly_replay(s[name], delta=delta, clock=AMENDED_CLOCK, onset_step=onset[name]) for name in onset}

    window = s["shifted"].loc[(s["shifted"]["timestamp"] >= start) & (s["shifted"]["timestamp"] < start + 48 * HOUR)]
    window = window.sort_values(["timestamp", "edge_id"], kind="mergesort").reset_index(drop=True)
    control = window.assign(score_calibrated=window["score_calibrated"]
                            + step["mean"] * (window["timestamp"] >= control_onset))
    arm_b = {"real": transaction_replay(window, delta=delta, start=start, onset_seconds=day9),
             "control": transaction_replay(control, delta=delta, start=start, onset_seconds=control_onset)}

    adwin = lambda clock: {"implementation": "river 0.22.0 ADWIN", "delta": delta, "clock": clock,  # noqa: E731
                           "max_buckets": 5, "min_window_length": 5, "grace_period": 10, "units": "raw"}
    panel = {"statement": "drift was injected, not observed", "synthetic_control": r12.SYNTHETIC,
             "control_step": step, "control_onset": instant(control_onset), "real_onset": instant(day9),
             "removed_cycle_transactions": s["removed"],
             "original_registered_run": {"adwin": adwin(32), "note": "as run on 2026-10-24; the control did not fire",
                                         **original},
             "amendment_a_hourly": {"adwin": adwin(AMENDED_CLOCK), **arm_a},
             "amendment_b_per_transaction": {"adwin": adwin(AMENDED_CLOCK), "monitor": "adwin_score_mean",
                                             "note": "p99 is not defined for a single transaction", **arm_b}}

    scores = pd.read_parquet(configured_path(config, "scored_edges"),
                             columns=["timestamp", "from_bank", "to_bank", "score_calibrated"])
    scores = scores.loc[(scores["timestamp"] >= start) & (scores["timestamp"] < start + 48 * HOUR)]
    tenants = []
    for tenant in TENANTS:
        mine = scores.loc[(scores["from_bank"] == tenant) | (scores["to_bank"] == tenant)]
        series = daily_statistics(zip(mine["timestamp"].astype("int64"), mine["score_calibrated"]), step_seconds=HOUR)
        replay = hourly_replay(series, delta=delta, clock=AMENDED_CLOCK, onset_step=0)
        tenants.append({"tenant_id": tenant, "active_model_id": config["active_model_id"],
                        "active_seed": int(config["active_seed"]), "step_seconds": HOUR,
                        "items": [{"day": row["hour"], "mean": row["mean"], "p99": row["p99"]} for row in replay["rows"]],
                        "adwin": [{key: row[key] for key in ("hour", "adwin_mean_width", "adwin_mean_drift",
                                                             "adwin_p99_width", "adwin_p99_drift")} for row in replay["rows"]],
                        "events": [{**event, "window_end": event["detected_at"], "acted_on": False}
                                   for event in replay["events"]]})
    wall = round(time.monotonic() - started, 1)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "panel.json").write_text(json.dumps(panel | {"wall_seconds": wall}, indent=1), encoding="utf-8")
    (OUT / "tenant_hourly.json").write_text(json.dumps(
        {"statement": "real scores, no synthetic step; ADWIN as in R12 amendment A (clock=1)", "adwin": adwin(AMENDED_CLOCK),
         "tenants": tenants}, indent=1), encoding="utf-8")
    summary = {"wall_seconds": wall,
               "original_clock32": {k: v["detected"] for k, v in original.items()},
               "a_hourly_clock1": {k: {kk: v[kk] for kk in ("detected", "first_detection_step", "delay_hours")}
                                   for k, v in arm_a.items()},
               "b_per_transaction": {k: {kk: v[kk] for kk in ("n_transactions", "n_detections", "n_detections_before_onset",
                                                              "detected_after_onset", "first_detection_after_onset",
                                                              "delay_hours")} for k, v in arm_b.items()},
               "tenants": {t["tenant_id"]: {"hours": len(t["items"]), "events": len(t["events"])} for t in tenants}}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
