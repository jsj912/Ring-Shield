"""Scoring reproducibility / sampling noise, HI-Small, GenAgg seed 1 (PREREG_RECOVERY amendment, addendum 3).

    .venv312/Scripts/python.exe evaluation/scoring_noise.py

Pairs (each compared on validation and test):
  orig_vs_orig     two runs of models/mega_adapter.py --score-only, identical settings (experiments/R18_hm_transfer/hs_orig_run{1,2})
  orig_vs_rng1000  same, but every RNG seed offset by 1000 (hs_rng1000): runs that differ only in random state
  orig_vs_stored   current scoring vs the stored experiments/R6_megagenagg files
Per pair: share of edges with |diff| > 1e-6 and > 1e-4, |diff| quantiles, Spearman; top-0.1 % seed edges (whole split,
seed_mask_for_pct) overlap count and Jaccard; edge F1 at each run's own validation threshold (reference grid).
B0 ring-F1 is read from each run's ring output (test), and from the stored B0 run for the stored scores.
Writes results/tables/scoring_noise_hs_genagg_s1.csv.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import f1_score

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
from ringshield.aggregators.cc import seed_mask_for_pct  # noqa: E402

D = R / "experiments" / "R18_hm_transfer"
RUNS = {"orig1": D / "hs_orig_run1", "orig2": D / "hs_orig_run2", "rng1000": D / "hs_rng1000", "stored": R / "experiments" / "R6_megagenagg"}
LAB = Path("E:/JSJ/Ring-Shield/contract/out")


def ld(run, split):
    return pd.read_parquet(RUNS[run] / f"scores_{split}_seed1.parquet", columns=["edge_id", "score_raw"]).set_index("edge_id")["score_raw"].sort_index()


def val_thr(run):
    v = ld(run, "val")
    y = pd.read_parquet(LAB / "labels_val.parquet").set_index("edge_id")["true_label"].reindex(v.index).to_numpy()
    sv = v.to_numpy()
    grid = np.quantile(sv, np.linspace(0.90, 0.99999, 400))
    return max((f1_score(y, (sv >= t).astype(int), zero_division=0), t) for t in grid)[1]


def edge_f1(run, split, thr):
    s = ld(run, split)
    y = pd.read_parquet(LAB / f"labels_{split}.parquet").set_index("edge_id")["true_label"].reindex(s.index).to_numpy()
    return f1_score(y, (s.to_numpy() >= thr).astype(int))


def main():
    thr = {r: val_thr(r) for r in RUNS}
    rows = []
    for name, a, b in (("orig_vs_orig", "orig1", "orig2"), ("orig_vs_rng1000", "orig1", "rng1000"), ("orig_vs_stored", "orig1", "stored")):
        for split in ("val", "test"):
            x, y = ld(a, split), ld(b, split)
            assert x.index.equals(y.index)
            d = (x - y).abs().to_numpy()
            mx = seed_mask_for_pct(x.to_numpy(float), 0.1); my = seed_mask_for_pct(y.to_numpy(float), 0.1)
            inter = int((mx & my).sum()); union = int((mx | my).sum())
            rows.append({"pair": name, "split": split, "n": len(d), "share_gt_1e-6": float((d > 1e-6).mean()),
                         "share_gt_1e-4": float((d > 1e-4).mean()), "n_gt_1e-4": int((d > 1e-4).sum()),
                         "diff_p50": float(np.quantile(d, .5)), "diff_p99": float(np.quantile(d, .99)),
                         "diff_p999": float(np.quantile(d, .999)), "diff_max": float(d.max()),
                         "spearman": float(spearmanr(x, y).statistic),
                         "top01_a": int(mx.sum()), "top01_b": int(my.sum()), "top01_both": inter,
                         "top01_jaccard": inter / union if union else np.nan,
                         "thr_a": thr[a], "thr_b": thr[b], "edge_f1_a": edge_f1(a, split, thr[a]), "edge_f1_b": edge_f1(b, split, thr[b])})
            print({k: (round(v, 6) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(R / "results/tables/scoring_noise_hs_genagg_s1.csv", index=False)


if __name__ == "__main__":
    main()
