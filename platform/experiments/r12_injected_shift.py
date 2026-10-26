"""R12: an injected pattern shift and the drift monitor, as registered in docs/R12.md.

CYCLE is removed from test day 8 and day 9 is unchanged; the platform's ADWIN monitor runs on the
hourly mean and p99 of calibrated scores over the 48 hours, next to a synthetic positive control.
Drift was injected, not observed. Replaces the v1.0 design (days 8-17, 5-day shift, daily steps).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from adapters.ground_truth import load_window_truth_details
from experiments.common import ExperimentInputError, write_csv_and_markdown, write_run_manifest
from jobs.drift_monitor import MONITORS, DriftStream, daily_statistics
from settings import configured_path, load_platform_config
from ringshield.windows import load_windows

DAY_ZERO = 10
SECONDS_PER_DAY = 86_400
FIRST_TEST_DAY = 8
LAST_TEST_DAY = 17
PATTERN_NAMES = {"BIPARTITE", "CYCLE", "FAN_IN", "FAN_OUT", "SCATTER_GATHER", "STACK"}


def _ring_members(path: Path) -> list[set[int]]:
    table = pq.read_table(path, columns=["members"])
    return [set(map(int, values or [])) for values in table["members"].to_pylist()]


def _score_log(path: Path) -> dict:
    log_path = Path(str(path) + ".log.json")
    try:
        return json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentInputError(f"scored-edge run log is missing or invalid: {log_path}") from exc


SECONDS_PER_HOUR = 3_600
STEPS = 48                    # hourly steps over test days 8-9 (docs/R12.md, registered 2026-10-24)
CONTROL_START_STEP = 36       # hour 12 of day 9
CONTROL_SD = 3.0              # synthetic step: 3 SD of day 8's hourly values, per statistic
SYNTHETIC = "SYNTHETIC POSITIVE CONTROL: a step added to the monitor input, not data"


def remove_day8_pattern(scores: pd.DataFrame, truth_rows: pd.DataFrame, pattern_ids: set,
                        primary_start: int) -> tuple[pd.DataFrame, int]:
    """Drop the pattern's truth transactions on test day 8 (matched by sender, receiver and
    timestamp); day 9 is left unchanged. Returns the shifted scores and the rows removed."""
    day9 = primary_start + SECONDS_PER_DAY
    rows = truth_rows.loc[truth_rows["ring_id"].isin(pattern_ids)
                          & (truth_rows["timestamp_int"] >= primary_start)
                          & (truth_rows["timestamp_int"] < day9)]
    keys = set(zip(rows["from_id"].astype("int64"), rows["to_id"].astype("int64"),
                   rows["timestamp_int"].astype("int64")))
    hit = pd.Series([key in keys for key in zip(scores["from_id"].astype("int64"),
                                                scores["to_id"].astype("int64"),
                                                scores["timestamp"].astype("int64"))],
                    index=scores.index)
    return scores.loc[~hit].reset_index(drop=True), int(hit.sum())


def hourly_series(scores: pd.DataFrame, primary_start: int) -> list[tuple[int, float, float]]:
    """(absolute hour, mean, p99) of calibrated scores for the 48 hours of days 8-9."""
    window = scores.loc[(scores["timestamp"] >= primary_start)
                        & (scores["timestamp"] < primary_start + STEPS * SECONDS_PER_HOUR)]
    series = daily_statistics(zip(window["timestamp"].astype("int64"), window["score_calibrated"]),
                              step_seconds=SECONDS_PER_HOUR)
    if len(series) != STEPS:
        raise ExperimentInputError(f"expected {STEPS} hourly steps over days 8-9, found {len(series)}")
    return series


def with_synthetic_step(series: list[tuple[int, float, float]]) -> tuple[list[tuple[int, float, float]], dict]:
    """The positive control: +3 SD of day 8's hourly values on each statistic from hour 36."""
    means = np.array([mean for _, mean, _ in series[:24]])
    p99s = np.array([p99 for _, _, p99 in series[:24]])
    step = {"mean": CONTROL_SD * float(means.std(ddof=1)), "p99": CONTROL_SD * float(p99s.std(ddof=1))}
    shifted = [(hour, mean + step["mean"] * (i >= CONTROL_START_STEP), p99 + step["p99"] * (i >= CONTROL_START_STEP))
               for i, (hour, mean, p99) in enumerate(series)]
    return shifted, step


