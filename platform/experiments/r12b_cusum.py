"""R12b: a drift monitor with a passing positive control (docs/deep-analysis.md #6, registered 2026-11-12).

    python -m experiments.r12b_cusum          # from platform/  -> results/platform/r12b/

SYNTHETIC POSITIVE CONTROL; drift is injected, not observed. Everything below is fixed by the
registration: the R12 stream (seed-1 scored edges, CYCLE removed from day 8, 48 hourly steps of
days 8-9), two statistics standardised on day 8 (S1 share above the seed cutoff, S2 raw-score p99),
two upper monitors starting at day 9 hour 0 (CUSUM k=0.5 h=4; Page-Hinkley delta=0.5 lambda=4), a
control ladder (+1/+3/+5 SD from index 36), and a false-alarm bound (no alarm in-sample on day 8 and
none on the real stream before the onset). Success: an eligible arm detects +3 SD within 6 h.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PLATFORM_ROOT.parent
sys.path.insert(0, str(PLATFORM_ROOT))
sys.path.insert(1, str(REPO_ROOT))

from adapters.ground_truth import load_window_truth_details  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402
from settings import configured_path, load_platform_config  # noqa: E402

OUT = REPO_ROOT / "results" / "platform" / "r12b"
HOUR, STEPS, ONSET, MON_START = 3600, 48, 36, 24
K, H = 0.5, 4.0
LADDER = (1.0, 3.0, 5.0)
SUCCESS_RUNG, MAX_DELAY = 3.0, 6


SYNTHETIC = "SYNTHETIC POSITIVE CONTROL: a step added to the monitor input, not data"
R12_REMOVED = 31                    # results/platform/r12/*: removed_cycle_transactions


def remove_day8_pattern(scores, truth_rows, pattern_ids, primary_start):
    """Verbatim copy of experiments.r12_injected_shift.remove_day8_pattern (that module imports
    river, which this environment lacks); the removed count is asserted against R12's record."""
    day9 = primary_start + 86_400
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


def cusum(z, start):
    c, alarms = 0.0, []
    for t in range(start, len(z)):
        c = max(0.0, c + z[t] - K)
        if c > H:
            alarms.append(t)
            c = 0.0                                   # restart after an alarm
    return alarms


def page_hinkley(z, start):
    m, mmin, alarms = 0.0, 0.0, []
    for t in range(start, len(z)):
        m += z[t] - K
        mmin = min(mmin, m)
        if m - mmin > H:
            alarms.append(t)
            m, mmin = 0.0, 0.0
    return alarms


MONITORS = {"cusum": cusum, "page_hinkley": page_hinkley}


def main() -> int:
    config = load_platform_config()
    start = int(load_windows()["primary"].bounds[0])
    scored = configured_path(config, "scored_edges")
    q = float(json.loads(Path(str(scored) + ".log.json").read_text(encoding="utf-8"))["seed_rule"]["q"])
    truth = configured_path({"truth": config["l6"]["retrain"]["truth_parquet"]}, "truth")
    _, patterns, truth_rows = load_window_truth_details(truth, window_name="primary", scope="test_visible")
    cycle = {ring for ring, name in patterns.items() if str(name).upper() == "CYCLE"}
    scores = pd.read_parquet(scored, columns=["edge_id", "from_id", "to_id", "timestamp", "score_raw", "score_calibrated"])
    shifted, removed = remove_day8_pattern(scores, truth_rows, cycle, start)
    assert removed == R12_REMOVED, f"removed {removed} CYCLE rows, R12 removed {R12_REMOVED}"
    w = shifted[(shifted["timestamp"] >= start) & (shifted["timestamp"] < start + STEPS * HOUR)]
    hour = ((w["timestamp"] - start) // HOUR).astype(int)
    g = w.assign(hour=hour).groupby("hour")["score_raw"]
    n = g.size().reindex(range(STEPS)).to_numpy()
    assert (n > 0).all(), "an empty hour"
    raw = {"S1_share_above_cutoff": g.apply(lambda s: float((s > q).mean())).reindex(range(STEPS)).to_numpy(float),
           "S2_raw_p99": g.quantile(0.99).reindex(range(STEPS)).to_numpy(float)}

    arms, series_out, summary = [], {}, {}
    for stat, x in raw.items():
        mu, sd = float(x[:24].mean()), float(x[:24].std(ddof=1))
        z = (x - mu) / sd
        ac1 = float(np.corrcoef(x[:23], x[1:24])[0, 1])
        summary[stat] = {"day8_mean": mu, "day8_sd": sd, "lag1_autocorr_day8": round(ac1, 4),
                         "day9_pre_onset_mean_z": round(float(z[24:36].mean()), 3), "day9_post_onset_mean_z_real": round(float(z[36:].mean()), 3)}
        series_out[stat] = {"raw": x.tolist(), "z_real": z.round(4).tolist()}
        for mon, fn in MONITORS.items():
            fa_day8 = fn(z[:24], 0)
            fa_pre = [t for t in fn(z, MON_START) if t < ONSET]
            eligible = not fa_day8 and not fa_pre
            rungs = {}
            for sd_step in (0.0,) + LADDER:
                zz = z + sd_step * (np.arange(STEPS) >= ONSET)
                al = fn(zz, MON_START)
                post = [t for t in al if t >= ONSET]
                rungs["real" if sd_step == 0 else f"+{sd_step:g}SD"] = {
                    "alarms": al, "first_post_onset": post[0] if post else None,
                    "delay_h": (post[0] - (ONSET - 1)) if post else None}
            hit = rungs[f"+{SUCCESS_RUNG:g}SD"]["delay_h"]
            arms.append({"statistic": stat, "monitor": mon, "false_alarms_day8": fa_day8, "false_alarms_pre_onset": fa_pre,
                         "eligible": eligible, "ladder": rungs,
                         "passes": bool(eligible and hit is not None and hit <= MAX_DELAY)})
    success = any(a["passes"] for a in arms)
    OUT.mkdir(parents=True, exist_ok=True)
    rec = {"synthetic": SYNTHETIC, "statement": "drift was injected, not observed; the control is synthetic",
           "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "registration": "docs/deep-analysis.md #6 (2026-11-12)",
           "scored_edges": str(scored), "seed_cutoff_q": q, "removed_cycle_transactions": int(removed),
           "edges_per_hour": {"min": int(n.min()), "median": int(np.median(n)), "max": int(n.max())},
           "monitors": {"cusum": {"k": K, "h": H}, "page_hinkley": {"delta": K, "lambda": H}, "start_index": MON_START},
           "onset_index": ONSET, "ladder_sd": LADDER, "success_rule": f"eligible arm, +{SUCCESS_RUNG:g} SD, delay <= {MAX_DELAY} h",
           "statistics": summary, "arms": arms, "success": success, "series": series_out}
    (OUT / "summary.json").write_text(json.dumps(rec, indent=2, default=int), encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("seed_cutoff_q", "removed_cycle_transactions", "edges_per_hour", "statistics")}, indent=1))
    for a in arms:
        lad = " | ".join(f"{k}: {v['delay_h']}" for k, v in a["ladder"].items())
        print(f"{a['statistic']:22s} {a['monitor']:13s} FA day8 {a['false_alarms_day8']} pre {a['false_alarms_pre_onset']} "
              f"eligible {a['eligible']} | delays(h) {lad} | all alarms real {a['ladder']['real']['alarms']} | PASS {a['passes']}")
    print(f"SUCCESS: {success}  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
