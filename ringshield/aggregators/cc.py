"""B0 -- connected-components ring aggregation (moved from models/ring_aggregator.py, Step 4).

    rings = aggregate_cc(scored_edges, seed_frac_pct=0.5, min_size=3, max_gap_hours=None)

    score edges  ->  keep the top `seed_frac_pct` %  ->  connected components  ->  filter  ->  rings

`scored_edges` is a DataFrame with the contract columns (contract/schema.py::SCORED_EDGES_COLUMNS):
at least edge_id, from_id, to_id, from_bank, to_bank, timestamp and a score column
(`score_calibrated` if present, else `score_raw`; NaN scores are never seeds but their edges can
still be member_edges). The threshold is a percentile cut over the non-NaN scores -- per-seed
absolute thresholds are not comparable across models, a percentile is. The thresholded edges are
the ring's `seed_edges`; `member_edges` are every edge of the split with both endpoints in the
ring and timestamp in [start_time, end_time]; nothing is expanded (`expanded_edges = []`),
topology is UNKNOWN / uniform and roles are empty (Steps 6-8 fill them).

Semantics are exactly the legacy CLI's: parallel transactions between the same pair are one
graph edge (so `n_edges` counts distinct unordered pairs and `density = n_edges / (n (n-1))`),
`confidence` is the mean score over the thresholded transactions, and `max_gap_hours` re-clusters
each component through transactions no further apart than that (breaks chains through busy
shared accounts). A note on density (FR04.6 suggests min 0.4): a 5-node CYCLE has density 0.25
and a 1-to-5 FAN-OUT 0.167, so density is reported, not used as a filter, here.
"""
from __future__ import annotations

import networkx as nx
import numpy as np
import pandas as pd

from ringshield.rings import Ring

AGGREGATOR_ID = "cc"
REQUIRED = ("edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp")


SELECT_COL = "score_raw"   # seeds are always selected on the raw score (see aggregate_cc)


def score_column(scored_edges: pd.DataFrame) -> str:
    """Column used for `confidence` / `max_edge_prob`: calibrated when available."""
    return "score_calibrated" if "score_calibrated" in scored_edges.columns else "score_raw"


def threshold_for_pct(scores: np.ndarray, seed_frac_pct: float) -> float:
    """The (100 - seed_frac_pct) percentile of the non-NaN scores. The quantile cut is STRICT
    (`score > q`, configs/threshold_rule.yaml): a plateau of tied scores sitting on the
    boundary is excluded rather than swept in wholesale -- ties are edges the model cannot
    tell apart, not a seed set. An explicit absolute `threshold=` stays inclusive (`>=`)."""
    s = np.asarray(scores, dtype=float)
    s = s[~np.isnan(s)]
    return float(np.percentile(s, 100 - seed_frac_pct))


def seed_mask_for_pct(scores: np.ndarray, seed_frac_pct: float) -> np.ndarray:
    """Boolean mask of the seed edges under the strict quantile rule (NaN never a seed)."""
    s = np.asarray(scores, dtype=float)
    q = threshold_for_pct(s, seed_frac_pct)
    return ~np.isnan(s) & (s > q)


def _mode_smallest(values: np.ndarray) -> int:
    """Most common value; ties broken by the smallest value (deterministic)."""
    vals, counts = np.unique(values, return_counts=True)
    return int(vals[np.argmax(counts)])


def _split_by_time(G: nx.Graph, components, max_gap_seconds: float):
    """Re-cluster each component using only edges close in time (legacy behaviour)."""
    out = []
    for members in components:
        sub = G.subgraph(members)
        H = nx.Graph()
        H.add_nodes_from(members)
        for u, v, d in sub.edges(data=True):
            H.add_edge(u, v, t=float(np.median(d["times"])))
        edges = sorted(H.edges(data=True), key=lambda e: e[2]["t"])
        K = nx.Graph()
        K.add_nodes_from(members)
        for i, (u, v, d) in enumerate(edges):
            K.add_edge(u, v)
            for u2, v2, d2 in edges[i + 1:]:
                if d2["t"] - d["t"] > max_gap_seconds:
                    break
                if u2 in (u, v) or v2 in (u, v):
                    K.add_edge(u2, v2)
        out.extend(nx.connected_components(K))
    return out


