"""What happens to the 174 truth rings, full pipeline, primary window, per detector at fixed 0.1 % (data only).

    .venv312/Scripts/python.exe evaluation/ring_decomposition_sb2048.py --out results/tables/r6_ring_decomposition_sb2048.csv

Uses evaluation.unmatched_rings.classify unchanged (the B11 decomposition the paper's figure quotes). Detectors:
shipped Multi-GINe (reproduction check against 80.2 / 48.6 / 33.2 / 5.2 / 6.8), MEGA-GIN at batch 8192 (check
against 83.6 / 51.6 / 24.0 / 8.2 / 6.6), MEGA-GIN and MEGA-GenAgg at batch 2048.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

E, REF = REPO_ROOT / "experiments", REPO_ROOT.parent / "RS-e2e" / "experiments"
DET = {"gine_causal": (REF / "R4_partition" / "runs" / "average", REF / "R1_gine_causal", "gine_causal"),
       "mega_sb8192": (REF / "R6_full" / "mega", REF / "R6_mega", "mega"),
       "mega_sb2048": (E / "R6_full_sb2048_k010" / "mega", E / "R6_mega_sb2048", "mega"),
       "megagenagg_sb2048": (E / "R6_full_sb2048_k010" / "megagenagg", E / "R6_megagenagg", "mega")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    rows = []
    for d, (runs, sd, mid) in DET.items():
        for s in a.seeds:
            rp = runs / f"seed{s}" / "rings.parquet"
            if not rp.exists():
                print(f"  [skip] {d} seed {s}"); continue
            se = build_scored_edges(sd / f"scores_test_seed{s}.parquet", "test", model_id=mid, seed=s, processed_dir=pdir)
            kl = classify(read_rings_any(rp), se, truth, patterns, W)
            vc = kl["klass"].value_counts().to_dict()
            rows.append({"detector": d, "seed": s, **vc}); print(rows[-1], flush=True)
    df = pd.DataFrame(rows).fillna(0)
    mean = df.groupby("detector").mean(numeric_only=True).drop(columns="seed").reset_index().assign(seed="mean")
    df = pd.concat([df, mean], ignore_index=True)
    df.to_csv(a.out, index=False)
    print(mean.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