def replay_monitor(series: list[tuple[int, float, float]], *, delta: float, tenant_id: int,
                   onset_step: int) -> tuple[list[dict], dict]:
    """Feed the series to the platform's two ADWIN streams one hour at a time; day 8 is the
    reference. Returns the per-hour state and the first detection relative to `onset_step`."""
    stream = DriftStream(delta=delta, tenant_id=tenant_id, step_seconds=SECONDS_PER_HOUR)
    rows, events = [], []
    for index, (hour, mean, p99) in enumerate(series):
        fired = stream.update(hour, mean, p99)
        events += [(index, event) for event in fired]
        state = {monitor.split("_")[-1]: stream.detectors[monitor] for monitor in MONITORS.values()}
        rows.append({
            "step": index + 1, "day": 8 + index // 24, "hour_of_day": index % 24,
            "mean": round(mean, 6), "p99": round(p99, 6),
            "adwin_mean_width": int(state["mean"].width), "adwin_mean_drift": bool(state["mean"].drift_detected),
            "adwin_p99_width": int(state["p99"].width), "adwin_p99_drift": bool(state["p99"].drift_detected),
        })
    first = min((index for index, _ in events), default=None)
    detection = {"detected": first is not None,
                 "first_detection_step": None if first is None else first + 1,
                 "delay_hours": None if first is None else first - onset_step,
                 "monitors": sorted({event["monitor"] for index, event in events if index == first})}
    return rows, detection


def monitor_stage(*, scores_path: Path, truth_path: Path, delta: float, tenant_id: int,
                  output_dir: Path) -> dict:
    """Registered R12 monitor run: the real shifted stream and the synthetic positive control."""
    windows = load_windows()
    primary_start = int(windows["primary"].bounds[0])
    _, patterns, truth_rows = load_window_truth_details(truth_path, window_name="primary", scope="test_visible")
    cycle_ids = {ring_id for ring_id, name in patterns.items() if str(name).upper() == "CYCLE"}
    scores = pd.read_parquet(scores_path, columns=["edge_id", "from_id", "to_id", "timestamp", "score_calibrated"])
    shifted, removed = remove_day8_pattern(scores, truth_rows, cycle_ids, primary_start)
    real = hourly_series(shifted, primary_start)
    control, step = with_synthetic_step(real)
    real_rows, real_detection = replay_monitor(real, delta=delta, tenant_id=tenant_id, onset_step=24)
    control_rows, control_detection = replay_monitor(control, delta=delta, tenant_id=tenant_id,
                                                     onset_step=CONTROL_START_STEP)
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv_and_markdown(real_rows, output_dir / "monitor_real.csv", output_dir / "monitor_real.md")
    write_csv_and_markdown(control_rows, output_dir / "monitor_control.csv", output_dir / "monitor_control.md")
    control_md = output_dir / "monitor_control.md"
    control_md.write_text(f"{SYNTHETIC}. Step from hour {CONTROL_START_STEP} (hour 12 of day 9): "
                          f"mean +{step['mean']:.6f}, p99 +{step['p99']:.6f}.\n\n"
                          + control_md.read_text(encoding="utf-8"), encoding="utf-8")
    real_md = output_dir / "monitor_real.md"
    real_md.write_text("drift was injected, not observed. CYCLE removed from day 8 "
                       f"({removed} transactions); day 9 unchanged.\n\n"
                       + real_md.read_text(encoding="utf-8"), encoding="utf-8")
    return {"removed_cycle_transactions": removed, "n_cycle_truth_rings": len(cycle_ids),
            "real": real_detection, "control": control_detection, "control_step": step,
            "adwin": {"delta": delta, "clock": int(DriftStream(delta=delta, tenant_id=tenant_id)
                                                  .detectors[MONITORS["mean"]].clock)}}


