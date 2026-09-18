"""Aggregate ringshield/run_rings.py outputs over seeds into one table (Step 4.5).

    python evaluation/aggregate_results.py --root experiments/R2_b0 --out results/tables/r2_ring_b0.csv

Layout expected under --root: <model>/seed<S>/metrics.json (written by ringshield/run_rings.py).
Score directories (<model>_scores) are ignored. One row per model: mean +/- std (ddof=1) over
seeds of the PRIMARY block's ring precision / recall / F1, Ring-Recall>=3, member coverage and
mean Jaccard, the per-pattern recalls, seed-edge precision and illicit recall in the primary
window, the chosen val cell (mode over seeds), and the tail / whole F1 for reference. Rows are
tagged with feature_set / reportable from the runs' metrics.json. Confidence intervals: 'CIs
pending Step 9' (the ci column says so; the bootstrap over seeds lands in Step 9).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_METRICS = ["ring_precision", "ring_recall", "ring_f1", "ring_recall_ge3", "member_coverage", "mean_jaccard"]
PATTERNS = ["FAN-OUT", "FAN-IN", "GATHER-SCATTER", "SCATTER-GATHER", "CYCLE", "RANDOM", "BIPARTITE", "STACK"]


def load_runs(root: Path) -> dict[str, list[dict]]:
    runs: dict[str, list[dict]] = {}
    for p in sorted(root.glob("*/seed*/metrics.json")):
        model = p.parent.parent.name
        if model.endswith("_scores"):
            continue
        j = json.loads(p.read_text(encoding="utf-8"))
        j["_seed_dir"] = p.parent.name
        runs.setdefault(model, []).append(j)
    return runs


def _ms(values):
    v = np.array([x for x in values if x is not None], dtype=float)
    if len(v) == 0:
        return np.nan, np.nan
    return float(v.mean()), (float(v.std(ddof=1)) if len(v) > 1 else 0.0)


def row_for(model: str, runs: list[dict]) -> dict:
    blk = [r["blocks"]["primary"] for r in runs]
    row = {"model": model, "n_seeds": len(runs),
           "seeds": " ".join(sorted(r["_seed_dir"].replace("seed", "") for r in runs)),
           "feature_set": Counter(r.get("feature_set", "?") for r in runs).most_common(1)[0][0],
           "reportable": all(r.get("reportable", True) for r in runs),
           "identical_seeds": bool(all(r.get("chosen") == runs[0].get("chosen") for r in runs) and
                                   len({json.dumps(b["ring_f1"]) for b in blk}) == 1 and len(runs) > 1),
           "aggregator": runs[0].get("aggregator"), "scope": runs[0].get("scope"),
           "window": f"days {blk[0]['window']['days']}", "n_truth_rings": blk[0]["n_truth"],
           "chosen_seed_frac_pct": Counter(r["chosen"]["seed_frac_pct"] for r in runs).most_common(1)[0][0],
           "chosen_min_size": Counter(r["chosen"]["min_size"] for r in runs).most_common(1)[0][0],
           "chosen_cells": "; ".join(f"{r['chosen']['seed_frac_pct']}/{r['chosen']['min_size']}" for r in runs),
           "val_ring_f1_mean": _ms([r["val_at_chosen"]["ring_f1"] for r in runs])[0]}
    for m in PRIMARY_METRICS:
        mean, std = _ms([b.get(m) for b in blk])
        row[f"{m}_mean"], row[f"{m}_std"] = mean, std
    row["n_pred_rings_mean"] = _ms([b["n_predicted"] for b in blk])[0]
    for pat in PATTERNS:
        vals = [b.get("per_pattern", {}).get(pat, {}).get("recall") for b in blk]
        row[f"recall_{pat}_mean"] = _ms(vals)[0]
    sv = [b.get("seed_edges_vs_labels") or {} for b in blk]
    row["seed_edge_precision_mean"], row["seed_edge_precision_std"] = _ms([s.get("seed_edge_precision") for s in sv])
    row["seed_edge_recall_of_illicit_mean"] = _ms([s.get("seed_edge_recall_of_illicit") for s in sv])[0]
    row["n_seed_edges_mean"] = _ms([s.get("n_seed_edges") for s in sv])[0]
    for name in ("tail", "whole"):
        row[f"{name}_ring_f1_mean"], row[f"{name}_ring_f1_std"] = _ms([r["blocks"][name]["ring_f1"] for r in runs])
        row[f"{name}_ring_recall_mean"] = _ms([r["blocks"][name]["ring_recall"] for r in runs])[0]
    row["jaccard03_f1_mean"] = _ms([b["jaccard_sweep"].get("0.3", {}).get("ring_f1") for b in blk])[0]
    row["jaccard07_f1_mean"] = _ms([b["jaccard_sweep"].get("0.7", {}).get("ring_f1") for b in blk])[0]
    row["appendix_strict_f1_mean"] = _ms([b["appendix"]["strict"]["ring_f1"] for b in blk])[0]
    row["appendix_majority_f1_mean"] = _ms([b["appendix"]["majority"]["ring_f1"] for b in blk])[0]
    row["ci"] = "CIs pending Step 9"
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--order", nargs="*", default=["gine_causal", "gfpxgb", "density"])
    args = ap.parse_args(argv)
    runs = load_runs(args.root)
    if not runs:
        sys.exit(f"no <model>/seed*/metrics.json under {args.root}")
    rows = [row_for(m, r) for m, r in runs.items()]
    df = pd.DataFrame(rows)
    order = {m: i for i, m in enumerate(args.order)}
    df = df.assign(_o=df["model"].map(lambda m: order.get(m, len(order)))).sort_values(["_o", "model"]).drop(columns="_o")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    meta = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "root": str(args.root),
            "models": {m: [r["_seed_dir"] for r in rs] for m, rs in runs.items()},
            "primary_window": rows[0]["window"], "note": "CIs pending Step 9"}
    args.out.with_suffix(".log.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    pd.set_option("display.width", 220)
    show = ["model", "n_seeds", "feature_set", "reportable", "chosen_seed_frac_pct", "chosen_min_size", "ring_precision_mean",
            "ring_recall_mean", "ring_f1_mean", "ring_f1_std", "ring_recall_ge3_mean", "member_coverage_mean",
            "seed_edge_precision_mean", "seed_edge_recall_of_illicit_mean", "tail_ring_f1_mean", "whole_ring_f1_mean"]
    print(df[show].round(4).to_string(index=False))
    print("per-pattern recall (primary):")
    print(df[["model"] + [f"recall_{p}_mean" for p in PATTERNS]].round(3).to_string(index=False))
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
