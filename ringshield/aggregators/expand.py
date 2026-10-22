"""'expand' -- Stage B: seed components grown by the expansion policy, then components on the
expanded subgraph (Step 6.4).

    trajs = expand_all(scored_edges, seed_mask, policy, ctx, delta_t_h=72, p_floor=0.3)
    rings = rings_from_trajectories(scored_edges, seed_mask, trajs, p_min=0.5, min_size=3)
    rings = aggregate_expand(scored_edges, 0.1, 3, policy=policy, ctx=ctx, p_min=0.5, delta_t_h=72)

Per seed component (connected component of the thresholded edges, any size):

    included = its seed edges; window = [min seed time - delta_t, max seed time + delta_t]
    repeat: candidates(included, delta_t, 2 hops, window) -> features at the candidate's timestamp
            -> p = policy(features); add the argmax if p >= p_min; stop when no candidate reaches
            p_min, after MAX_ITER additions, or on closure: every included account with both an
            inflow and an outflow has closure >= CLOSURE_STOP and no candidate with p >= p_min
            would raise closure anywhere (delta_closure > 0) -- without the second clause a
            single balanced pass-through account would stop a half-recovered stack
    (rule policies add every candidate with p >= p_min in ONE pass -- B1 / B1b are not iterative)

The greedy path is deterministic given the included set, so the run for the lowest p_min of a
grid is computed once and the higher p_min results are its prefixes (a trajectory stops at the
first addition whose p is below p_min): `expand_all` records (edge_id, p, closure_after) per
addition and `rings_from_trajectories` truncates. Every added edge is asserted to lie inside the
component's seed window. Rings come from ringshield.aggregators.cc.rings_from_masks over
seed + expanded edges: an edge added by two components merges them; `seed_edges` /
`expanded_edges` / `member_edges` per the contract; `conservation_closure` = mean closure over
the ring's included accounts that have both an inflow and an outflow (NaN if none).
"""
from __future__ import annotations

import time

import networkx as nx
import numpy as np
import pandas as pd

from ringshield.aggregators.cc import SELECT_COL, rings_from_masks, score_column, seed_graph, seed_mask_for_pct
from ringshield.expand.candidates import MAX_EVENTS_PER_QUERY, candidates
from ringshield.expand.features import FeatureContext, compute_features
from ringshield.expand.policy import Policy
from ringshield.rings import Ring

AGGREGATOR_ID = "expand"
MAX_ITER = 200
CLOSURE_STOP = 0.98


def _closure_all(idx, inc_pos: np.ndarray) -> tuple[float, bool]:
    """(mean closure over included accounts with both flows, all of them >= CLOSURE_STOP)."""
    f, t, a = idx.from_dense[inc_pos], idx.to_dense[inc_pos], idx.amount[inc_pos]
    out_sum = pd.Series(a).groupby(f).sum()
    in_sum = pd.Series(a).groupby(t).sum()
    both = out_sum.index.intersection(in_sum.index)
    if len(both) == 0:
        return float("nan"), False
    i, o = in_sum.loc[both].to_numpy(), out_sum.loc[both].to_numpy()
    c = np.minimum(i, o) / np.maximum(i, o)
    return float(c.mean()), bool((c >= CLOSURE_STOP).all())


def expand_component(scored_edges: pd.DataFrame, seed_edge_ids, policy: Policy, ctx: FeatureContext, *,
                     delta_t_h: float, p_floor: float, max_hops: int = 2, max_iter: int = MAX_ITER,
                     max_events_per_query: int | None = MAX_EVENTS_PER_QUERY) -> dict:
    """Greedy expansion of one seed component down to p_floor. Returns the trajectory:
    {"seeds": [...], "window": (lo, hi), "adds": [(edge_id, p, closure_mean, closure_stop)], "stop": str,
     "n_iter": int, "n_candidates_first": int}."""
    idx = ctx.idx
    seeds = [int(e) for e in seed_edge_ids]
    sp = idx.pos_of(seeds)
    delta = int(round(delta_t_h * 3600))
    window = (int(idx.ts[sp].min()) - delta, int(idx.ts[sp].max()) + delta)
    included = list(seeds)
    adds, stop, n_first = [], "no_candidate", None
    one_pass = policy.kind != "model"
    for it in range(max_iter):
        cand = candidates(scored_edges, included, delta_t_h, max_hops, index=idx, max_events_per_query=max_events_per_query,
                          time_bounds=window)
        if n_first is None:
            n_first = int(len(cand))
        if len(cand) == 0:
            stop = "no_candidate"
            break
        X = compute_features(ctx, cand, included, delta_t_h)
        p = policy.predict(X)
        if one_pass:
            take = np.where(p >= p_floor)[0]
            for j in take:
                adds.append((int(cand["candidate_edge_id"].iat[j]), float(p[j]), float("nan"), False))
            stop = "one_pass"
            break
        cm, closed = _closure_all(idx, idx.pos_of(included))
        if closed and not bool(((p >= p_floor) & (X["delta_closure"].to_numpy() > 0)).any()):
            stop = "closure"
            break
        j = int(np.argmax(p))
        if p[j] < p_floor:
            stop = "below_p_floor"
            break
        e = int(cand["candidate_edge_id"].iat[j])
        included.append(e)
        cm, closed = _closure_all(idx, idx.pos_of(included))
        adds.append((e, float(p[j]), cm, closed))
    else:
        stop = "max_iter"
    ts_add = idx.ts[idx.pos_of([a[0] for a in adds])] if adds else np.zeros(0, np.int64)
    assert np.all((ts_add >= window[0]) & (ts_add <= window[1])), "expansion added an edge outside the seed window"
    return {"seeds": seeds, "window": window, "adds": adds, "stop": stop, "n_iter": len(adds), "n_candidates_first": n_first}