def _fixture_dry_report(config: dict, *, pattern: str) -> dict:
    output_dir = REPO_ROOT / "results" / "platform" / "r12" / "dry_fixture"
    insertion_day = 8 + 128
    daily = [(8 + index, 0.0 if index < 128 else 1.0,
              0.0 if index < 128 else 1.0) for index in range(256)]
    stream = DriftStream(delta=float(config["l6"]["drift"]["delta"]), tenant_id=-99)
    events = [event for point in daily for event in stream.update(*point)]
    mean_events = [event for event in events if event["monitor"] == "adwin_score_mean"]
    detected_day = ((int(mean_events[0]["window_end"].timestamp()) - DAY_ZERO)
                    // SECONDS_PER_DAY - 1) if mean_events else None
    delay = detected_day - insertion_day if detected_day is not None else None
    truth = {1: {11, 12}}
    before = {"ring_recall": 0.0, "member_coverage": 0.0}
    after = {"ring_recall": 1.0, "member_coverage": 1.0}
    rows = [
        {"lane": "no_retrain_control", "recall_before_insertion": before["ring_recall"],
         "recall_after_insertion_without_retrain": after["ring_recall"],
         "recall_after_gated_retrain": None,
         "control_note": "fixture only; gated retrain was not executed"},
        {"lane": "gated_retrain", "recall_before_insertion": before["ring_recall"],
         "recall_after_insertion_without_retrain": after["ring_recall"],
         "recall_after_gated_retrain": None,
         "control_note": "fixture only; no supplied held-out model"},
    ]
    csv_path = output_dir / "recall.csv"
    md_path = output_dir / "recall.md"
    write_csv_and_markdown(rows, csv_path, md_path)
    report_header = (
        f"DRY RUN FIXTURE ONLY for pattern {pattern}. No real detector, analyst, or retrain ran.\n"
        "drift was injected, not observed.\n\n"
        f"Fixture insertion day: {insertion_day}; ADWIN mean detection day: {detected_day}; "
        f"detection delay (simulated days): {delay}. The final recall column is null because "
        "the gated retrain was not executed in dry mode.\n\n"
    )
    md_path.write_text(report_header + md_path.read_text(encoding="utf-8"), encoding="utf-8")
    run_path = write_run_manifest(
        output_dir, experiment="r12_injected_shift", config=config,
        inputs=[Path(__file__)],
        details={"dry_run": True, "fixture_only": True, "pattern": pattern,
                 "insertion_day": insertion_day, "detection_day": detected_day,
                 "detection_delay_simulated_days": delay,
                 "n_events": len(events), "n_truth_fixture_rings": len(truth),
                 "statement": "drift was injected, not observed"},
    )
    return {"dry_run": True, "csv": str(csv_path), "markdown": str(md_path),
            "run_json": str(run_path), "detection_delay_simulated_days": delay}


def run_experiment(*, tenant_id: int | None = None, dry: bool = False,
                   pattern: str | None = None) -> dict:
    config = load_platform_config()
    selected_pattern = str(pattern or (config.get("r12") or {}).get("pattern", "BIPARTITE")).upper()
    model_dir_value = (config.get("r12") or {}).get("model_dir")
    model_path = Path(model_dir_value) if model_dir_value else None
    if model_path is not None and not model_path.is_absolute():
        model_path = REPO_ROOT / model_path
    if dry or model_path is None or not model_path.is_dir():
        return _fixture_dry_report(config, pattern=selected_pattern)
    if selected_pattern != "CYCLE":
        raise ExperimentInputError("R12 is registered for CYCLE only (docs/R12.md)")
    return registered_run(config=config, tenant_id=tenant_id or EXPERIMENT_TENANT_ID)


EXPERIMENT_TENANT_ID = 900_001   # the dedicated R12 experiment tenant; not a bank code


def registered_run(*, config: dict, tenant_id: int) -> dict:
    """R12 as registered in docs/R12.md. Stage 1 is the monitor on the real stream and on the
    synthetic positive control; if the control does not fire, R12 stops: the monitor is broken."""
    started = datetime.now(timezone.utc)
    truth_value = (config.get("l6", {}).get("retrain", {}) or {}).get("truth_parquet")
    if not truth_value:
        raise ExperimentInputError("platform config l6.retrain.truth_parquet is unavailable")
    truth_path = configured_path({"truth": truth_value}, "truth")
    scores_path = configured_path(config, "scored_edges")
    output_dir = REPO_ROOT / "results" / "platform" / "r12" / "registered"
    delta = float(config["l6"]["drift"]["delta"])
    monitor = monitor_stage(scores_path=scores_path, truth_path=truth_path, delta=delta,
                            tenant_id=tenant_id, output_dir=output_dir)
    details = {"registered": "docs/R12.md, 2026-10-24", "statement": "drift was injected, not observed",
               "experiment_tenant_id": tenant_id, **monitor}
    if not monitor["control"]["detected"]:
        details["stopped"] = ("the synthetic positive control did not fire: the monitor is broken; "
                              "R12 stops here as registered")
    details["wall_time_seconds"] = round((datetime.now(timezone.utc) - started).total_seconds(), 1)
    run_json = write_run_manifest(output_dir, experiment="r12_injected_shift", config=config,
                                  inputs=[truth_path, scores_path], details=details)
    return {"run_json": str(run_json), **details}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=int)
    parser.add_argument("--pattern")
    parser.add_argument("--dry", action="store_true",
                        help="write clearly labeled fixture output without research data or database writes")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run_experiment(tenant_id=args.tenant_id, dry=args.dry,
                                        pattern=args.pattern), indent=2))
    except (ExperimentInputError, RuntimeError, ValueError, OSError) as exc:
        parser.exit(2, f"R12 input or execution error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
