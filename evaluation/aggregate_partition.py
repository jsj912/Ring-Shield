"""R4 table: B2-B4 and the two affinity clusterings over the detector seeds; 'proposed' = the
clustering with the better VAL ring-F1 per seed (Step 7.4).

    python evaluation/aggregate_partition.py --runs experiments/R4_partition/runs --out results/tables/r4_partition.csv

One row per method: mean +/- std (ddof=1) over seeds of the PRIMARY block's ring precision /
recall / F1, Ring-Recall>=3, mean Jaccard, member coverage, the number of predicted rings with
more than 100 members, the chosen cell per seed, the affinity's grouped-CV AUC-PR, partition
diagnostics (components split, clusters), and tail / whole F1 for reference. The B0 (R2) and
expand (R3 proposed) rows are appended from their own runs for continuity; B2 must reproduce
the R3 proposed row (same expanded subgraph, plain components).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.aggregate_results import _ms, load_runs, step9_lookup  # noqa: E402

PRIMARY = ["ring_precision", "ring_recall", "ring_f1", "ring_recall_ge3", "mean_jaccard", "member_coverage"]
ORDER = ["b0", "expand", "b2", "b3", "b4", "b5", "pivot", "average", "proposed"]
LABELS = {"b0": "B0 cc (R2)", "expand": "expand, R3 proposed (no partition)", "b2": "B2 plain components of the expanded subgraph",
          "b3": "B3 time-windowed components (gap chosen on val)", "b4": "B4 Louvain, weight = mean pair affinity",
          "b5": "B5 CSGM (Collaborative-AML)", "pivot": "affinity + greedy pivot correlation clustering",
          "average": "affinity + average linkage (cut chosen on val)", "proposed": "proposed = pivot / average, val-chosen per seed"}


def _load(root: Path) -> list[dict]:
    out = []
    for p in sorted(root.glob("seed*/metrics.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        j["_seed_dir"] = p.parent.name
        out.append(j)
    return out


def row_for(name: str, runs: list[dict]) -> dict:
    blk = [r["blocks"]["primary"] for r in runs]
    row = {"method": name, "label": LABELS.get(name, name), "n_seeds": len(runs),
           "seeds": " ".join(sorted(r["_seed_dir"].replace("seed", "") for r in runs)), "aggregator": runs[0].get("aggregator"),
           "window": f"days {blk[0]['window']['days']}", "n_truth_rings": blk[0]["n_truth"]}
    for m in PRIMARY:
        mu, sd = _ms([b.get(m) for b in blk])
        row[f"{m}_mean"], row[f"{m}_std"] = mu, sd
    row["n_pred_rings_mean"] = _ms([b["n_predicted"] for b in blk])[0]
    row["max_members_mean"] = _ms([b["pred_size"]["max_members"] for b in blk])[0]
    row["n_rings_gt100_mean"] = _ms([b.get("n_rings_gt100_in_window", sum(1 for _ in [] )) if "n_rings_gt100_in_window" in b
                                     else int(b["pred_size"]["max_members"] is not None and b["pred_size"]["max_members"] > 100) for b in blk])[0]
    ch = [r["chosen"] for r in runs]
    cells = []
    for c in ch:
        if "method" in c:
            extra = {k: c[k] for k in ("gap_h", "resolution", "cut", "threshold") if k in c}
            cells.append(c["method"] + ("" if not extra else " " + "/".join(f"{k}={v}" for k, v in extra.items())))
        elif "delta_t_h" in c:
            cells.append(f"{c['delta_t_h']:.0f}h/{c['p_min']}")
        else:
            cells.append(f"{c['seed_frac_pct']}/{c['min_size']}")
    row["chosen_cells"] = "; ".join(cells)
    row["val_ring_f1_mean"] = _ms([c.get("val_ring_f1") for c in ch])[0]
    row["affinity_cv_auc_pr"] = runs[0].get("affinity_cv_auc_pr")
    tp = [r.get("test_partition") for r in runs]
    row["components_split_mean"] = _ms([t["components_split"] for t in tp])[0] if all(tp) else np.nan
    row["n_clusters_mean"] = _ms([t["n_clusters"] for t in tp])[0] if all(tp) else np.nan
    row["n_dropped_edges_mean"] = _ms([t["n_dropped_edges"] for t in tp])[0] if all(tp) else np.nan
    for w in ("tail", "whole"):
        mu, sd = _ms([r["blocks"][w]["ring_f1"] for r in runs])
        row[f"{w}_ring_f1_mean"], row[f"{w}_ring_f1_std"] = mu, sd
    # r4 row names -> Step 9 method names: 'proposed' is the val-chosen clustering (average on
    # 4 of 5 seeds) and 'expand' is the R3 proposed run shown for continuity
    row.update(step9_lookup({"proposed": "average", "expand": "proposed"}.get(name, name)))
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=REPO_ROOT / "experiments" / "R4_partition" / "runs")
    ap.add_argument("--b0", type=Path, default=REPO_ROOT / "experiments" / "R2_b0" / "gine_causal")
    ap.add_argument("--expand", type=Path, default=REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r4_partition.csv")
    args = ap.parse_args(argv)
    runs = load_runs(args.runs)
    for name, root in (("b0", args.b0), ("expand", args.expand)):
        r = _load(root)
        if r:
            runs[name] = r
    # proposed: per seed the better of pivot / average on VAL
    if "pivot" in runs and "average" in runs:
        prop = []
        by_seed = {m: {r["_seed_dir"]: r for r in runs[m]} for m in ("pivot", "average")}
        for s in sorted(set(by_seed["pivot"]) & set(by_seed["average"])):
            cands = [by_seed["pivot"][s], by_seed["average"][s]]
            prop.append(max(cands, key=lambda r: (r["val_at_chosen"]["ring_f1"], r["method"] == "pivot")))
        runs["proposed"] = prop
    rows = [row_for(n, runs[n]) for n in ORDER if n in runs] + [row_for(n, r) for n, r in runs.items() if n not in ORDER]
    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    Path(str(args.out).replace(".csv", ".log.json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "runs_root": str(args.runs), "n_methods": len(df),
         "seeds_per_method": {r["method"]: r["seeds"] for r in rows}, "proposed_rule": "per seed: pivot vs average by val ring-F1 (ties -> pivot)",
         "out": str(args.out)}, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[aggregate_partition] {len(df)} rows -> {args.out}")
    for r in rows:
        print(f"  {r['method']:9s} n={r['n_seeds']}  P {r['ring_precision_mean']:.3f}±{r['ring_precision_std']:.3f}  R {r['ring_recall_mean']:.3f}±{r['ring_recall_std']:.3f}  "
              f"F1 {r['ring_f1_mean']:.3f}±{r['ring_f1_std']:.3f}  R>=3 {r['ring_recall_ge3_mean']:.3f}  J {r['mean_jaccard_mean']:.3f}  cov {r['member_coverage_mean']:.3f}  "
              f">100 {r['n_rings_gt100_mean']:.1f}  max {r['max_members_mean']:.0f}  split {r['components_split_mean']}  cells {r['chosen_cells']}")


if __name__ == "__main__":
    main()
