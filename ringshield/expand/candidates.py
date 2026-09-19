"""Candidate edges around an included set (Step 6.1).

    cand = candidates(scored_edges, included_edge_ids, delta_t_h=72, max_hops=2)

One row per candidate edge (the closest way it was reached), columns

    candidate_edge_id   an edge of the split that is not in the included set
    anchor_edge_id      the included edge the chain starts from
    shared_account      the account the candidate shares with the anchor (hop 1) or with the
                        hop-1 candidate it touches (hop 2)
    hop                 1 or 2
    gap_s               candidate timestamp - anchor timestamp (signed)
    via_edge_id         hop 2: the hop-1 candidate whose far endpoint the candidate touches (-1 at hop 1)
    gap_via_s           hop 2: candidate timestamp - via timestamp (= gap_s at hop 1)
    n_anchors           number of distinct included edges reaching the candidate at hop 1 (0 at hop 2)

Hop 1: the candidate shares an endpoint with an included edge and its timestamp is within
delta_t of that anchor. Hop 2: the candidate touches a hop-1 candidate's far endpoint (the
endpoint not shared with the anchor) within delta_t of that hop-1 candidate. A candidate reached
several ways keeps the row with the smallest hop, then the smallest |gap| to what it touches.
Every candidate lies in [min included timestamp - delta_t, max included timestamp + delta_t]
(the 6.4 window rule, enforced here so training rows and inference see the same set).

Queries run on the split's SplitIndex (ringshield/expand/index.py, built once per split).
`max_events_per_query` (default MAX_EVENTS_PER_QUERY = 500, part of the candidate definition
since 6.4) takes at most that many events at an account, the ones nearest in time to the query;
the count of truncated queries is in `cand.attrs["n_truncated"]`. Without it AMLworld's
mega-accounts (135: 101,913 transactions; 98992: 62,275) turn hop 2 into ~80 k rows per ring.
`time_bounds=(lo, hi)` fixes the window instead of deriving it from the included set (the
greedy expansion keeps the SEED window while the included set grows).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ringshield.expand.index import SplitIndex, index_for

MAX_EVENTS_PER_QUERY = 500
COLUMNS = ["candidate_edge_id", "anchor_edge_id", "shared_account", "hop", "gap_s", "via_edge_id", "gap_via_s", "n_anchors"]


def _empty() -> pd.DataFrame:
    df = pd.DataFrame({c: pd.Series(dtype=np.int64) for c in COLUMNS})
    df.attrs["n_truncated"] = 0
    return df


def _truncate(idx: SplitIndex, lo, hi, t_query, cap):
    """Keep at most `cap` events per range, the ones nearest t_query."""
    n = hi - lo
    big = n > cap
    if not big.any():
        return lo, hi, 0
    lo, hi = lo.copy(), hi.copy()
    acc_base = idx.ev_key[lo[big]] - (idx.ev_key[lo[big]] % (np.int64(1) << np.int64(32)))
    p = np.searchsorted(idx.ev_key, acc_base + np.asarray(t_query)[big], side="left")
    half = cap // 2
    new_lo = np.clip(p - half, lo[big], hi[big] - cap)
    lo[big], hi[big] = new_lo, new_lo + cap
    return lo, hi, int(big.sum())


def _dedupe(cand_pos, anchor_pos, shared, gap, via_pos, gap_via, prefer_abs):
    """One row per candidate: smallest |prefer_abs|, then smallest anchor position."""
    order = np.lexsort((anchor_pos, np.abs(prefer_abs), cand_pos))
    cand_pos, anchor_pos, shared, gap, via_pos, gap_via = (a[order] for a in (cand_pos, anchor_pos, shared, gap, via_pos, gap_via))
    first = np.ones(len(cand_pos), dtype=bool)
    first[1:] = cand_pos[1:] != cand_pos[:-1]
    return cand_pos[first], anchor_pos[first], shared[first], gap[first], via_pos[first], gap_via[first]


def candidates(scored_edges: pd.DataFrame, included_edge_ids, delta_t_h: float, max_hops: int = 2, *,
               index: SplitIndex | None = None, max_events_per_query: int | None = MAX_EVENTS_PER_QUERY,
               time_bounds: tuple[int, int] | None = None) -> pd.DataFrame:
    assert max_hops in (1, 2), max_hops
    idx = index or index_for(scored_edges)
    inc = np.unique(np.asarray(list(included_edge_ids), dtype=np.int64))
    if len(inc) == 0:
        return _empty()
    inc_pos = idx.pos_of(inc)
    delta = int(round(float(delta_t_h) * 3600))
    t_inc = idx.ts[inc_pos]
    t_lo_g, t_hi_g = (int(t_inc.min()) - delta, int(t_inc.max()) + delta) if time_bounds is None else (int(time_bounds[0]), int(time_bounds[1]))
    inc_mask = np.zeros(idx.n_edges, dtype=bool)
    inc_mask[inc_pos] = True
    n_trunc = 0

    # ---- hop 1: both endpoints of every included edge, [t - delta, t + delta]
    q_acc = np.concatenate([idx.from_dense[inc_pos], idx.to_dense[inc_pos]])
    q_anchor = np.concatenate([inc_pos, inc_pos])
    q_t = np.concatenate([t_inc, t_inc])
    lo, hi = idx.window(q_acc, q_t - delta, q_t + delta)
    if max_events_per_query:
        lo, hi, k = _truncate(idx, lo, hi, q_t, max_events_per_query)
        n_trunc += k
    rows, ev = idx.expand(lo, hi)
    c1 = idx.ev_pos[ev]
    keep = ~inc_mask[c1]
    rows, c1 = rows[keep], c1[keep]
    a1, s1 = q_anchor[rows], q_acc[rows]
    g1 = idx.ts[c1] - idx.ts[a1]
    # distinct anchors per candidate (before dedupe)
    if len(c1):
        pairs = np.unique(c1.astype(np.int64) * (idx.n_edges + 1) + a1)
        n_anchor_of = pd.Series(pairs // (idx.n_edges + 1)).value_counts()
    else:
        n_anchor_of = pd.Series(dtype=np.int64)
    c1, a1, s1, g1, v1, gv1 = _dedupe(c1, a1, s1, g1, np.full(len(c1), -1), g1.copy(), g1)
    hop1_mask = np.zeros(idx.n_edges, dtype=bool)
    hop1_mask[c1] = True
    parts = [(c1, a1, s1, g1, v1, gv1, np.ones(len(c1), np.int64), n_anchor_of.reindex(c1).fillna(0).to_numpy(np.int64))]

    # ---- hop 2: the far endpoint of every hop-1 candidate, [t_c - delta, t_c + delta]
    if max_hops >= 2 and len(c1):
        far = np.where(idx.from_dense[c1] == s1, idx.to_dense[c1], idx.from_dense[c1])
        not_loop = far != s1
        c1n, a1n, farn = c1[not_loop], a1[not_loop], far[not_loop]
        t_via = idx.ts[c1n]
        lo, hi = idx.window(farn, t_via - delta, t_via + delta)
        if max_events_per_query:
            lo, hi, k = _truncate(idx, lo, hi, t_via, max_events_per_query)
            n_trunc += k
        rows, ev = idx.expand(lo, hi)
        c2 = idx.ev_pos[ev]
        keep = ~inc_mask[c2] & ~hop1_mask[c2]
        rows, c2 = rows[keep], c2[keep]
        via = c1n[rows]
        a2, s2 = a1n[rows], farn[rows]
        g2 = idx.ts[c2] - idx.ts[a2]
        gv2 = idx.ts[c2] - idx.ts[via]
        c2, a2, s2, g2, v2, gv2 = _dedupe(c2, a2, s2, g2, via, gv2, gv2)
        parts.append((c2, a2, s2, g2, v2, gv2, np.full(len(c2), 2, np.int64), np.zeros(len(c2), np.int64)))

    cand_pos = np.concatenate([p[0] for p in parts])
    df = pd.DataFrame({
        "candidate_edge_id": idx.edge_id[cand_pos],
        "anchor_edge_id": idx.edge_id[np.concatenate([p[1] for p in parts])],
        "shared_account": idx.acc_uniq[np.concatenate([p[2] for p in parts])],
        "hop": np.concatenate([p[6] for p in parts]),
        "gap_s": np.concatenate([p[3] for p in parts]),
        "via_edge_id": np.where(np.concatenate([p[4] for p in parts]) >= 0,
                                idx.edge_id[np.maximum(np.concatenate([p[4] for p in parts]), 0)], -1),
        "gap_via_s": np.concatenate([p[5] for p in parts]),
        "n_anchors": np.concatenate([p[7] for p in parts]),
    })
    t_c = idx.ts[cand_pos]
    df = df[(t_c >= t_lo_g) & (t_c <= t_hi_g)]
    df = df.sort_values(["hop", "candidate_edge_id"]).reset_index(drop=True)
    for c in COLUMNS:
        df[c] = df[c].astype(np.int64)
    assert df["candidate_edge_id"].is_unique
    df.attrs["n_truncated"] = n_trunc
    df.attrs["window"] = (t_lo_g, t_hi_g)
    return df
