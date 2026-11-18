"""GenAgg paired family (addendum paper/PREREG_GENAGG_ADDENDUM_2026-11-16.md). Exploratory.

    .venv312/Scripts/python.exe evaluation/genagg_paired.py --out results/tables/r6_genagg_paired.csv

Reuses evaluation/precision_paired.py unchanged (paired unit bootstrap: truth rings plus off-ring account
clusters, resampled with replacement, both arms on the same draw; seeds averaged for ring-F1; Holm over
the four comparisons, per metric). Only the run set and the family differ. Fixed budget (0.1 %),
scoring batch 2048, primary window, test_visible, Jaccard 0.5.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import evaluation.precision_paired as pp  # noqa: E402

E = REPO_ROOT / "experiments"
REF = REPO_ROOT.parent / "RS-e2e" / "experiments"   # shipped GINe runs and scores
RUNS = {
    "genagg_full": E / "R6_full_sb2048_k010" / "megagenagg",
    "genagg_b0": E / "R6_b0_sb2048_k010" / "megagenagg",
    "genagg_noembed_full": E / "R6_full_sb2048_k010" / "megagenagg_noembed",
    "gine_full": REF / "R4_partition" / "runs" / "average",
    "gine_b0": REF / "R2_b0" / "gine_causal",
    "megagin_full": E / "R6_full_sb2048_k010" / "mega",
}
FAMILY = [
    ("i_genagg_full_vs_gine_full", "genagg_full", "gine_full"),
    ("ii_genagg_full_vs_megagin_full", "genagg_full", "megagin_full"),
    ("iii_genagg_b0_vs_gine_b0", "genagg_b0", "gine_b0"),
    ("iv_genagg_full_vs_genagg_noembed_full", "genagg_full", "genagg_noembed_full"),
]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--exp-root" not in argv:
        argv += ["--exp-root", str(REF)]          # scored-edge frame built from shipped GINe seed 1, as in pp
    pp.RUNS, pp.FAMILY = {k: str(v) for k, v in RUNS.items()}, FAMILY
    pp.main(argv)


if __name__ == "__main__":
    main()
