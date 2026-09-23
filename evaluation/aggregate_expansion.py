"""R3 table: B0 (from R2), B1, B1b, the proposed policy and its ablations over the detector seeds (Step 6.4).

    python evaluation/aggregate_expansion.py --runs experiments/R3_expansion/runs \\
        --b0 experiments/R2_b0/gine_causal --out results/tables/r3_expansion.csv

One row per method: mean +/- std (ddof=1) over seeds of the PRIMARY block's ring precision /
recall / F1, Ring-Recall>=3, member coverage and mean Jaccard; the chosen (delta_t, p_min) per
seed; the policy's grouped-CV AUC-PR; the expansion diagnostics (expanded edges that are member
edges of a truth ring vs not, truth member accounts newly covered relative to B0); and the
tail / whole F1 for reference. Since Step 9 every row also carries `quiet_member_recall` with its
bootstrap CI and the CIs of the ring metrics, read from the Step 9 companions
(`results/tables/r9_quiet_members.csv`, `r9_ring_ci.csv`) by `aggregate_results.step9_lookup`.
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

PRIMARY = ["ring_precision", "ring_recall", "ring_f1", "ring_recall_ge3", "member_coverage", "mean_jaccard"]
ORDER = ["b0", "b1", "b1b", "proposed", "no_detector", "no_account_state", "no_embedding", "hop1"]
LABELS = {"b0": "B0 cc (R2)", "b1": "B1 rule: shared endpoint within dt", "b1b": "B1b rule: shared endpoint and quantile > 0.99",
          "proposed": "proposed: LightGBM policy", "no_detector": "ablation: drop detector group",
          "no_account_state": "ablation: drop account_state group", "no_embedding": "ablation: drop embedding group",
          "hop1": "ablation: hop-1 rows only"}


def row_for(name: str, runs: list[dict]) -> dict:
    blk = [r["blocks"]["primary"] for r in runs]
    row = {"method": name, "label": LABELS.get(name, name), "n_seeds": len(runs),
           "seeds": " ".join(sorted(r["_seed_dir"].replace("seed", "") for r in runs)),
           "aggregator": runs[0].get("aggregator"), "window": f"days {blk[0]['window']['days']}", "n_truth_rings": blk[0]["n_truth"]}
    for m in PRIMARY:
        mu, sd = _ms([b.get(m) for b in blk])
        row[f"{m}_mean"], row[f"{m}_std"] = mu, sd
    row["n_pred_rings_mean"] = _ms([b["n_predicted"] for b in blk])[0]
    ch = [r["chosen"] for r in runs]
    if "delta_t_h" in ch[0]:
        row["chosen_cells"] = "; ".join(f"{c['delta_t_h']:.0f}h/{c['p_min']}" for c in ch)
        row["val_ring_f1_mean"] = _ms([c.get("val_ring_f1") for c in ch])[0]
    else:
        row["chosen_cells"] = "; ".join(f"{c['seed_frac_pct']}/{c['min_size']}" for c in ch)
        row["val_ring_f1_mean"] = _ms([c.get("val_ring_f1") for c in ch])[0]
    row["policy_cv_auc_pr"] = runs[0].get("policy_cv_auc_pr")
    ex = [b.get("expansion") for b in blk]
    if all(e for e in ex):
        row["expanded_true_member_mean"] = _ms([e["expanded_true_member"] for e in ex])[0]
        row["expanded_not_member_mean"] = _ms([e["expanded_not_member"] for e in ex])[0]
        row["expanded_member_precision_mean"] = _ms([e["expanded_member_precision"] for e in ex])[0]
        row["quiet_accounts_newly_covered_mean"] = _ms([e["quiet_accounts_newly_covered"] for e in ex])[0]
        row["accounts_lost_vs_b0_mean"] = _ms([e["accounts_lost_vs_b0"] for e in ex])[0]
        row["non_truth_accounts_added_mean"] = _ms([e["non_truth_accounts_added"] for e in ex])[0]
    else:
        for k in ("expanded_true_member_mean", "expanded_not_member_mean", "expanded_member_precision_mean",
                  "quiet_accounts_newly_covered_mean", "accounts_lost_vs_b0_mean", "non_truth_accounts_added_mean"):
            row[k] = 0.0 if name == "b0" else np.nan
    row.update(step9_lookup(name))
    for w in ("tail", "whole"):
        mu, sd = _ms([r["blocks"][w]["ring_f1"] for r in runs])
        row[f"{w}_ring_f1_mean"], row[f"{w}_ring_f1_std"] = mu, sd
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=REPO_ROOT / "experiments" / "R3_expansion" / "runs")
    ap.add_argument("--b0", type=Path, default=REPO_ROOT / "experiments" / "R2_b0" / "gine_causal")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r3_expansion.csv")
    args = ap.parse_args(argv)
    runs = load_runs(args.runs)
    b0 = []
    for p in sorted(args.b0.glob("seed*/metrics.json")):
        j = json.loads(p.read_text(encoding="utf-8"))
        j["_seed_dir"] = p.parent.name
        b0.append(j)
    if b0:
        runs["b0"] = b0
    rows = [row_for(n, runs[n]) for n in ORDER if n in runs] + [row_for(n, r) for n, r in runs.items() if n not in ORDER]
    df = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "runs_root": str(args.runs), "b0_root": str(args.b0),
           "n_methods": len(df), "seeds_per_method": {r["method"]: r["seeds"] for r in rows}, "out": str(args.out)}
    Path(str(args.out).replace(".csv", ".log.json")).write_text(json.dumps(log, indent=2), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"[aggregate_expansion] {len(df)} rows -> {args.out}")
    for r in rows:
        print(f"  {r['method']:17s} n={r['n_seeds']}  P {r['ring_precision_mean']:.3f}±{r['ring_precision_std']:.3f}  "
              f"R {r['ring_recall_mean']:.3f}±{r['ring_recall_std']:.3f}  F1 {r['ring_f1_mean']:.3f}±{r['ring_f1_std']:.3f}  "
              f"R>=3 {r['ring_recall_ge3_mean']:.3f}  cov {r['member_coverage_mean']:.3f}  "
              f"exp {r['expanded_true_member_mean']}/{r['expanded_not_member_mean']}  quiet+ {r['quiet_accounts_newly_covered_mean']}  "
              f"cells {r['chosen_cells']}")


if __name__ == "__main__":
    main()