def aggregate_cc(scored_edges: pd.DataFrame, seed_frac_pct: float, min_size: int,
                 max_gap_hours: float | None = None, *, score_col: str | None = None,
                 threshold: float | None = None, aggregator_id: str = AGGREGATOR_ID,
                 verbose: bool = False) -> list[Ring]:
    """Threshold, connected components, size filter -> rings sorted by confidence (desc).

    `threshold` (keyword) overrides the percentile cut with an absolute score cut; the legacy
    CLI's --threshold uses it. Everything else keys off `seed_frac_pct`.

    Seed SELECTION always uses `score_raw` (`score_col` overrides only for tests / legacy files):
    isotonic calibration is monotone but maps hundreds of thousands of distinct raw scores onto
    ~100-150 levels, so a quantile cut on the calibrated score lands inside a tie level and the
    strict rule would drop a large slice of the intended seeds (gfpxgb: 264 of 960 at 0.1 %).
    `confidence` / `max_edge_prob` use the calibrated score when it exists (score_column)."""
    missing = [c for c in REQUIRED if c not in scored_edges.columns]
    if missing:
        raise ValueError(f"scored_edges is missing {missing}")
    score_col = score_col or SELECT_COL
    conf_col = score_column(scored_edges) if score_col == SELECT_COL else score_col
    scores = scored_edges[score_col].to_numpy(dtype=float)
    valid = ~np.isnan(scores)
    if not valid.any():
        return []
    if threshold is None:
        threshold = threshold_for_pct(scores, seed_frac_pct)
        flagged_mask = valid & (scores > threshold)          # strict quantile cut (ties excluded)
        rule = f"top {seed_frac_pct}% -> q {threshold:.4f}, strict (score > q)"
    else:
        flagged_mask = valid & (scores >= threshold)         # explicit absolute cut, inclusive
        rule = f"threshold {threshold:.4f} (score >= t)"
    if verbose:
        print(f"  {int(valid.sum()):,} scored edges; {rule}; edges above cutoff: {int(flagged_mask.sum()):,} / "
              f"{len(scored_edges):,} ({flagged_mask.mean() * 100:.3f}%)")
    if not flagged_mask.any():
        return []

    flagged = scored_edges.loc[flagged_mask, ["from_id", "to_id", "timestamp", conf_col]]
    G = nx.Graph()
    for f, t, ts, p in flagged.itertuples(index=False):
        if G.has_edge(f, t):
            e = G[f][t]
            e["probs"].append(p)
            e["times"].append(ts)
        else:
            G.add_edge(f, t, probs=[p], times=[ts])
    components = list(nx.connected_components(G))
    if verbose:
        print(f"  Raw connected components: {len(components)}")
    if max_gap_hours is not None:
        components = _split_by_time(G, components, max_gap_hours * 3600)
        if verbose:
            print(f"  After time-window splitting: {len(components)}")

    kept, n_small = [], 0
    for members in components:
        n = len(members)
        if n < min_size:
            n_small += 1
            continue
        sub = G.subgraph(members)
        m = sub.number_of_edges()
        probs = [p for _, _, d in sub.edges(data=True) for p in d["probs"]]
        times = [t for _, _, d in sub.edges(data=True) for t in d["times"]]
        kept.append({
            "members": sorted(int(x) for x in members), "n_edges": m,
            "confidence": float(np.mean(probs)), "max_edge_prob": float(np.max(probs)),
            "density": m / (n * (n - 1)) if n > 1 else 0.0,
            "start_time": int(min(times)), "end_time": int(max(times)),
        })
    if verbose:
        print(f"  Dropped (size < {min_size}): {n_small}; candidate rings: {len(kept)}")
        if kept:
            big = max(len(r["members"]) for r in kept)
            if big > 100:
                print(f"  WARNING: largest candidate has {big} members. Components chain through shared "
                      f"accounts, so a few false-positive edges on a hub can merge many rings. Try max_gap_hours.")
    kept.sort(key=lambda r: -r["confidence"])
    if not kept:
        return []

    # Components are node-disjoint, so every account maps to at most one ring: member_edges and
    # seed_edges come from one vectorised pass over the split instead of one isin() per ring.
    ring_of = {}
    for i, r in enumerate(kept):
        for a in r["members"]:
            ring_of[a] = i
    from_id = scored_edges["from_id"].to_numpy(np.int64)
    to_id = scored_edges["to_id"].to_numpy(np.int64)
    ts = scored_edges["timestamp"].to_numpy(np.int64)
    edge_id = scored_edges["edge_id"].to_numpy(np.int64)
    rf = np.array([ring_of.get(a, -1) for a in from_id.tolist()], dtype=np.int64)
    rt = np.array([ring_of.get(a, -1) for a in to_id.tolist()], dtype=np.int64)
    same = (rf >= 0) & (rf == rt)
    start = np.array([r["start_time"] for r in kept], dtype=np.int64)
    end = np.array([r["end_time"] for r in kept], dtype=np.int64)
    in_win = same.copy()
    in_win[same] = (ts[same] >= start[rf[same]]) & (ts[same] <= end[rf[same]])
    member_of = np.where(in_win, rf, -1)
    seed_of = np.where(in_win & flagged_mask, rf, -1)

    # bank of every member account, from the edges it appears on (contract: most common bank)
    bank_of: dict[int, int] = {}
    for a, b in zip(from_id.tolist(), scored_edges["from_bank"].to_numpy(np.int64).tolist()):
        bank_of.setdefault(a, b)
    for a, b in zip(to_id.tolist(), scored_edges["to_bank"].to_numpy(np.int64).tolist()):
        bank_of.setdefault(a, b)

    rings: list[Ring] = []
    for i, r in enumerate(kept):
        member_edges = edge_id[member_of == i]
        seed_edges = edge_id[seed_of == i]
        assert len(seed_edges) > 0 and len(member_edges) >= len(seed_edges)
        assert int(ts[member_of == i].min()) == r["start_time"]
        banks = np.array([bank_of[a] for a in r["members"]], dtype=np.int64)
        rings.append(Ring.baseline(
            ring_id=f"{aggregator_id}-{i}", tenant_id=_mode_smallest(banks), aggregator_id=aggregator_id,
            members=r["members"], member_edges=member_edges.tolist(), seed_edges=seed_edges.tolist(),
            n_edges=r["n_edges"], start_time=r["start_time"], end_time=r["end_time"],
            confidence=r["confidence"], max_edge_prob=r["max_edge_prob"], density=r["density"]))
    return rings
