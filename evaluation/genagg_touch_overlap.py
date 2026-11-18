"""Per-seed overlap of truth rings touched by seeds: MEGA-GenAgg vs shipped Multi-GINe (fixed 0.1 %).

    .venv312/Scripts/python.exe evaluation/genagg_touch_overlap.py --out results/tables/r6_genagg_touch_overlap.csv

"Touched" uses exactly r6_detector_swap.seed_distribution: the top 0.1 % of SELECT_COL (seed_mask_for_pct) on
the test split, restricted to the primary window, counted on in-scope (test_visible) truth rings. Descriptive.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

DET = {"megagenagg": (REPO_ROOT / "experiments" / "R6_megagenagg", "mega"),
       "gine_causal": (REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal", "gine_causal")}


def touched(se, ring_id_of, truth, W, k_pct=0.1) -> set:
    mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct)
    ids = se.loc[mask, "edge_id"].to_numpy()
    ids = ids[W.mask(se.loc[mask, "timestamp"].to_numpy())]
    rid = ring_id_of.reindex(ids).fillna(-1).astype(int).to_numpy()
    return {int(r) for r in rid if r > 0 and int(r) in truth}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows = []
    for s in a.seeds:
        T = {}
        for d, (sd, mid) in DET.items():
            se = build_scored_edges(sd / f"scores_test_seed{s}.parquet", "test", model_id=mid, seed=s, processed_dir=pdir)
            T[d] = touched(se, ring_id_of, truth, W)
        g, n = T["megagenagg"], T["gine_causal"]
        rows.append({"seed": s, "genagg_touched": len(g), "gine_touched": len(n), "both": len(g & n),
                     "genagg_only": len(g - n), "gine_only": len(n - g), "either": len(g | n),
                     "jaccard": len(g & n) / len(g | n) if g | n else np.nan})
        print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    mean = df.drop(columns="seed").mean().to_dict()
    df = pd.concat([df, pd.DataFrame([{"seed": "mean", **mean}])], ignore_index=True)
    df.to_csv(a.out, index=False)
    print(df.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
