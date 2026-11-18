"""Seed-set Jaccard and touched-ring overlap against shipped Multi-GINe, per detector and seed (data only).

    .venv312/Scripts/python.exe evaluation/seed_overlap_sb2048.py --out results/tables/r6_seed_overlap_sb2048.csv

Seeds = top 0.1 % of SELECT_COL on the test split (seed_mask_for_pct, as the ring runs). Edge-set Jaccard is
reported on the whole test split and on the primary window; touched rings as in r6_detector_swap.seed_distribution
(primary window, test_visible). `mega_sb8192` (experiments/R6_mega, frozen scores) is included as a reproduction
check of the published C6/C7 numbers (seed Jaccard 0.415, rings reached 128.8, touched overlap 71.5 %).
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

E, REF = REPO_ROOT / "experiments", REPO_ROOT.parent / "RS-e2e" / "experiments"
DET = {"gine_causal": (REF / "R1_gine_causal", "gine_causal"),
       "mega_sb8192": (REF / "R6_mega", "mega"),
       "mega_sb2048": (E / "R6_mega_sb2048", "mega"),
       "megagenagg_sb2048": (E / "R6_megagenagg", "mega")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows = []
    for s in a.seeds:
        S, Sw, T = {}, {}, {}
        for d, (sd, mid) in DET.items():
            p = sd / f"scores_test_seed{s}.parquet"
            if not p.exists():
                print(f"  [skip] {d} seed {s}: {p} missing"); continue
            se = build_scored_edges(p, "test", model_id=mid, seed=s, processed_dir=pdir)
            m = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
            ids = se.loc[m, "edge_id"].to_numpy(); ts = se.loc[m, "timestamp"].to_numpy()
            S[d] = set(ids.tolist()); Sw[d] = set(ids[W.mask(ts)].tolist())
            rid = ring_id_of.reindex(list(Sw[d])).fillna(-1).astype(int).to_numpy()
            T[d] = {int(r) for r in rid if r > 0 and int(r) in truth}
        g = "gine_causal"
        for d in S:
            if d == g:
                continue
            j = lambda x, y: len(x & y) / len(x | y) if x | y else np.nan  # noqa: E731
            rows.append({"detector": d, "seed": s, "seed_jaccard_test": j(S[d], S[g]),
                         "seed_jaccard_primary": j(Sw[d], Sw[g]), "n_seeds": len(S[d]),
                         "rings_reached": len(T[d]), "gine_rings_reached": len(T[g]),
                         "touched_both": len(T[d] & T[g]), "touched_det_only": len(T[d] - T[g]),
                         "touched_gine_only": len(T[g] - T[d]), "touched_union": len(T[d] | T[g]),
                         "touched_overlap_share": j(T[d], T[g])})
            print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    df = pd.DataFrame(rows)
    mean = df.groupby("detector").mean(numeric_only=True).drop(columns="seed").reset_index().assign(seed="mean")
    df = pd.concat([df, mean], ignore_index=True)
    df.to_csv(a.out, index=False)
    print(mean.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