def seed_components(scored_edges: pd.DataFrame, seed_mask: np.ndarray) -> list[list[int]]:
    """Seed edge ids per connected component of the thresholded graph (every size)."""
    G = seed_graph(scored_edges, seed_mask, SELECT_COL)
    comp_of = {}
    for i, members in enumerate(nx.connected_components(G)):
        for a in members:
            comp_of[a] = i
    out: dict[int, list[int]] = {}
    sub = scored_edges.loc[seed_mask, ["edge_id", "from_id"]]
    for e, f in sub.itertuples(index=False):
        out.setdefault(comp_of[f], []).append(int(e))
    return [sorted(v) for _, v in sorted(out.items())]


def expand_all(scored_edges: pd.DataFrame, seed_mask: np.ndarray, policy: Policy, ctx: FeatureContext, *,
               delta_t_h: float, p_floor: float, max_hops: int = 2, verbose: bool = False, **kw) -> list[dict]:
    comps = seed_components(scored_edges, seed_mask)
    t0 = time.time()
    trajs = []
    for i, seeds in enumerate(comps):
        tr = expand_component(scored_edges, seeds, policy, ctx, delta_t_h=delta_t_h, p_floor=p_floor, max_hops=max_hops, **kw)
        tr["component"] = i
        trajs.append(tr)
        if verbose and (i + 1) % 50 == 0:
            print(f"    expanded {i + 1}/{len(comps)} components ({time.time() - t0:.0f}s)", flush=True)
    if verbose:
        n_add = sum(len(t["adds"]) for t in trajs)
        print(f"  expand: {len(comps)} seed components, {n_add} additions down to p {p_floor} in {time.time() - t0:.0f}s "
              f"(stops: {pd.Series([t['stop'] for t in trajs]).value_counts().to_dict()})")
    return trajs


def truncate(traj: dict, p_min: float) -> list[int]:
    """Edges a run with threshold p_min would have added (prefix rule; one-pass rules filter)."""
    out = []
    for e, p, _, _ in traj["adds"]:
        if p < p_min:
            if traj["stop"] == "one_pass":
                continue
            break
        out.append(e)
    return out


def rings_from_trajectories(scored_edges: pd.DataFrame, seed_mask: np.ndarray, trajs: list[dict], p_min: float,
                            min_size: int, max_gap_hours: float | None = None, *, aggregator_id: str = AGGREGATOR_ID,
                            verbose: bool = False, report: dict | None = None) -> list[Ring]:
    pos = pd.Series(np.arange(len(scored_edges)), index=scored_edges["edge_id"].to_numpy())
    added = sorted({e for t in trajs for e in truncate(t, p_min)})
    exp_mask = np.zeros(len(scored_edges), dtype=bool)
    if added:
        exp_mask[pos.loc[added].to_numpy()] = True
    exp_mask &= ~seed_mask
    rings = rings_from_masks(scored_edges, seed_mask, exp_mask, min_size, max_gap_hours,
                             conf_col=score_column(scored_edges), aggregator_id=aggregator_id, verbose=verbose)
    # ring-level conservation closure over seed + expanded edges
    se = scored_edges.set_index("edge_id")
    amt_col = "amount_received" if "amount_received" in se.columns else "amount"
    for r in rings:
        inc = r.seed_edges + r.expanded_edges
        sub = se.loc[inc, ["from_id", "to_id", amt_col]]
        o = sub.groupby("from_id")[amt_col].sum()
        i = sub.groupby("to_id")[amt_col].sum()
        both = o.index.intersection(i.index)
        if len(both):
            c = np.minimum(i.loc[both].to_numpy(), o.loc[both].to_numpy()) / np.maximum(i.loc[both].to_numpy(), o.loc[both].to_numpy())
            r.conservation_closure = float(c.mean())
    if report is not None:
        report.update({"p_min": p_min, "n_components": len(trajs), "n_expanded_edges": int(exp_mask.sum()),
                       "n_components_expanded": int(sum(1 for t in trajs if truncate(t, p_min))),
                       "n_rings": len(rings), "n_rings_with_expansion": int(sum(1 for r in rings if r.expanded_edges))})
    return rings


def aggregate_expand(scored_edges: pd.DataFrame, seed_frac_pct: float, min_size: int, max_gap_hours: float | None = None, *,
                     policy: Policy, ctx: FeatureContext, p_min: float, delta_t_h: float, max_hops: int = 2,
                     aggregator_id: str = AGGREGATOR_ID, verbose: bool = False, report: dict | None = None) -> list[Ring]:
    """One operating point: threshold -> expand every seed component -> components on the expanded subgraph."""
    seed_mask = seed_mask_for_pct(scored_edges[SELECT_COL].to_numpy(float), seed_frac_pct)
    trajs = expand_all(scored_edges, seed_mask, policy, ctx, delta_t_h=delta_t_h, p_floor=p_min, max_hops=max_hops, verbose=verbose)
    return rings_from_trajectories(scored_edges, seed_mask, trajs, p_min, min_size, max_gap_hours,
                                   aggregator_id=aggregator_id, verbose=verbose, report=report)
