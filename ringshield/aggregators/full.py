"""'full' -- Stage B + C: expansion, then partition of every expanded component into attempts (Step 7).

    rings = aggregate_full(scored_edges, 0.1, 3, policy=policy, ctx=ctx, p_min=0.7, delta_t_h=24,
                           affinity=aff, method="pivot")                       # proposed
    rings = aggregate_full(..., method="b3", gap_h=24)                        # baseline B3

Shared pipeline (identical for every method, so the baselines see the SAME expanded subgraph):
seeds (strict quantile) -> greedy expansion (ringshield.aggregators.expand) -> included edges =
seeds + expanded -> components of their account graph. Then one of

    b2        plain components                                   (= the 'expand' aggregator's rings)
    b3        time-windowed components: two included edges are joined if they share an account and
              are at most gap_h apart (gap chosen on val); an edge belongs to exactly one group, so
              nothing is dropped. The edge-level routine is cc.time_window_labels, which
              cc._split_by_time (the legacy `max_gap_hours` path, a no-op from E7 until Step 7)
              now also delegates to
    b4        Louvain (python-louvain, fixed random_state) on the account graph whose edge weight
              is the mean pair affinity of the transactions between the two accounts (0.5 when a
              transaction has no pair); an edge crossing communities is dropped
    pivot     shared-account pairs -> affinity p -> greedy pivot correlation clustering over the
              included edges (w = logit(p), threshold 0.5)
    average   the same pairs -> average-linkage agglomerative with distance 1 - p, cut chosen on val
    both: clusters spanning fewer than min_size accounts are re-attached to their best-linked
    neighbour (affinity.reattach_small) -- a fragment below min_size can never be a ring

Each cluster becomes one Ring: members = endpoints of its included edges, `seed_edges` /
`expanded_edges` its included edges, `member_edges` every edge of the split among the members
inside [start, end] (the contract's rule), `n_edges` / `density` over the distinct account pairs
of its included edges, `max_edge_prob` over its seed edges. Clusters with fewer than `min_size`
members are dropped. Rings of a partition may share accounts (a hub belongs to every attempt
that used it).

Step 8 fills the rest of the contract from `ringshield.roles` and `ringshield.typing`:
`source_accounts` / `sink_accounts` / `mule_accounts` from the account roles,
`conservation_closure` = 1 - |inflow at sinks - outflow at sources| / max(both), NaN without a
source or a sink, `confidence` = mean `score_calibrated` over the seed edges x that closure (the
closure factor is dropped when it is NaN), `expanded_edge_probs` aligned with `expanded_edges`
(pass `probs=`, the expansion trajectories carry them), and `topology_type` / `topology_probs`
from the typing head (`head=`) or the rule scorer (`head="rule"`); without either the ring stays
UNKNOWN / uniform.
"""
from __future__ import annotations

import math
from typing import Callable

import networkx as nx
import numpy as np
import pandas as pd

from ringshield.aggregators.cc import SELECT_COL, _mode_smallest, score_column, seed_mask_for_pct, time_window_labels
from ringshield.aggregators.expand import expand_all, truncate
from ringshield.expand.features import FeatureContext
from ringshield.partition.affinity import Affinity, cluster_average, cluster_pivot, reattach_small
from ringshield.partition.pairs import components_of, pair_features
from ringshield.rings import Ring
from ringshield.roles import account_roles, conservation_closure, load_roles_config, ring_confidence, role_arrays

AGGREGATOR_ID = "full"
METHODS = ("b2", "b3", "b4", "pivot", "average")


def included_from_trajectories(scored_edges: pd.DataFrame, seed_mask: np.ndarray, trajs: list[dict], p_min: float):
    """(inc_pos, is_seed) of seeds + the expansion's additions at p_min (positions into scored_edges)."""
    pos = pd.Series(np.arange(len(scored_edges)), index=scored_edges["edge_id"].to_numpy())
    added = sorted({e for t in trajs for e in truncate(t, p_min)})
    exp_mask = np.zeros(len(scored_edges), dtype=bool)
    if added:
        exp_mask[pos.loc[added].to_numpy()] = True
    exp_mask &= ~seed_mask
    inc_pos = np.flatnonzero(seed_mask | exp_mask)
    return inc_pos, seed_mask[inc_pos]


def component_pairs(ctx: FeatureContext, inc_pos: np.ndarray, is_seed: np.ndarray, comp: np.ndarray, affinity: Affinity | None):
    """Pair rows with an `affinity` column (NaN without a model)."""
    idx = ctx.idx
    emb_of = None
    if ctx.emb is not None:
        def emb_of(pa, pb):
            return ctx.emb.get(idx.edge_id[pa]), ctx.emb.get(idx.edge_id[pb])
    P = pair_features(idx, ctx.gfp, inc_pos, is_seed, comp, emb_of=emb_of)
    P["affinity"] = affinity.predict(P) if (affinity is not None and len(P)) else np.nan
    return P


