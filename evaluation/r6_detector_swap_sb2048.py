"""Detector-swap table with every MEGA-family row from scoring batch 2048 (author decision 2026-11-15).

    python evaluation/r6_detector_swap_sb2048.py --out results/tables/r6_detector_swap_sb2048.csv \
        --pvalues-out results/tables/r6_pvalues_sb2048.csv

Runs `evaluation/r6_detector_swap.py` unchanged, with only the detector map redirected:
  mega / mega_noembed  scores experiments/R6_mega_sb2048 (shipped models rescored with --score-only at
                       batch 2048, calibrated on the 2048 val scores); ring runs re-chosen on val from
                       them in experiments/R6_b0_sb2048/mega and experiments/R6_full_sb2048/mega{,_noembed}
  gine_causal / gfpxgb the shipped inputs, read from --ref-root (default ../RS-e2e/experiments)
Then adds, for every shipped column, `<col>_shipped8192` from the shipped table (--shipped) beside it.
Refuses to write over the shipped table names.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import evaluation.r6_detector_swap as r6  # noqa: E402

FROZEN = {"r6_detector_swap.csv", "r6_pvalues.csv", "r6_detector_swap.json"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pvalues-out", type=Path, required=True)
    ap.add_argument("--ref-root", type=Path, default=REPO_ROOT.parent / "RS-e2e" / "experiments")
    ap.add_argument("--exp-root", type=Path, default=REPO_ROOT / "experiments")
    ap.add_argument("--shipped", type=Path, default=REPO_ROOT / "results" / "tables" / "r6_detector_swap.csv")
    ap.add_argument("--labels-dir", type=Path, default=Path("E:/JSJ/Ring-Shield/contract/out"))
    ap.add_argument("--ring-suffix", default="_k010",
                    help="ring runs under R6_b0_sb2048<suffix> / R6_full_sb2048<suffix> (default: B0 grid fixed at k = 0.1 %%)")
    a, rest = ap.parse_known_args(argv)
    for p in (a.out, a.pvalues_out):
        assert p.name not in FROZEN, f"refusing to overwrite the shipped table {p.name}"
    R, E = a.ref_root, a.exp_root
    D = r6.DETECTORS
    D["gine_causal"].update(scores=R / "R1_gine_causal",
                            runs={"b0": R / "R2_b0" / "gine_causal", "full": R / "R4_partition" / "runs" / "average"})
    D["gfpxgb"].update(scores=R / "R2_b0" / "gfpxgb_scores",
                       runs={"b0": R / "R2_b0" / "gfpxgb", "full": R / "R6_full" / "gfpxgb"})
    D["mega"].update(scores=E / "R6_mega_sb2048",
                     runs={"b0": E / f"R6_b0_sb2048{a.ring_suffix}" / "mega", "full": E / f"R6_full_sb2048{a.ring_suffix}" / "mega"})
    D["mega_noembed"].update(scores=E / "R6_mega_sb2048", runs={"full": E / f"R6_full_sb2048{a.ring_suffix}" / "mega_noembed"})
    for k in ("mega", "mega_noembed"):
        D[k]["sampling"] += "; scoring batch 2048 (score-only rescoring of the shipped models)"
    r6.main(["--out", str(a.out), "--pvalues-out", str(a.pvalues_out), "--labels-dir", str(a.labels_dir), *rest])

    new, old = pd.read_csv(a.out), pd.read_csv(a.shipped)
    keys = [c for c in ("detector", "method") if c in new.columns]
    num = [c for c in old.columns if c not in keys and pd.api.types.is_numeric_dtype(old[c])]
    merged = new.merge(old[keys + num].rename(columns={c: f"{c}_shipped8192" for c in num}), on=keys, how="left")
    merged.to_csv(a.out, index=False)
    print(f"-> {a.out} (shipped 8192 values beside, suffix _shipped8192)")


if __name__ == "__main__":
    main()
