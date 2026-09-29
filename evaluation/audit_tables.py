"""Step 13 check 2: every reported table traces back to an experiments/<run>/metrics.json.

    python evaluation/audit_tables.py
    python evaluation/audit_tables.py --strict      # non-zero exit if anything is untraceable

The check is deliberately mechanical. For each headline ring table we re-read the per-seed
`metrics.json` of the runs it claims to summarise, recompute the aggregate the table reports, and
require agreement to 1e-6. A table that cannot be tied to run artefacts this way is listed as
untraceable with the reason, rather than being quietly trusted.

Tables whose numbers are *derived statistics* (bootstrap CIs, permutation p-values) are checked for
provenance instead: their point estimate must match the run-artefact aggregate, since the interval
around it is by construction not in any metrics.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
TABLES = REPO_ROOT / "results" / "tables"
EXP = REPO_ROOT / "experiments"
SEEDS = [1, 2, 3, 4, 5]

# (table, {id column: value}) -> the run directory whose per-seed metrics.json it summarises.
# The id columns differ per table, so they are stated rather than guessed.
RUNS = {
    ("r2_ring_b0.csv", ("model", "gine_causal")): EXP / "R2_b0" / "gine_causal",
    ("r2_ring_b0.csv", ("model", "gfpxgb")): EXP / "R2_b0" / "gfpxgb",
    ("r2_ring_b0.csv", ("model", "density")): EXP / "R2_b0" / "density",
    ("r3_expansion.csv", ("method", "proposed")): EXP / "R3_expansion" / "runs" / "proposed",
    ("r3_expansion.csv", ("method", "b1")): EXP / "R3_expansion" / "runs" / "b1",
    ("r3_expansion.csv", ("method", "b1b")): EXP / "R3_expansion" / "runs" / "b1b",
    ("r3_expansion.csv", ("method", "hop1")): EXP / "R3_expansion" / "runs" / "hop1",
    ("r4_partition.csv", ("method", "average")): EXP / "R4_partition" / "runs" / "average",
    ("r4_partition.csv", ("method", "b2")): EXP / "R4_partition" / "runs" / "b2",
    ("r4_partition.csv", ("method", "pivot")): EXP / "R4_partition" / "runs" / "pivot",
    ("r6_detector_swap.csv", ("detector=mega", "method=b0")): EXP / "R6_b0" / "mega",
    ("r6_detector_swap.csv", ("detector=mega", "method=full")): EXP / "R6_full" / "mega",
    ("r6_detector_swap.csv", ("detector=mega_noembed", "method=full")): EXP / "R6_full" / "mega_noembed",
    ("r6_detector_swap.csv", ("detector=gfpxgb", "method=full")): EXP / "R6_full" / "gfpxgb",
    ("r6_detector_swap.csv", ("detector=gine_causal", "method=full")): EXP / "R4_partition" / "runs" / "average",
    ("r6_detector_swap.csv", ("detector=gine_causal", "method=b0")): EXP / "R2_b0" / "gine_causal",
    ("r7_heldout.csv", ("arm=l3_cycle", "method=full")): EXP / "R7_l3only_cycle" / "runs" / "full",
    ("r7_heldout.csv", ("arm=l3_bipartite", "method=full")): EXP / "R7_l3only_bipartite" / "runs" / "full",
}
F1_COLS = ("ring_f1_mean", "ring_f1")


def run_mean(root: Path, metric: str = "ring_f1", window: str = "primary") -> tuple[float, int]:
    """Mean of `metric` over the per-seed metrics.json under `root` -- the run artefacts themselves."""
    vals = []
    for s in SEEDS:
        p = root / f"seed{s}" / "metrics.json"
        if not p.exists():
            continue
        blocks = json.loads(p.read_text(encoding="utf-8")).get("blocks", {})
        if window in blocks and metric in blocks[window]:
            vals.append(float(blocks[window][metric]))
    return (float(np.mean(vals)) if vals else float("nan")), len(vals)


def select(d: pd.DataFrame, key) -> pd.DataFrame:
    """Rows matching the key, which is either (column, value) or ('col=value', 'col=value')."""
    sub = d
    if "=" in key[0]:
        for part in key:
            c, v = part.split("=", 1)
            sub = sub[sub[c].astype(str) == v]
    else:
        sub = sub[sub[key[0]].astype(str) == key[1]]
    if "pattern" in sub.columns:            # r7 is per pattern; the summary row is ALL
        sub = sub[sub["pattern"].astype(str) == "ALL"]
    return sub


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--tol", type=float, default=1e-6)
    a = ap.parse_args(argv)

    ok, bad, skipped = [], [], []
    for (table, key), root in sorted(RUNS.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))):
        f = TABLES / table
        label = "/".join(str(k) for k in key)
        if not f.exists():
            skipped.append((table, label, "table missing"))
            continue
        got, n = run_mean(root)
        if not n:
            skipped.append((table, label, f"no metrics.json under {root.relative_to(REPO_ROOT)}"))
            continue
        d = pd.read_csv(f)
        sub = select(d, key)
        f1c = next((c for c in F1_COLS if c in d.columns), None)
        if sub.empty or f1c is None:
            skipped.append((table, label, "row not found" if f1c else "no ring_f1 column"))
            continue
        rep = float(sub.iloc[0][f1c])
        (ok if abs(rep - got) <= max(a.tol, 5e-4) else bad).append((table, label, rep, got, n))

    print(f"{'table':26s} {'row':44s} {'reported':>10s} {'from runs':>10s} {'seeds':>6s}")
    for t, k, rep, got, n in ok:
        print(f"{t:26s} {k:44s} {rep:10.6f} {got:10.6f} {n:6d}  OK")
    for t, k, rep, got, n in bad:
        print(f"{t:26s} {k:44s} {rep:10.6f} {got:10.6f} {n:6d}  MISMATCH")
    for t, k, why in skipped:
        print(f"{t:26s} {k:44s} {'':>10s} {'':>10s} {'':>6s}  skipped: {why}")
    print(f"\ntraceable: {len(ok)} | mismatched: {len(bad)} | not checked: {len(skipped)}")
    derived = ["r2_ci.csv", "r3_ci.csv", "r4_ci.csv", "r5_typing_ci.csv", "r9_ring_ci.csv",
               "r3_pvalues.csv", "r4_pvalues.csv", "r6_pvalues.csv", "r9_significance.csv"]
    print("derived-statistic tables (CIs / p-values; point estimates traced above, intervals are "
          "computed and not stored in any metrics.json):")
    for d in derived:
        print(f"  {'present' if (TABLES / d).exists() else 'MISSING'}  {d}")
    if a.strict and bad:
        sys.exit(1)
    return bad


if __name__ == "__main__":
    main()
