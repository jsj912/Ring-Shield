"""Why R12's positive control did not fire (docs/R12.md, Diagnosis, 2026-10-25).

    python -m experiments.r12_diagnose          # -> results/platform/r12/diagnosis/

Rebuilds the registered run's two hourly streams exactly as experiments.r12_injected_shift did,
replays the control through the instrumented ADWIN (experiments.adwin_trace, checked against
river at every step) with the registered clock=32 and with clock=1, and writes the per-step trace:
whether ADWIN tested, the window size, and for every cut n0, n1, the mean difference and epsilon.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from adapters.ground_truth import load_window_truth_details  # noqa: E402
from experiments import r12_injected_shift as r12  # noqa: E402
from experiments.adwin_trace import TracedADWIN, assert_matches_river  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402

OUT = REPO_ROOT / "results" / "platform" / "r12" / "diagnosis"


def registered_streams(config: dict) -> dict:
    """The real (CYCLE removed from day 8) and control hourly series, and the shifted scores."""
    start = int(load_windows()["primary"].bounds[0])
    truth = configured_path({"truth": config["l6"]["retrain"]["truth_parquet"]}, "truth")
    _, patterns, truth_rows = load_window_truth_details(truth, window_name="primary", scope="test_visible")
    cycle = {ring for ring, name in patterns.items() if str(name).upper() == "CYCLE"}
    scores = pd.read_parquet(configured_path(config, "scored_edges"),
                             columns=["edge_id", "from_id", "to_id", "timestamp", "score_calibrated"])
    shifted, removed = r12.remove_day8_pattern(scores, truth_rows, cycle, start)
    real = r12.hourly_series(shifted, start)
    control, step = r12.with_synthetic_step(real)
    return {"start": start, "shifted": shifted, "removed": removed, "real": real, "control": control, "step": step}


def trace(values: list[float], *, delta: float, clock: int) -> list[dict]:
    assert_matches_river(values, delta=delta, clock=clock)
    detector = TracedADWIN(delta=delta, clock=clock)
    return [{"step": index, "value": value, **detector.update(value)} for index, value in enumerate(values, start=1)]


def main() -> int:
    config = load_platform_config()
    delta = float(config["l6"]["drift"]["delta"])
    streams = registered_streams(config)
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    for clock in (32, 1):
        record = {"synthetic": r12.SYNTHETIC, "adwin": {"implementation": "river 0.22.0 ADWIN, traced copy",
                  "delta": delta, "clock": clock, "max_buckets": 5, "min_window_length": 5, "grace_period": 10,
                  "units": "raw calibrated-score statistics"},
                  "control_step": streams["step"], "control_start_step": r12.CONTROL_START_STEP + 1, "streams": {}}
        for name, column in (("mean", 1), ("p99", 2)):
            rows = trace([point[column] for point in streams["control"]], delta=delta, clock=clock)
            record["streams"][name] = rows
            tested = [row for row in rows if row["tested"]]
            cuts = [cut for row in tested for cut in row["cuts"] if cut["epsilon"] is not None]
            summary[f"clock{clock}_{name}"] = {
                "steps_tested": [row["step"] for row in tested],
                "fired": any(row["drift_detected"] for row in rows),
                "max_abs_mean_diff": max((abs(cut["mean_diff"]) for cut in cuts), default=None),
                "min_epsilon": min((cut["epsilon"] for cut in cuts), default=None)}
        (OUT / f"trace_control_clock{clock}.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
