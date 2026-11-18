"""PROVISIONAL GenAgg detector-swap ring rows, seeds 1-4 (seed 5 still training). Not for the paper or FINDINGS.

    python evaluation/genagg_provisional_4seed.py --out results/tables/r6_genagg_provisional_4seed.csv
    python evaluation/genagg_provisional_4seed.py --ring-suffix "" --out results/tables/r6_genagg_provisional_4seed_valpicked.csv

Runs `evaluation/r6_detector_swap.py` unchanged, once per seed (1, 2, 3, 4) and once on seeds 1-4 together
("mean" rows), for: GINe (shipped inputs from --ref-root), MEGA-GIN and MEGA-GIN no-embedding (batch-2048
scores, R6_*_sb2048<suffix>), MEGA-GenAgg and its no-embedding arm (experiments/R6_megagenagg scores,
R6_*_sb2048<suffix>/megagenagg{,_noembed}). Same window/scope defaults as r6_detector_swap_sb2048
(primary, test_visible). --ring-suffix _k010 = budget fixed at 0.1 % (default); "" = validation-picked
(sensitivity only). The paired-test output of r6_detector_swap is written to a scratch file and NOT reported:
paired tests wait for five seeds.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
import evaluation.r6_detector_swap as r6  # noqa: E402

KEEP = ["detector", "method", "n_seeds", "edge_f1", "rings_touched_by_seeds", "matched_rings", "ring_precision",
        "ring_recall", "ring_f1", "ring_f1_lo", "ring_f1_hi", "added_member_precision", "quiet_member_recall"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ring-suffix", default="_k010")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    ap.add_argument("--ref-root", type=Path, default=REPO_ROOT.parent / "RS-e2e" / "experiments")
    ap.add_argument("--genagg-tag", default="megagenagg",
                    help="GenAgg run-directory name under R6_{b0,full}_sb2048<suffix>/ (megagenagg_v2 = open item 21 fix)")
    ap.add_argument("--genagg-scores", default="R6_megagenagg", help="GenAgg score directory under experiments/")
    ap.add_argument("--status", default="PROVISIONAL seeds 1-4; not in paper/FINDINGS; no paired tests")
    ap.add_argument("--labels-dir", type=Path, default=Path("E:/JSJ/Ring-Shield/contract/out"))
    a = ap.parse_args(argv)
    assert "provisional" in a.out.name or sorted(a.seeds) == [1, 2, 3, 4, 5], \
        "output name must say provisional unless all five seeds are scored"
    R, E, suf = a.ref_root, REPO_ROOT / "experiments", a.ring_suffix
    D = r6.DETECTORS
    D["gine_causal"].update(scores=R / "R1_gine_causal",
                            runs={"b0": R / "R2_b0" / "gine_causal", "full": R / "R4_partition" / "runs" / "average"})
    D["mega"].update(scores=E / "R6_mega_sb2048",
                     runs={"b0": E / f"R6_b0_sb2048{suf}" / "mega", "full": E / f"R6_full_sb2048{suf}" / "mega"})
    D["mega_noembed"].update(scores=E / "R6_mega_sb2048", runs={"full": E / f"R6_full_sb2048{suf}" / "mega_noembed"})
    G, GS = a.genagg_tag, E / a.genagg_scores
    D["megagenagg"] = {**D["mega"], "scores": GS,
                       "runs": {"b0": E / f"R6_b0_sb2048{suf}" / G, "full": E / f"R6_full_sb2048{suf}" / G}}
    D["megagenagg_noembed"] = {**D["mega_noembed"], "scores": GS,
                               "runs": {"full": E / f"R6_full_sb2048{suf}" / f"{G}_noembed"}}
    dets = ["gine_causal", "mega", "mega_noembed", "megagenagg", "megagenagg_noembed"]
    frames = []
    with tempfile.TemporaryDirectory() as td:
        for label, seeds in [*((str(s), [s]) for s in a.seeds), ("mean", a.seeds)]:
            tmp, pv = Path(td) / f"r6_{label}.csv", Path(td) / f"p_{label}.csv"
            r6.main(["--detectors", *dets, "--seeds", *map(str, seeds), "--out", str(tmp), "--pvalues-out", str(pv),
                     "--labels-dir", str(a.labels_dir), "--n-perm", "200"])
            df = pd.read_csv(tmp)
            frames.append(df[[c for c in KEEP if c in df.columns]].assign(seed=label))
    out = pd.concat(frames, ignore_index=True)
    out.insert(0, "status", a.status)
    out["budget"] = "fixed 0.1 %" if suf == "_k010" else "validation-picked (sensitivity)"
    out.to_csv(a.out, index=False)
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
