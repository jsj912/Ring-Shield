"""Part B2 test read, once, for the gate-selected cell (PREREG_RECOVERY amendment, addenda 3-4).

    .venv312/Scripts/python.exe evaluation/b2_test_read.py --cell r25_both [--suffix _testhist05] --out <csv>

Primary: paired unit bootstrap (evaluation/precision_paired.py unchanged), 10,000 draws, rng seed 20261117,
ring-F1, cell full arm vs shipped GINe full (../RS-e2e/experiments/R4_partition/runs/average), five seeds.
Descriptive per seed and mean: ring precision, recall, F1, rings touched by a prediction, added-member precision
(read from each run's metrics.json, test, primary window). Q0 buckets come from evaluation/q0_loss_decomposition.py
run separately with --runs/--scores pointed at the cell.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
import evaluation.precision_paired as pp  # noqa: E402

REF = R.parent / "RS-e2e" / "experiments"


def describe(run_dir: Path, label: str):
    rows = []
    for s in range(1, 6):
        m = json.load(open(run_dir / f"seed{s}" / "metrics.json"))
        t = m["test"]
        ex = t.get("expansion", {})
        rows.append({"arm": label, "seed": s, "ring_precision": t["ring_precision"], "ring_recall": t["ring_recall"],
                     "ring_f1": t["ring_f1"], "n_predicted": t["n_predicted"], "n_matched": t["n_matched"],
                     "expanded_edges": ex.get("n_expanded_edges_in_window"),
                     "added_member_precision": ex.get("expanded_member_precision"),
                     "val_ring_f1": m["chosen"]["val_ring_f1"]})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cell", required=True)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--paired", action="store_true", help="also run the primary paired bootstrap")
    a = ap.parse_args()
    cell_full = R / "experiments" / "R17_history_seeds" / f"{a.cell}{a.suffix}" / "full"
    ship = REF / "R4_partition" / "runs" / "average"
    d = pd.DataFrame(describe(cell_full, f"{a.cell}{a.suffix}_full") + describe(ship, "gine_full_shipped"))
    mean = d.groupby("arm").mean(numeric_only=True).reset_index().assign(seed="mean")
    d = pd.concat([d, mean])
    d.to_csv(a.out, index=False)
    print(d.to_string(index=False))
    if a.paired:
        pp.RUNS = {"cell_full": str(cell_full), "gine_full": str(ship)}
        pp.FAMILY = [(f"{a.cell}{a.suffix}_full_vs_gine_full", "cell_full", "gine_full")]
        pp.main(["--exp-root", str(REF), "--n-boot", "10000", "--rng-seed", "20261117",
                 "--out", str(a.out.with_name(a.out.stem + "_paired.csv"))])


if __name__ == "__main__":
    main()
