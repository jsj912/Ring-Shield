"""Step 3b-z: the GFP cycle features are trailing, and the eight counts still are.

    python -m pytest tests/test_gfp_causality.py -q -s          # ~2 min, one core
    python -m pytest tests/test_gfp_causality.py -q -s -k counts

Full data (data/processed/amlworld_edges_*.parquet); skipped when it is not on disk.

test_cycle_features_trailing   for 10,000 random edges per split (seed from configs/seeds.yaml),
                               the production `_closes_cycle` on the full train+val+test adjacency
                               equals the same function on the adjacency cut at timestamp < t_e:
                               0 differences on both temporal_cycle and cycle_length.
test_cycle_features_match_reference
                               on 2,000 random edges per split, `_closes_cycle` equals an
                               independent brute-force FORWARD temporal search (dst -> ... -> src,
                               strictly increasing timestamps, all < t_e and >= t_e - lookback,
                               <= max hops; shortest length) written without the production
                               adjacency helpers.
test_eight_counts_trailing     regression for Step 3b-y: the eight count features are unchanged
                               on the cut graph (`tests/audit_feature_causality.py` machinery,
                               2,000 random test edges).
"""
from __future__ import annotations

import sys
from bisect import bisect_left
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import graph.motif_features as mf  # noqa: E402
from tests.audit_feature_causality import (FEATURES, MAX_HOPS, WINDOW_S, Truncated,  # noqa: E402
                                           build_adjacency_fast, features_for)

DATA = REPO_ROOT / "data" / "processed"
LOOKBACK_S = mf.LOOKBACK_DAYS_DEFAULT * 86400
SPLITS = ("train", "val", "test")
N_CAUSAL, N_REF, N_COUNTS = 10_000, 2_000, 2_000


@pytest.fixture(scope="module")
def graph():
    paths = [DATA / f"amlworld_edges_{s}.parquet" for s in SPLITS]
    if not all(p.exists() for p in paths):
        pytest.skip("processed edge parquets not on disk")
    e = pd.concat([pd.read_parquet(p, columns=["from_id", "to_id", "Timestamp"]) for p in paths], ignore_index=True)
    src, dst, ts = (e[c].to_numpy(np.int64) for c in ("from_id", "to_id", "Timestamp"))
    adj = build_adjacency_fast(src, dst, ts)
    return adj, src, dst, ts


@pytest.fixture(scope="module")
def seed():
    return int(yaml.safe_load((REPO_ROOT / "configs" / "seeds.yaml").read_text())["seeds"][0])


def _set_full(adj):
    mf._ADJ_OUT, mf._ADJ_IN, mf._ADJ_OUT_TS, mf._ADJ_IN_TS = adj
    mf._WINDOW, mf._MAX_HOPS, mf._LOOKBACK = WINDOW_S, MAX_HOPS, LOOKBACK_S


def _set_cut(adj, t_cut):
    adj_out, adj_in, adj_out_ts, adj_in_ts = adj
    mf._ADJ_OUT = Truncated(adj_out, adj_out_ts, t_cut, arrays=False)
    mf._ADJ_IN = Truncated(adj_in, adj_in_ts, t_cut, arrays=False)
    mf._ADJ_OUT_TS = Truncated(adj_out, adj_out_ts, t_cut, arrays=True)
    mf._ADJ_IN_TS = Truncated(adj_in, adj_in_ts, t_cut, arrays=True)
    mf._WINDOW, mf._MAX_HOPS, mf._LOOKBACK = WINDOW_S, MAX_HOPS, LOOKBACK_S


def _sample(split, n, seed):
    d = pd.read_parquet(DATA / f"amlworld_{split}.parquet", columns=["from_id", "to_id", "Timestamp"])
    rng = np.random.default_rng(seed)
    return d.iloc[np.sort(rng.choice(len(d), size=min(n, len(d)), replace=False))].reset_index(drop=True)


