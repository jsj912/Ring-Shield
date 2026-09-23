"""Per-ring topology features (Step 8.2).

    f = ring_features(edges, roles)          # edges: the ring's included edges, roles: account_roles()

`edges` is a scored_edges frame restricted to the ring (deduplicated inside), `roles` the output
of `ringshield.roles.account_roles`. The features describe the SHAPE of the account graph, so the
same function serves a predicted ring and a ground-truth ring (whose "edges" are its pattern
lines and whose roles come from the same routine).

RING_FEATURES (23):
    role counts / fractions           n_source, n_sink, n_mule, n_holder, n_peripheral and the
                                      same divided by n_members
    size / time                       n_members, n_edges (distinct account pairs), n_txn,
                                      duration_h, density, txn_per_member
    structure                         longest_path (longest directed simple path, capped),
                                      has_cycle (directed cycle present), cycle_cover (fraction of
                                      members on the longest directed cycle found),
                                      bipartite_score (fraction of edges crossing the best
                                      2-colouring), bipartite_min_side (smaller side / n_members),
                                      max_out_degree, max_in_degree, mean_degree, n_branch_points
                                      (accounts with out-degree >= 2), frac_leaf
    fragmentation / hubs              n_components and max_component_frac (a ring visible in one
                                      split is usually a FRAGMENT of its pattern: BIPARTITE and
                                      STACK arrive as several disconnected pieces),
                                      n_pair_components (2-account pieces), n_both (accounts with
                                      an inflow and an outflow = pass-throughs), n_hub_in /
                                      n_hub_out (in- / out-degree >= 2) and n_hub_both (both),
                                      the signature of a gather-then-scatter account
    provenance                        seed_ratio (seed edges / included edges)

Graph conventions: the directed multigraph is collapsed to distinct (from, to) account pairs;
`longest_path` and the cycle search are exact by DFS for rings up to MAX_EXACT_NODES accounts
(every ring in AMLworld's ground truth is far below it) and fall back to a greedy bound above.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

import networkx as nx
import numpy as np
import pandas as pd

from ringshield.roles import dedup_edges

MAX_EXACT_NODES = 40
ROLE_NAMES = ("source", "sink", "mule", "holder", "peripheral")
RING_FEATURES = ([f"n_{r}" for r in ROLE_NAMES] + [f"frac_{r}" for r in ROLE_NAMES]
                 + ["n_members", "n_edges", "n_txn", "duration_h", "density", "txn_per_member",
                    "longest_path", "has_cycle", "cycle_cover", "bipartite_score", "bipartite_min_side",
                    "max_out_degree", "max_in_degree", "mean_degree", "n_branch_points", "frac_leaf",
                    "n_components", "max_component_frac", "n_pair_components", "n_both", "n_hub_in", "n_hub_out", "n_hub_both",
                    "seed_ratio"])


def _longest_path_and_cycle(G: nx.DiGraph) -> tuple[int, int, float]:
    """(longest directed simple path in edges, has_cycle, fraction of nodes on the longest cycle)."""
    n = G.number_of_nodes()
    if n == 0:
        return 0, 0, 0.0
    cycles = []
    try:
        for c in itertools.islice(nx.simple_cycles(G), 200):
            cycles.append(len(c))
    except Exception:                                   # pragma: no cover
        cycles = []
    has_cycle = 1 if cycles else 0
    cover = (max(cycles) / n) if cycles else 0.0
    if n <= MAX_EXACT_NODES:
        best = 0
        adj = {u: list(G.successors(u)) for u in G.nodes}

        def dfs(u, seen, length):
            nonlocal best
            best = max(best, length)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    dfs(v, seen, length + 1)
                    seen.discard(v)
        for s in G.nodes:
            dfs(s, {s}, 0)
        longest = best
    else:                                               # pragma: no cover  (no AMLworld ring is this big)
        dag = nx.DiGraph((u, v) for u, v in G.edges if u != v)
        longest = nx.dag_longest_path_length(dag) if nx.is_directed_acyclic_graph(dag) else n - 1
    return int(longest), has_cycle, float(cover)


def _bipartite_score(G: nx.DiGraph) -> tuple[float, float]:
    """(fraction of edges crossing the best 2-colouring, smaller side / n_nodes).

    Exact for a connected bipartite graph (the 2-colouring is unique up to swap); otherwise a
    greedy BFS colouring refined by one pass of local improvement."""
    U = G.to_undirected()
    n = U.number_of_nodes()
    m = U.number_of_edges()
    if n == 0 or m == 0:
        return 0.0, 0.0
    color = {}
    for comp in nx.connected_components(U):
        root = min(comp)
        color[root] = 0
        for u, v in nx.bfs_edges(U, root):
            color[v] = 1 - color[u]
    improved = True
    while improved:                                     # local search: flip a node if it helps
        improved = False
        for u in U.nodes:
            same = sum(1 for v in U.neighbors(u) if color[v] == color[u])
            cross = U.degree(u) - same
            if same > cross:
                color[u] = 1 - color[u]
                improved = True
    cross = sum(1 for u, v in U.edges if color[u] != color[v])
    sides = [sum(1 for c in color.values() if c == k) for k in (0, 1)]
    return cross / m, min(sides) / n


def ring_features(edges: pd.DataFrame, roles: dict[int, dict], *, seed_ratio: float | None = None) -> dict:
    """Feature dict (RING_FEATURES order) for one ring."""
    e = dedup_edges(edges)
    members = sorted(set(e["from_id"].tolist()) | set(e["to_id"].tolist()))
    n = len(members)
    G = nx.DiGraph()
    G.add_nodes_from(members)
    for u, v in zip(e["from_id"].tolist(), e["to_id"].tolist()):
        if u != v:
            G.add_edge(u, v)
    n_edges = G.number_of_edges()
    longest, has_cycle, cover = _longest_path_and_cycle(G)
    bip, min_side = _bipartite_score(G)
    out_deg = [d for _, d in G.out_degree()] or [0]
    in_deg = [d for _, d in G.in_degree()] or [0]
    ind, outd = dict(G.in_degree()), dict(G.out_degree())
    comps = list(nx.weakly_connected_components(G)) if n else []
    counts = {r: sum(1 for d in roles.values() if d["role"] == r) for r in ROLE_NAMES}
    dur = (int(e["timestamp"].max()) - int(e["timestamp"].min())) / 3600 if len(e) else 0.0
    if seed_ratio is None:
        seed_ratio = float(e["is_seed"].mean()) if "is_seed" in e.columns and len(e) else 1.0
    f = {f"n_{r}": counts[r] for r in ROLE_NAMES}
    f.update({f"frac_{r}": (counts[r] / n if n else 0.0) for r in ROLE_NAMES})
    f.update({"n_members": n, "n_edges": n_edges, "n_txn": len(e), "duration_h": dur,
              "density": n_edges / (n * (n - 1)) if n > 1 else 0.0, "txn_per_member": len(e) / n if n else 0.0,
              "longest_path": longest, "has_cycle": has_cycle, "cycle_cover": cover,
              "bipartite_score": bip, "bipartite_min_side": min_side,
              "max_out_degree": max(out_deg), "max_in_degree": max(in_deg),
              "mean_degree": (2 * n_edges / n) if n else 0.0,
              "n_branch_points": sum(1 for d in out_deg if d >= 2),
              "frac_leaf": (sum(1 for a in members if G.out_degree(a) + G.in_degree(a) <= 1) / n) if n else 0.0,
              "n_components": len(comps), "max_component_frac": (max(len(c) for c in comps) / n) if comps else 0.0,
              "n_pair_components": sum(1 for c in comps if len(c) == 2),
              "n_both": sum(1 for a in members if ind[a] and outd[a]),
              "n_hub_in": sum(1 for a in members if ind[a] >= 2), "n_hub_out": sum(1 for a in members if outd[a] >= 2),
              "n_hub_both": sum(1 for a in members if ind[a] >= 2 and outd[a] >= 2),
              "seed_ratio": float(seed_ratio)})
    return {k: f[k] for k in RING_FEATURES}


def features_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=RING_FEATURES).astype(float)
