"""Q3: overlapping membership in the truth, and the ring-F1 ceiling of any hard partition.

    python -m evaluation.q3_overlap

For the primary window (test days 8-9) and the whole test period (days 8-17), scope test_visible:
accounts in more than one truth ring, rings sharing >= 1 account with another, and the size of the
shared part.

Ceiling. A hard partition assigns each account to at most one predicted ring, so predicted rings
are pairwise disjoint. A prediction P matches truth ring T at Jaccard >= 0.5 at best when P is a
subset of T with |P| >= |T| / 2, because outsiders only lower the Jaccard. A set S of truth rings can
all be matched at once iff disjoint subsets exist, one per ring T in S, each of size ceil(|T| / 2).
That is a b-matching with account capacity 1 and ring demand ceil(|T| / 2), checked by max-flow.
The ceiling m* is the largest such S, found exactly by search inside each connected cluster of
overlapping rings (non-overlapping rings are always matchable). With precision 1 (output only those
predictions), the best ring-F1 is 2 m* / (n + m*). min_size and observability are ignored here: this
is the bound that overlap alone imposes.
"""
from __future__ import annotations

import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def feasible(rings: list[set]) -> bool:
    """Disjoint subsets of size ceil(|T|/2), one per ring?"""
    G = nx.DiGraph()
    need = 0
    for i, T in enumerate(rings):
        d = (len(T) + 1) // 2
        need += d
        G.add_edge("s", ("r", i), capacity=d)
        for a in T:
            G.add_edge(("r", i), ("a", a), capacity=1)
            G.add_edge(("a", a), "t", capacity=1)
    return nx.maximum_flow_value(G, "s", "t") == need if need else True


def max_simultaneous(cluster: list[set]) -> int:
    """Largest number of rings in the cluster matchable at once (exact, largest-first search)."""
    n = len(cluster)
    if feasible(cluster):
        return n
    assert n <= 20, f"cluster of {n} rings too large for exact search"
    for k in range(n - 1, 0, -1):
        if any(feasible([cluster[i] for i in c]) for c in itertools.combinations(range(n), k)):
            return k
    return 0


def analyse(truth: dict) -> dict:
    owners = defaultdict(set)
    for t, accs in truth.items():
        for a in accs:
            owners[a].add(t)
    multi = {a for a, o in owners.items() if len(o) > 1}
    G = nx.Graph()
    G.add_nodes_from(truth)
    shared_sizes = []
    for a in multi:
        for x, y in itertools.combinations(sorted(owners[a]), 2):
            G.add_edge(x, y)
    for x, y in G.edges:
        shared_sizes.append(len(truth[x] & truth[y]))
    rings_sharing = {t for t in truth if G.degree(t) > 0}
    m = 0
    clusters = []
    for comp in nx.connected_components(G):
        comp = sorted(comp)
        k = max_simultaneous([truth[t] for t in comp])
        m += k
        if len(comp) > 1:
            clusters.append({"rings": len(comp), "matchable": k})
    n = len(truth)
    ss = pd.Series(shared_sizes, dtype=float)
    return {"n_rings": n, "n_accounts": len(owners), "accounts_in_gt1_ring": len(multi),
            "max_rings_per_account": max((len(o) for o in owners.values()), default=0),
            "rings_sharing_an_account": len(rings_sharing), "overlapping_pairs": G.number_of_edges(),
            "shared_part_size": {"median": ss.median(), "mean": ss.mean(), "max": ss.max()} if len(ss) else None,
            "shared_share_of_smaller_ring_median": float(pd.Series(
                [len(truth[x] & truth[y]) / min(len(truth[x]), len(truth[y])) for x, y in G.edges]).median()) if G.number_of_edges() else None,
            "overlap_clusters": clusters, "max_matchable_m": m,
            "ceiling_ring_recall": m / n, "ceiling_ring_f1": 2 * m / (n + m)}


def main():
    from preprocessing.account_bank import load_paths
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    sys.stdout.reconfigure(encoding="utf-8")
    gt = load_paths()["processed_dir"] / "amlworld_ring_ground_truth.parquet"
    W = load_windows()
    out, rows = {}, []
    for name in ("primary", "whole"):
        truth, _ = load_ground_truth(gt, *W[name].bounds, "test_visible", verbose=False)
        r = analyse(truth)
        out[name] = r
        rows.append({"window": name, **{k: v for k, v in r.items() if k not in ("overlap_clusters", "shared_part_size")},
                     **{f"shared_{k}": v for k, v in (r["shared_part_size"] or {}).items()}})
        print(name, json.dumps(r, default=float))
    pre = REPO_ROOT / "results/tables/q3_overlap"
    pd.DataFrame(rows).to_csv(f"{pre}.csv", index=False)
    Path(f"{pre}.json").write_text(json.dumps({"definitions": __doc__, **out}, indent=2, default=float), encoding="utf-8")


if __name__ == "__main__":
    main()
