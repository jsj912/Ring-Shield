"""Feature rows for ground-truth rings of a split (Step 8.2 / 8.3 training data).

    rows = truth_ring_rows("train", min_members=3)

One row per ground-truth ring visible in the split (the `test_visible` definition applied to it:
the ring's transactions inside the split, i.e. the split parquet's `ring_id` column), with
`ringshield.typing.features.ring_features` computed on its pattern lines and the account roles
from `ringshield.roles`. Rings with fewer than `min_members` visible accounts are dropped
(amendment d: the head trains on train-visible rings with >= 3 visible members).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from contract.make_scored_edges import load_paths
from ringshield.roles import (account_roles, flows_for, flows_of, load_roles_config, role_of,  # noqa: E402
                              role_records_from_flows)
from ringshield.typing.features import RING_FEATURES, ring_features

SPLIT_COLUMNS = ["EdgeID", "from_id", "to_id", "Timestamp", "Amount Received", "ring_id", "pattern_type"]


def split_rings(split: str, processed_dir: Path | None = None) -> pd.DataFrame:
    pdir = Path(processed_dir) if processed_dir else load_paths()["processed_dir"]
    df = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=SPLIT_COLUMNS)
    df = df[df["ring_id"] > 0].rename(columns={"EdgeID": "edge_id", "Timestamp": "timestamp", "Amount Received": "amount_received"})
    return df


def roles_for_edges(edges: pd.DataFrame, cfg: dict | None = None, *, currency: str = "raw") -> dict[int, dict]:
    """{account: role record} over `edges` directly, without needing a Ring.

    `currency` is the same switch as `account_roles`, and **defaults to `"raw"`**, which is
    byte-identical to the previous behaviour -- every typing-head feature and every truth-ring row
    published so far was computed with it, and the head's training set would move if the default
    changed. `"converted"` runs the corrected convention (sender's leg from amount_sent /
    currency_sent, both legs converted to currency 0 via contract/fx_rates.json); it is literally
    the same code path as `account_roles(..., currency="converted")`, because both call
    `flows_for` and `role_records_from_flows`.
    """
    cfg = cfg or load_roles_config()
    return role_records_from_flows(flows_for(edges, currency), cfg, currency)


def truth_ring_rows(split: str, *, min_members: int = 3, processed_dir: Path | None = None,
                    window_days: int | None = None) -> pd.DataFrame:
    """ring_id, pattern_type, n_visible_members + RING_FEATURES for every visible ring of the split.

    `window_days` slices the split into consecutive windows of that many days first and emits one
    row per (ring, window) -- the `test_visible` rule applied to the window, which is exactly what
    a ring looks like at inference time. It matters: a pattern seen through a 6-day split is a
    much larger fragment than the same pattern seen through the 2-day primary window, and a head
    trained on the former types the latter badly (docs/TYPING.md). `ring_id` keeps the ring's id so
    grouped CV still holds all windows of one ring in the same fold.
    """
    df = split_rings(split, processed_dir)
    cfg = load_roles_config()
    day = (df["timestamp"].to_numpy() - 10) // 86400
    if window_days:
        df = df.assign(_win=(day - day.min()) // int(window_days))
    else:
        df = df.assign(_win=0)
    rows = []
    for (rid, win), g in df.groupby(["ring_id", "_win"]):
        members = set(g["from_id"]) | set(g["to_id"])
        if len(members) < min_members:
            continue
        roles = roles_for_edges(g, cfg)
        f = ring_features(g, roles, seed_ratio=1.0)
        rows.append({"ring_id": int(rid), "pattern_type": str(g["pattern_type"].iloc[0]), "n_visible_members": len(members),
                     "window": int(win), **f})
    return pd.DataFrame(rows, columns=["ring_id", "pattern_type", "n_visible_members", "window"] + RING_FEATURES)
