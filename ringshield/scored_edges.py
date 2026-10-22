"""Build the scored_edges contract frame for a split from a models/score.py scores parquet.

    se = build_scored_edges(scores_parquet, split="test", model_id="gine", seed=1)

Columns follow contract/schema.py::SCORED_EDGES_COLUMNS (edge attributes from
data/processed/amlworld_<split>.parquet, banks included since Step 3a; score_calibrated ==
score_raw until calibration exists; is_seed left False -- the aggregator decides seeds).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from contract.make_scored_edges import load_paths
from contract.schema import SCORED_EDGES_ORDER, TEST_PARQUET_RENAMES

SPLIT_COLUMNS = ["EdgeID", "from_id", "to_id", "from_bank", "to_bank", "Timestamp", "Amount Sent",
                 "Amount Received", "Sent Currency", "Received Currency", "Payment Format"]


def build_scored_edges(scores_parquet: Path, split: str, model_id: str = "unknown", seed: int = 0,
                       processed_dir: Path | None = None, keep_unscored: bool = True) -> pd.DataFrame:
    processed_dir = Path(processed_dir) if processed_dir else load_paths()["processed_dir"]
    base = pd.read_parquet(processed_dir / f"amlworld_{split}.parquet", columns=SPLIT_COLUMNS)
    base = base.rename(columns=TEST_PARQUET_RENAMES)
    sc = pd.read_parquet(scores_parquet)
    assert {"edge_id", "score_raw"} <= set(sc.columns), sc.columns.tolist()
    if "timestamp" in sc.columns:
        chk = base[["edge_id", "timestamp"]].merge(sc[["edge_id", "timestamp"]], on="edge_id", suffixes=("", "_s"))
        assert (chk["timestamp"] == chk["timestamp_s"]).all(), "scores parquet timestamps differ from the split parquet"
    se = base.merge(sc[["edge_id", "score_raw"] + (["score_calibrated"] if "score_calibrated" in sc.columns else [])],
                    on="edge_id", how="left" if keep_unscored else "inner", validate="one_to_one")
    if "score_calibrated" not in se.columns:
        se["score_calibrated"] = se["score_raw"]
    se["tenant_id"] = se["from_bank"].astype(np.int64)
    se["is_seed"] = False
    se["model_id"] = model_id
    se["seed"] = np.int64(seed)
    se = se[SCORED_EDGES_ORDER]
    for c in ("edge_id", "tenant_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp",
              "currency_sent", "currency_received", "payment_format"):
        se[c] = se[c].astype(np.int64)
    return se.sort_values("edge_id").reset_index(drop=True)