def time_windowed_labels(idx, inc_pos: np.ndarray, comp: np.ndarray, gap_s: float) -> np.ndarray:
    """Group id per included edge: two edges of the same component are joined when they share an
    account and lie at most `gap_s` apart (ringshield.aggregators.cc.time_window_labels)."""
    return time_window_labels(idx.from_dense[inc_pos], idx.to_dense[inc_pos], idx.ts[inc_pos], comp, gap_s)


def _local(inc_pos: np.ndarray, comp: np.ndarray):
    """Per component: local index of every included edge."""
    order = np.argsort(comp, kind="stable")
    local = np.empty(len(inc_pos), dtype=np.int64)
    starts = {}
    for c in np.unique(comp):
        m = np.flatnonzero(comp == c)
        local[m] = np.arange(len(m))
        starts[int(c)] = m
    return local, starts


def partition_labels(ctx: FeatureContext, inc_pos: np.ndarray, is_seed: np.ndarray, comp: np.ndarray, *, method: str,
                     pairs: pd.DataFrame | None = None, cut: float = 0.5, threshold: float = 0.5, gap_h: float | None = None,
                     resolution: float = 1.0, seed: int = 0, min_members: int | None = None) -> np.ndarray:
    """Global cluster label per included edge (-1 = dropped: an edge crossing a B3 / B4 split)."""
    assert method in METHODS, method
    idx = ctx.idx
    n = len(inc_pos)
    if method == "b2":
        return comp.astype(np.int64)
    labels = np.full(n, -1, dtype=np.int64)
    f, t = idx.from_dense[inc_pos], idx.to_dense[inc_pos]
    if method == "b3":
        assert gap_h is not None
        return time_windowed_labels(idx, inc_pos, comp, float(gap_h) * 3600)
    if method == "b4":
        # account graph of the included edges, one networkx edge per account pair, weight = mean pair affinity
        assert pairs is not None
        import community.community_louvain as louvain
        e_p = pd.concat([pairs[["edge_a", "affinity"]].rename(columns={"edge_a": "e"}),
                         pairs[["edge_b", "affinity"]].rename(columns={"edge_b": "e"})]).groupby("e")["affinity"].mean()
        pair_p = e_p.reindex(idx.edge_id[inc_pos]).fillna(0.5).to_numpy()
        G = nx.Graph()
        for i in range(n):
            u, v = int(f[i]), int(t[i])
            if G.has_edge(u, v):
                G[u][v]["ws"].append(float(pair_p[i]))
            else:
                G.add_edge(u, v, ws=[float(pair_p[i])])
        for u, v, d in G.edges(data=True):
            d["weight"] = float(np.mean(d["ws"]))
        part = louvain.best_partition(G, weight="weight", resolution=float(resolution), random_state=int(seed))
        groups = {}
        for a, c in part.items():
            groups.setdefault(c, set()).add(a)
        groups = list(groups.values())
        acc_group = {}
        for k, members in enumerate(groups):
            for a in members:
                acc_group[a] = k
        for i in range(n):
            gu, gv = acc_group.get(int(f[i])), acc_group.get(int(t[i]))
            if gu is not None and gu == gv:
                labels[i] = gu
        return labels
    assert pairs is not None and "affinity" in pairs.columns
    pos_of_edge = pd.Series(np.arange(n), index=idx.edge_id[inc_pos])
    local, members = _local(inc_pos, comp)
    ia_all = pos_of_edge.loc[pairs["edge_a"].to_numpy()].to_numpy() if len(pairs) else np.zeros(0, np.int64)
    ib_all = pos_of_edge.loc[pairs["edge_b"].to_numpy()].to_numpy() if len(pairs) else np.zeros(0, np.int64)
    p_all = pairs["affinity"].to_numpy(float) if len(pairs) else np.zeros(0)
    pc = pairs["component"].to_numpy() if len(pairs) else np.zeros(0, np.int64)
    next_label = 0
    for c, m in members.items():
        sel = pc == c
        ia, ib, p = local[ia_all[sel]], local[ib_all[sel]], p_all[sel]
        if method == "pivot":
            lab = cluster_pivot(len(m), ia, ib, p, seed=seed, threshold=threshold)
        else:
            lab = cluster_average(len(m), ia, ib, p, cut=cut)
        if min_members:
            ends = np.stack([idx.from_dense[inc_pos[m]], idx.to_dense[inc_pos[m]]], axis=1)
            lab = reattach_small(lab, ia, ib, p, ends, min_members)
        labels[m] = lab + next_label
        next_label += int(lab.max()) + 1 if len(lab) else 0
    return labels