def test_cycle_features_trailing(graph, seed):
    adj = graph[0]
    for split in SPLITS:
        sm = _sample(split, N_CAUSAL, seed)
        full, cut = [], []
        for r in sm.itertuples(index=False):
            u, v, t = int(r.from_id), int(r.to_id), int(r.Timestamp)
            _set_full(adj)
            full.append(mf._closes_cycle(u, v, t))
            _set_cut(adj, t - 1)                      # graph restricted to timestamp < t_e
            cut.append(mf._closes_cycle(u, v, t))
        full, cut = np.array(full), np.array(cut)
        n_diff = int((full != cut).any(axis=1).sum())
        print(f"\n[{split}] {len(sm):,} edges: closes_cycle rate {full[:, 0].mean() * 100:.2f}%, "
              f"differences full vs cut(< t_e): {n_diff}")
        assert n_diff == 0, f"{split}: {n_diff} edges change on the cut graph"


class _ForwardCSR:
    """Out-edges of every node sorted by time, as flat numpy arrays (independent of the
    production adjacency dicts): node n's edges are rows start[n]:start[n+1]."""

    def __init__(self, src, dst, ts):
        order = np.lexsort((ts, src))
        self.src, self.dst, self.ts = src[order], dst[order], ts[order]
        n = int(max(src.max(), dst.max())) + 2
        self.start = np.searchsorted(self.src, np.arange(n))

    def out_edges(self, node, t_lo, t_hi):
        """(ts, dst) of node's out-edges with t_lo <= ts < t_hi, in time order."""
        a, b = self.start[node], self.start[node + 1]
        seg = self.ts[a:b]
        i, j = a + np.searchsorted(seg, t_lo, "left"), a + np.searchsorted(seg, t_hi, "left")
        return self.ts[i:j], self.dst[i:j]


def _reference_closes_cycle(u, v, t, csr: _ForwardCSR, max_hops, lookback_s):
    """Forward temporal BFS: path v -> ... -> u over edges with t - lookback <= ts < t, strictly
    increasing timestamps, <= max_hops edges; (flag, shortest length). Per level it keeps, for
    each reached node, the EARLIEST arrival time (the most permissive continuation), and
    re-expands a node only when reached earlier than before."""
    earliest = {v: -1}
    frontier = {v: -1}
    for hops in range(1, max_hops + 1):
        nxt = {}
        for node, last in frontier.items():
            tss, ws = csr.out_edges(node, max(t - lookback_s, last + 1), t)
            for tt, w in zip(tss.tolist(), ws.tolist()):
                if w == u:
                    return 1, hops
                if hops < max_hops and tt < earliest.get(w, np.inf):
                    earliest[w] = tt
                    nxt[w] = tt
        if not nxt:
            break
        frontier = nxt
    return 0, 0


def test_cycle_features_match_reference(graph, seed):
    adj, src, dst, ts = graph
    _set_full(adj)
    csr = _ForwardCSR(src, dst, ts)
    for split in SPLITS:
        sm = _sample(split, N_REF, seed + 1)
        n_bad, n_cyc = 0, 0
        for r in sm.itertuples(index=False):
            u, v, t = int(r.from_id), int(r.to_id), int(r.Timestamp)
            got = mf._closes_cycle(u, v, t)
            want = _reference_closes_cycle(u, v, t, csr, MAX_HOPS, LOOKBACK_S)
            n_cyc += want[0]
            if got != want:
                n_bad += 1
                if n_bad <= 3:
                    print(f"\n  mismatch {split} ({u}->{v} @ {t}): production {got}, reference {want}")
        print(f"\n[{split}] {len(sm):,} edges vs brute-force reference: {n_cyc} cycles, {n_bad} mismatches")
        assert n_bad == 0


def test_eight_counts_trailing(graph, seed):
    """Step 3b-y regression: fan/degree/scatter-gather never change on the graph cut at <= t_e."""
    adj = graph[0]
    sm = _sample("test", N_COUNTS, seed)
    counts = [i for i, f in enumerate(FEATURES) if f not in ("temporal_cycle", "cycle_length")]
    n_diff = 0
    for r in sm.itertuples(index=False):
        u, v, t = int(r.from_id), int(r.to_id), int(r.Timestamp)
        _set_full(adj)
        a = features_for(u, v, t)
        _set_cut(adj, t)
        b = features_for(u, v, t)
        n_diff += int((a[counts] != b[counts]).any())
    print(f"\n[counts] {len(sm):,} test edges: {n_diff} edges with any of the 8 counts changed on the cut graph")
    assert n_diff == 0
