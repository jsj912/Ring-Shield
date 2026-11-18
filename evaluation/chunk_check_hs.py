"""Addendum 6 check: HI-Small GenAgg seed 1 test scored in day blocks vs the stored single-pass batch-2048 file.

    .venv312/Scripts/python.exe evaluation/chunk_check_hs.py --blocks-root experiments/R18_hm_transfer/hs_blocks

Concatenates the block files, asserts they cover the test split exactly once, adds score_calibrated with the stored
seed-1 calibrator (experiments/R6_megagenagg/calibrator_seed1.pkl, as the stored file), writes
<root>/scores_test_seed1.parquet and prints |diff| shares, Spearman and top-0.1 % seed overlap. B0 ring-F1 is run
separately (ringshield.run_rings) on that file. Writes results/tables/chunk_check_hs_genagg_s1.json.
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))
from ringshield.aggregators.cc import seed_mask_for_pct  # noqa: E402


def concat_blocks(root: Path, seed: int, processed_dir: Path) -> pd.DataFrame:
    parts = sorted(p for p in root.glob(f"d*/scores_test_seed{seed}.parquet"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    ids = pd.read_parquet(processed_dir / "amlworld_test.parquet", columns=["EdgeID"])["EdgeID"]
    assert df["edge_id"].is_unique, "an edge was scored in two blocks"
    assert len(df) == len(ids) and set(df["edge_id"]) == set(ids), f"{len(df)} rows vs {len(ids)} test edges"
    print(f"[concat] {len(parts)} blocks -> {len(df):,} rows = test split, ids unique, none missing")
    return df.sort_values("edge_id").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blocks-root", type=Path, required=True)
    a = ap.parse_args()
    from preprocessing.account_bank import load_paths
    df = concat_blocks(a.blocks_root, 1, load_paths()["processed_dir"])
    cal = pickle.load(open(R / "experiments/R6_megagenagg/calibrator_seed1.pkl", "rb"))["model"]
    df["score_calibrated"] = cal.predict(df["score_raw"].to_numpy())
    df.to_parquet(a.blocks_root / "scores_test_seed1.parquet", index=False)
    st = pd.read_parquet(R / "experiments/R6_megagenagg/scores_test_seed1.parquet").sort_values("edge_id").reset_index(drop=True)
    assert st["edge_id"].equals(df["edge_id"])
    x, y = df["score_raw"].to_numpy(float), st["score_raw"].to_numpy(float)
    d = np.abs(x - y)
    mx, my = seed_mask_for_pct(x, 0.1), seed_mask_for_pct(y, 0.1)
    inter, union = int((mx & my).sum()), int((mx | my).sum())
    out = {"n": len(d), "share_gt_1e-4": float((d > 1e-4).mean()), "n_gt_1e-4": int((d > 1e-4).sum()),
           "diff_max": float(d.max()), "diff_p50": float(np.median(d)), "spearman": float(spearmanr(x, y).statistic),
           "top01_blocks": int(mx.sum()), "top01_stored": int(my.sum()), "top01_both": inter,
           "top01_jaccard": inter / union}
    print(json.dumps(out, indent=1))
    (R / "results/tables/chunk_check_hs_genagg_s1.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
