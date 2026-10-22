"""Ring ground truth (moved from models/ring_aggregator.py in Step 4; semantics unchanged).

    truth, patterns = load_ground_truth(gt_parquet, t_min, t_max, "test_visible")

Returns {ring_id: set of account ids} and {ring_id: pattern_type} for the rings in scope of
the window [t_min, t_max] (loader time basis), per docs/RING_GROUND_TRUTH_DEFINITION.md.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

POLICIES = ("test_visible", "strict", "majority", "start", "full_membership")


def load_ground_truth(path: Path, t_min: float, t_max: float, policy: str, *, verbose: bool = True):
    """Build {ring_id: member set} and {ring_id: pattern} for in-scope rings.

    A ring is in scope per D1 section 4. `policy` decides boundary rings:
        test_visible -- at least one transaction inside [t_min, t_max]; the
                        member set is the union of from_id/to_id over the
                        ring's transactions inside the window only (D1 default,
                        decided 2026-09-16)
        strict       -- every transaction inside [t_min, t_max]; full members
        majority     -- more than half its transactions inside; full members
        start        -- its earliest transaction inside; full members
        full_membership -- Step 14 item 4, SENSITIVITY ONLY, never the headline: the same in-scope
                        rule as test_visible (>= 1 transaction in the window) but the scored member
                        set is ALL of the ring's accounts across the dataset. It keeps long patterns
                        intact instead of letting the window fragment them, at the cost of scoring a
                        method against members it had no way to observe. The gap between the two
                        rows is the size of the convention's effect (docs/paper/evaluation_protocol.md).
    """
    gt = pd.read_parquet(path)
    for col in ("ring_id", "from_id", "to_id", "timestamp_int"):
        if col not in gt.columns:
            raise SystemExit(f"Ground truth is missing column '{col}'. "
                             f"Found: {list(gt.columns)}")

    inside = (gt["timestamp_int"] >= t_min) & (gt["timestamp_int"] <= t_max)
    gt = gt.assign(_in=inside)

    grp = gt.groupby("ring_id")
    frac = grp["_in"].mean()
    if policy in ("test_visible", "full_membership"):
        keep = frac[frac > 0].index
    elif policy == "strict":
        keep = frac[frac == 1.0].index
    elif policy == "majority":
        keep = frac[frac > 0.5].index
    elif policy == "start":
        starts = grp["timestamp_int"].min()
        keep = starts[(starts >= t_min) & (starts <= t_max)].index
    else:
        raise SystemExit(f"unknown scope policy: {policy}")

    sub = gt[gt["ring_id"].isin(keep)]
    if policy == "test_visible":
        sub = sub[sub["_in"]]  # scored members: only accounts seen in the window
    truth = {rid: set(g["from_id"]) | set(g["to_id"])
             for rid, g in sub.groupby("ring_id")}
    patterns = (sub.groupby("ring_id")["pattern_type"].first().to_dict()
                if "pattern_type" in sub.columns else {})

    if verbose:
        n_total = gt["ring_id"].nunique()
        n_partial = int(((frac > 0) & (frac < 1)).sum())
        print(f"  Ground truth: {n_total} rings total, {len(truth)} in scope "
              f"(policy={policy})")
        print(f"    Rings straddling the split boundary: {n_partial}")
        if truth:
            sizes = [len(v) for v in truth.values()]
            print(f"    In-scope ring sizes: min {min(sizes)}, "
                  f"median {int(np.median(sizes))}, max {max(sizes)}")
            n_tiny = sum(1 for s in sizes if s < 3)
            if n_tiny:
                print(f"    WARNING: {n_tiny} in-scope rings have <3 members and "
                      f"are undetectable under --min-size 3 (D1 section 6).")
    return truth, patterns


def split_window(split_parquet: Path) -> tuple[int, int]:
    """[t_min, t_max] of a split parquet in the loader basis (the scope window)."""
    ts = pd.read_parquet(split_parquet, columns=["Timestamp"])["Timestamp"]
    return int(ts.min()), int(ts.max())