def rings_from_edge_clusters(scored_edges: pd.DataFrame, idx, inc_pos: np.ndarray, is_seed: np.ndarray, labels: np.ndarray,
                             min_size: int, *, aggregator_id: str = AGGREGATOR_ID, conf_col: str | None = None,
                             probs: dict | None = None, head=None, report: dict | None = None) -> list[Ring]:
    """`probs`: {edge_id: expansion probability} for the expanded edges (Step 8 contract column).
    `head`: a ringshield.typing.head.TypingHead, or the string "rule" for the rule scorer, or None
    (topology stays UNKNOWN / uniform)."""
    conf_col = conf_col or score_column(scored_edges)
    conf = scored_edges[conf_col].to_numpy(float)
    bank_f, bank_t = scored_edges["from_bank"].to_numpy(np.int64), scored_edges["to_bank"].to_numpy(np.int64)
    amt = idx.amount
    rings: list[dict] = []
    for lab in np.unique(labels[labels >= 0]):
        m = np.flatnonzero(labels == lab)
        ep = inc_pos[m]
        f, t = idx.from_dense[ep], idx.to_dense[ep]
        members_d = np.unique(np.concatenate([f, t]))
        if len(members_d) < min_size:
            continue
        seeds = ep[is_seed[m]]
        if len(seeds) == 0:
            continue
        mean_seed_score = float(np.nanmean(conf[seeds]))
        start, end = int(idx.ts[ep].min()), int(idx.ts[ep].max())
        # member edges: every edge of the split with both endpoints in the cluster inside [start, end]
        lo, hi = idx.window(members_d, start, end)
        _, ev = idx.expand(lo, hi)
        cand = np.unique(idx.ev_pos[ev])
        both = np.isin(idx.from_dense[cand], members_d) & np.isin(idx.to_dense[cand], members_d)
        member_edges = cand[both]
        pairs_d = np.unique(np.minimum(f, t).astype(np.int64) * (len(idx.acc_uniq) + 1) + np.maximum(f, t))
        n_edges, n = len(pairs_d), len(members_d)
        closure = math.nan                      # filled below from the account roles (contract definition)
        banks = np.concatenate([bank_f[ep], bank_t[ep]])
        rings.append({"members": idx.acc_uniq[members_d].tolist(), "member_edges": idx.edge_id[member_edges].tolist(),
                      "seed_edges": idx.edge_id[seeds].tolist(), "expanded_edges": idx.edge_id[ep[~is_seed[m]]].tolist(),
                      "n_edges": n_edges, "start": start, "end": end, "confidence": mean_seed_score, "mean_seed_score": mean_seed_score,
                      "max_edge_prob": float(np.nanmax(conf[seeds])), "density": n_edges / (n * (n - 1)) if n > 1 else 0.0,
                      "closure": closure, "tenant": _mode_smallest(banks)})
    # Step 8: roles, closure, contract confidence, expansion probabilities, topology
    cfg = load_roles_config()
    n_closure_nan = 0
    for r in rings:
        stub = Ring.baseline(ring_id="tmp", tenant_id=r["tenant"], aggregator_id=aggregator_id, members=r["members"],
                             member_edges=sorted(r["member_edges"]), seed_edges=sorted(r["seed_edges"]), n_edges=r["n_edges"],
                             start_time=r["start"], end_time=r["end"], confidence=0.0, max_edge_prob=r["max_edge_prob"],
                             density=r["density"])
        stub.expanded_edges = sorted(r["expanded_edges"])
        roles = account_roles(stub, scored_edges, config=cfg)
        r["roles"] = roles
        r["closure"] = conservation_closure(roles)
        n_closure_nan += int(math.isnan(r["closure"]))
        r["confidence"] = ring_confidence(r["mean_seed_score"], r["closure"])
    rings.sort(key=lambda r: (-r["confidence"], min(r["seed_edges"])))
    out = []
    for k, r in enumerate(rings):
        ring = Ring.baseline(ring_id=f"{aggregator_id}-{k}", tenant_id=r["tenant"], aggregator_id=aggregator_id, members=r["members"],
                             member_edges=sorted(r["member_edges"]), seed_edges=sorted(r["seed_edges"]), n_edges=r["n_edges"],
                             start_time=r["start"], end_time=r["end"], confidence=r["confidence"], max_edge_prob=r["max_edge_prob"],
                             density=r["density"])
        ring.expanded_edges = sorted(r["expanded_edges"])
        ring.expanded_edge_probs = [float(probs.get(e, float("nan"))) if probs else float("nan") for e in ring.expanded_edges]
        ring.conservation_closure = r["closure"]
        arrays = role_arrays(r["roles"], cfg)
        ring.source_accounts, ring.sink_accounts, ring.mule_accounts = arrays["source_accounts"], arrays["sink_accounts"], arrays["mule_accounts"]
        assert set(ring.seed_edges) <= set(ring.member_edges) and set(ring.expanded_edges) <= set(ring.member_edges)
        assert len(ring.expanded_edge_probs) == len(ring.expanded_edges)
        out.append(ring)
    if head is not None and out:
        _attach_topology(out, scored_edges, head)
    if report is not None:
        report.update({"n_rings_closure_nan": n_closure_nan,
                       "n_rings_no_expansion_probs": int(sum(1 for r in out if r.expanded_edges and any(math.isnan(p) for p in r.expanded_edge_probs)))})
    return out


