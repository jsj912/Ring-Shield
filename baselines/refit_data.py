"""The refit feature set and its loader, importable without pulling Optuna.

`baselines/gfp_xgboost_aml.py` imports `optuna` at module scope (~2.6 s, and it is a tuning
dependency, not a data one), so anything that only wanted the loader paid for the tuner. The
loader and the three column lists live here instead; `gfp_xgboost_aml` re-exports them, so
`from baselines.gfp_xgboost_aml import load_split_for_refit` keeps working and returns the same
function object.

Nothing here reads a label to make a decision and nothing is configurable: the feature set is the
one E5b tuned on, and changing it would make the refit incomparable with the published numbers.

**`Sent Currency`, `Received Currency` and `Payment Format` enter as numeric codes** -- the frame
is handed to XGBoost as `float32`, with no one-hot and no categorical dtype. The codes are
arbitrary integers from `scripts/format_kaggle_files.py` (see `contract/currency_map.json` and
`contract/payment_format_map.json`), so a split on `Payment Format < 3.5` is a split on an
alphabetical accident, not on an ordering that means anything. That is a property of the shipped
baseline, recorded here rather than fixed, because fixing it would change the published model.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42

GFP_COLS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
            "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]
REFIT_TABULAR = ["Amount Sent", "Sent Currency", "Amount Received", "Received Currency", "Payment Format",
                 "hour_of_day", "day_of_week"]
REFIT_EXCLUDED = ["day_index", "from_bank", "to_bank"] + [f"{p}_{k}" for p in ("sender_out", "receiver_in")
                                                          for k in ("degree", "amount_mean", "amount_std", "amount_max",
                                                                    "volume_total")]


def load_split_for_refit(data_dir: Path, split: str):
    """Split parquet + trailing GFP parquet, joined 1:1 on EdgeID; asserts the re-keyed files."""
    import pyarrow.parquet as pq
    df = pd.read_parquet(data_dir / f"amlworld_{split}.parquet")
    gfp_path = data_dir / f"amlworld_gfp_features_{split}.parquet"
    gfp = pd.read_parquet(gfp_path)
    meta = pq.ParquetFile(gfp_path).schema_arrow.metadata or {}
    assert b"gfp" in meta and json.loads(meta[b"gfp"]).get("trailing"), \
        f"{gfp_path}: not the Step 3b-z trailing GFP parquet (no 'gfp' schema metadata)"
    assert gfp["EdgeID"].is_unique and set(gfp["EdgeID"]) == set(df["EdgeID"]), \
        f"{gfp_path}: EdgeID set differs from the split parquet (not re-keyed / edge_id aligned)"
    df = df.merge(gfp, on="EdgeID", how="inner", validate="one_to_one")
    assert len(df) == len(gfp) and not df[GFP_COLS].isna().any().any()
    feature_cols = REFIT_TABULAR + GFP_COLS
    return df, df[feature_cols].values.astype(np.float32), df["Is Laundering"].values.astype(np.int64), feature_cols
