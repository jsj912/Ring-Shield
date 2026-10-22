"""`max_gap_hours` really splits a component now (Step 7 close, item 4).

    python -m pytest tests/test_cc_gap.py -q

`ringshield.aggregators.cc._split_by_time` was a no-op from E7 until Step 7 (it added every
account-graph edge to its re-clustering graph before applying the time test). It now delegates to
`cc.time_window_labels`, the same routine the `full` aggregator's B3 baseline uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.aggregators.cc import _split_by_time, aggregate_cc, seed_graph, time_window_labels  # noqa: E402

H = 3600
DAY = 24 * H


def two_burst_frame() -> pd.DataFrame:
    """A -> B -> C -> D on day 0 and E -> F -> G -> D five days later; D is the shared account."""
    rows = []
    eid = 100
    for base, chain in ((0, [1, 2, 3, 9]), (5 * DAY, [5, 6, 7, 9])):
        for k in range(3):
            rows.append((eid, chain[k], chain[k + 1], 1, 1, base + 10 * H + 2 * H * k, 1000.0, 1000.0))
            eid += 1
    df = pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp", "amount_sent", "amount_received"])
    for c in ("currency_sent", "currency_received", "payment_format"):
        df[c] = 0
    df["score_raw"] = 0.9
    df["score_calibrated"] = df["score_raw"]
    return df


def test_time_window_labels_splits_two_bursts():
    df = two_burst_frame()
    comp = np.zeros(len(df), dtype=np.int64)
    lab = time_window_labels(df["from_id"].to_numpy(), df["to_id"].to_numpy(), df["timestamp"].to_numpy(), comp, 24 * H)
    assert len(np.unique(lab)) == 2 and (lab[:3] == lab[0]).all() and (lab[3:] == lab[3]).all() and lab[0] != lab[3]
    lab = time_window_labels(df["from_id"].to_numpy(), df["to_id"].to_numpy(), df["timestamp"].to_numpy(), comp, 10 * DAY)
    assert len(np.unique(lab)) == 1                      # one group when the gap covers both bursts


def test_split_by_time_partitions_the_component():
    df = two_burst_frame()
    G = seed_graph(df, np.ones(len(df), bool), "score_raw")
    comps = [set(G.nodes)]
    assert len(comps[0]) == 7
    groups = _split_by_time(G, comps, 24 * H)
    assert len(groups) == 2
    sizes = sorted(len(g) for g in groups)
    assert sizes == [3, 4]                               # the shared account D goes with the burst holding most of its edges
    assert sum(len(g) for g in groups) == 7 and len(set().union(*groups)) == 7   # a partition
    assert len(_split_by_time(G, comps, 10 * DAY)) == 1


def test_aggregate_cc_max_gap_hours_now_splits():
    df = two_burst_frame()
    kw = dict(seed_frac_pct=100.0, min_size=3, threshold=0.5)      # every edge a seed (the quantile cut is strict)
    one = aggregate_cc(df, max_gap_hours=None, **kw)
    assert len(one) == 1 and one[0].n_members == 7
    two = aggregate_cc(df, max_gap_hours=24, **kw)
    assert len(two) == 2 and sorted(r.n_members for r in two) == [3, 4]
    assert all(r.seed_edges for r in two) and set().union(*[set(r.members) for r in two]) == set(one[0].members)
    # and a gap wider than the bursts leaves the component alone
    assert len(aggregate_cc(df, max_gap_hours=10 * 24, **kw)) == 1