def _attach_topology(rings: list[Ring], scored_edges: pd.DataFrame, head) -> None:
    """Fill topology_type / topology_probs from the typing head (or the rule scorer)."""
    from ringshield.typing.features import ring_features
    from ringshield.typing.rules import rule_probs, rule_type
    from contract.schema import TOPOLOGY_TYPES
    cfg = load_roles_config()
    se = scored_edges.set_index("edge_id")
    rows = []
    for r in rings:
        inc = sorted(set(r.seed_edges + r.expanded_edges))
        edges = se.loc[inc].reset_index()
        roles = account_roles(r, scored_edges, config=cfg)
        rows.append(ring_features(edges, roles, seed_ratio=len(r.seed_edges) / max(len(inc), 1)))
    if head == "rule":
        for r, f in zip(rings, rows):
            r.topology_type = rule_type(f)
            r.topology_probs = [float(x) for x in rule_probs(f)]
        return
    P = head.predict_probs(rows)
    for r, p in zip(rings, P):
        r.topology_type = TOPOLOGY_TYPES[int(np.argmax(p))]
        r.topology_probs = [float(x) for x in p]


def expansion_probs(trajs: list[dict], p_min: float) -> dict[int, float]:
    """{edge_id: policy probability} over the additions a run at `p_min` keeps (contract column)."""
    out: dict[int, float] = {}
    for t in trajs:
        for e in truncate(t, p_min):
            for eid, p, _, _ in t["adds"]:
                if eid == e:
                    out[int(eid)] = float(p)
                    break
    return out


def aggregate_full(scored_edges: pd.DataFrame, seed_frac_pct: float, min_size: int, max_gap_hours: float | None = None, *,
                   policy, ctx: FeatureContext, p_min: float, delta_t_h: float, affinity: Affinity | None = None,
                   method: str = "pivot", cut: float = 0.5, threshold: float = 0.5, gap_h: float | None = None,
                   resolution: float = 1.0, seed: int = 0, max_hops: int = 2, aggregator_id: str = AGGREGATOR_ID,
                   report: dict | None = None, trajs: list[dict] | None = None, pairs: pd.DataFrame | None = None,
                   head=None) -> list[Ring]:
    """One operating point end to end. `trajs` / `pairs` may be passed to reuse the expansion and the
    pair affinities across methods (the grids in run_partition.py do)."""
    seed_mask = seed_mask_for_pct(scored_edges[SELECT_COL].to_numpy(float), seed_frac_pct)
    if trajs is None:
        trajs = expand_all(scored_edges, seed_mask, policy, ctx, delta_t_h=delta_t_h, p_floor=p_min, max_hops=max_hops)
    inc_pos, is_seed = included_from_trajectories(scored_edges, seed_mask, trajs, p_min)
    comp = components_of(ctx.idx, inc_pos)
    if pairs is None and method in ("b4", "pivot", "average"):
        pairs = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
    labels = partition_labels(ctx, inc_pos, is_seed, comp, method=method, pairs=pairs, cut=cut, threshold=threshold,
                              gap_h=gap_h if gap_h is not None else max_gap_hours, resolution=resolution, seed=seed, min_members=min_size)
    rings = rings_from_edge_clusters(scored_edges, ctx.idx, inc_pos, is_seed, labels, min_size, aggregator_id=aggregator_id,
                                     probs=expansion_probs(trajs, p_min), head=head, report=report)
    if report is not None:
        report.update({"method": method, "n_included": int(len(inc_pos)), "n_seeds": int(is_seed.sum()), "n_components": int(comp.max() + 1) if len(comp) else 0,
                       "n_clusters": int(len(np.unique(labels[labels >= 0]))), "n_dropped_edges": int((labels < 0).sum()),
                       "n_pairs": int(len(pairs)) if pairs is not None else 0, "n_rings": len(rings),
                       "n_rings_gt100": int(sum(1 for r in rings if r.n_members > 100)),
                       "components_split": int(sum(1 for c in np.unique(comp) if len(np.unique(labels[(comp == c) & (labels >= 0)])) > 1))})
    return rings
