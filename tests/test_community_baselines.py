"""T-P3 community baselines on hand-built graphs."""
import networkx as nx
import numpy as np
import pandas as pd

from evaluation.community_baselines import communities, rings_with
from ringshield.rings import RINGS_ORDER


def two_cliques():
    G = nx.Graph()
    a, b = range(0, 5), range(5, 10)
    for grp in (a, b):
        for i in grp:
            for j in grp:
                if i < j:
                    G.add_edge(i, j, w=1.0)
    G.add_edge(4, 5, w=1.0)                                  # one bridge
    return G


def test_louvain_splits_two_cliques():
    parts = communities(two_cliques(), "louvain", 1.0, seed=1)
    assert sorted(map(sorted, parts)) == [list(range(5)), list(range(5, 10))]


def test_components_is_one_community():
    assert len(communities(two_cliques(), "components", None, seed=1)) == 1


def _scored(G):
    rows = [(k, u, v, 1, 1, 100 + k, 0.9) for k, (u, v) in enumerate(G.edges())]
    return pd.DataFrame(rows, columns=["edge_id", "from_id", "to_id", "from_bank", "to_bank", "timestamp", "score_raw"])


def test_rings_schema_and_identity():
    se = _scored(two_cliques())
    flagged = np.ones(len(se), dtype=bool)
    lv = rings_with(se, flagged, None, "louvain", 1.0, 1, "louvain_r1")
    cc1 = rings_with(se, flagged, None, "components", None, 1, "components")
    assert len(lv) == 2 and len(cc1) == 1
    assert sorted(cc1[0].members) == list(range(10))
    assert list(lv[0].to_dict()) == list(RINGS_ORDER)       # validates against the rings contract order
    import ringshield.aggregators.cc as cc
    assert cc.nx is nx                                       # the community step is restored afterwards
