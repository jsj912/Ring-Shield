"""Diagnose the GenAgg seed spread (seeds 4, 5) from existing score files only. No training, no rescoring.

    .venv312/Scripts/python.exe evaluation/p7_genagg_seed_spread.py

Threshold tuned on val exactly as r6_detector_swap.edge_f1 (score_raw, 400 quantiles in [0.90, 0.99999], ties to the larger threshold). Test-optimal F1 is a
DIAGNOSTIC only. Days are timestamp // 86400 (loader basis; test spans days 8-17).
Writes results/tables/p7_genagg_seed_spread.csv.
"""
import sys
from pathlib import Path
import numpy as np, pandas as pd
from sklearn.metrics import f1_score, average_precision_score, roc_auc_score, precision_recall_curve

R = Path(__file__).resolve().parents[1]
LAB = Path("E:/JSJ/Ring-Shield/contract/out")
DIRS = {"megagenagg": R / "experiments/R6_megagenagg", "mega": R / "experiments/R6_mega_sb2048",
        "gine_causal": R.parent / "RS-e2e/experiments/R1_gine_causal"}


def load(d, split, s):
    sc = pd.read_parquet(d / f"scores_{split}_seed{s}.parquet", columns=["edge_id", "timestamp", "score_raw"])
    lab = pd.read_parquet(LAB / f"labels_{split}.parquet").set_index("edge_id")["true_label"]
    sc["y"] = lab.reindex(sc.edge_id).to_numpy().astype(int)
    return sc


rows = []
for det, d in DIRS.items():
    for s in range(1, 6):
        v, t = load(d, "val", s), load(d, "test", s)
        grid = np.quantile(v.score_raw.to_numpy(), np.linspace(0.90, 0.99999, 400))  # as r6_detector_swap.edge_f1
        vf_best, thr = max((f1_score(v.y, (v.score_raw >= g).astype(int), zero_division=0), g) for g in grid)
        pr, rc, _ = precision_recall_curve(t.y, t.score_raw)
        opt = float(np.nanmax(2 * pr * rc / np.where(pr + rc > 0, pr + rc, np.nan)))
        day = t.timestamp // 86400
        row = {"detector": det, "seed": s, "val_f1": vf_best, "threshold": thr,
               "val_pos_rate_at_thr": float((v.score_raw >= thr).mean()),
               "test_pos_rate_at_thr": float((t.score_raw >= thr).mean()),
               "test_f1": f1_score(t.y, t.score_raw >= thr), "test_f1_opt_DIAGNOSTIC": opt,
               "test_ap": average_precision_score(t.y, t.score_raw), "test_auc": roc_auc_score(t.y, t.score_raw),
               "val_ap": average_precision_score(v.y, v.score_raw)}
        for nm, m in (("d8_9", day <= 9), ("d10_17", day >= 10)):
            row[f"test_f1_{nm}"] = f1_score(t.y[m], t.score_raw[m] >= thr)
            row[f"test_ap_{nm}"] = average_precision_score(t.y[m], t.score_raw[m])
        rows.append(row); print({k: (round(x, 4) if isinstance(x, float) else x) for k, x in row.items()}, flush=True)
df = pd.DataFrame(rows)
out = R / "results/tables/p7_genagg_seed_spread.csv"; df.to_csv(out, index=False); print("->", out)
