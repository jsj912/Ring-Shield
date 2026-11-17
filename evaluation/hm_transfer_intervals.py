"""HI-Medium transfer close-out, seed S: intervals and per-day budget shares (author item 4, 2026-11-17).

    RINGSHIELD_PATHS=experiments/R18_hm_transfer/paths_hm_transfer.yaml \
    .venv312/Scripts/python.exe -u evaluation/hm_transfer_intervals.py --seed 1

Reads the rings written by hm_transfer_closeout (experiments/R18_hm_transfer/closeout/<window>/<rule>/<method>/seed<S>.parquet),
rebuilds ring evidence with evaluation.ring_stats.ring_evidence and gives percentile intervals over truth rings
(bootstrap_over_rings, 10,000 draws, seed 0) for ring precision, recall and ring-F1, every window x rule x method.
Per-day budget shares: share of the primary (days 6-14) seed edges on each day under each rule.
New file only: results/tables/hm_transfer_closeout_seed<S>_ci.csv and _budget_shares.csv. Nothing frozen is touched.
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
WINDOWS = [("primary", 6, 14), ("block6-7", 6, 7), ("block8-9", 8, 9), ("block10-11", 10, 11),
           ("block12-13", 12, 13), ("block14-15", 14, 15), ("day15", 15, 15)]
METHODS = ("b0", "proposed", "full", "b1b")
METRICS = ("ring_precision", "ring_recall", "ring_f1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-boot", type=int, default=10000)
    a = ap.parse_args()
    import evaluation.hm_closeout as hc
    from evaluation.ring_stats import bootstrap_over_rings, ring_evidence
    from preprocessing.account_bank import load_paths
    from ringshield.aggregators.cc import SELECT_COL
    from ringshield.rings import read_rings_parquet
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import Window, load_windows

    S = a.seed
    pdir = load_paths()["processed_dir"]
    gt = pdir / "amlworld_ring_ground_truth.parquet"
    base = R / "experiments/R18_hm_transfer"
    se = build_scored_edges(base / f"closeout_input/R1_gine_causal_c1prime/scores_test_seed{S}.parquet", "test",
                            model_id="gine_causal", seed=S, processed_dir=pdir)
    P0 = load_windows()["primary"]
    rows = []
    for name, lo, hi in WINDOWS:
        W = Window(name, "test", lo, hi, P0.day_zero, P0.seconds_per_day)
        truth, pats = load_ground_truth(gt, *W.bounds, "test_visible", verbose=False)
        for rule in ("global", "per_day"):
            for m in METHODS:
                rings = read_rings_parquet(base / "closeout" / name / rule / m / f"seed{S}.parquet")
                ev = ring_evidence(rings, se, truth, W, method=m, seed=S, patterns=pats)
                bs = bootstrap_over_rings([ev], n_resamples=a.n_boot, metrics=METRICS)
                r = {"seed": S, "window": name, "rule": rule, "method": m, "n_truth": len(truth), "n_rings": len(rings)}
                for k in METRICS:
                    r[k], r[k + "_lo"], r[k + "_hi"] = bs[k]["point"], bs[k]["lo"], bs[k]["hi"]
                rows.append(r)
                print(name, rule, m, {k: round(r[k], 4) for k in METRICS}, flush=True)
    out = R / f"results/tables/hm_transfer_closeout_seed{S}_ci.csv"
    pd.DataFrame(rows).to_csv(out, index=False)

    # per-day budget shares on the primary window
    W = Window("primary", "test", 6, 14, P0.day_zero, P0.seconds_per_day)
    sc, ts, eid = se[SELECT_COL].to_numpy(float), se["timestamp"].to_numpy(np.int64), se["edge_id"].to_numpy(np.int64)
    in_w = W.mask(ts)
    day = (ts - P0.day_zero) // P0.seconds_per_day
    g = np.zeros(len(sc), bool); g[in_w] = hc.topk_mask(sc[in_w], eid[in_w])
    pdm = np.zeros(len(sc), bool)
    for d in range(6, 15):
        md = in_w & (day == d)
        pdm[md] = hc.topk_mask(sc[md], eid[md])
    b = []
    for d in range(6, 15):
        md = in_w & (day == d)
        b.append({"day": d, "n_edges": int(md.sum()), "seeds_global": int((g & md).sum()),
                  "share_global": (g & md).sum() / g.sum(), "seeds_per_day": int((pdm & md).sum()),
                  "share_per_day": (pdm & md).sum() / pdm.sum()})
    bd = pd.DataFrame(b)
    bd.to_csv(R / f"results/tables/hm_transfer_closeout_seed{S}_budget_shares.csv", index=False)
    print(bd.to_string(index=False))


if __name__ == "__main__":
    main()
