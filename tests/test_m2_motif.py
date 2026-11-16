"""M2 motif search on hand-built graphs (prereg §3 unit tests)."""
from __future__ import annotations

import numpy as np

from evaluation import m2_motif as m2

H = 3600


def g(edges, rank=None):
    src, dst, ts = zip(*edges)
    return m2.Graph(src, dst, ts, rank if rank is not None else np.full(len(edges), 0.5))


def kinds(G, s, T=24 * H, f=3, L=6, ok=None):
    st = {}
    inst = m2.instances(G, s, T, f, L, np.ones(len(G.src), bool) if ok is None else ok, st)
    return inst, st.get("by_shape", {}), st


def test_fan_out_and_fan_in():
    G = g([(1, 2, 10), (1, 3, 20), (1, 4, 30)])
    inst, by, _ = kinds(G, 0)
    assert by.get("FAN_OUT") == 1 and frozenset({0, 1, 2}) in inst
    G = g([(2, 1, 10), (3, 1, 20), (4, 1, 30)])
    _, by, _ = kinds(G, 0)
    assert by.get("FAN_IN") == 1
    _, by, _ = kinds(G, 0, f=5)
    assert "FAN_IN" not in by


def test_scatter_gather_time_order():
    G = g([(1, 2, 10), (1, 3, 11), (2, 9, 20), (3, 9, 21)])
    inst, by, _ = kinds(G, 0, f=9)
    assert by.get("SCATTER_GATHER", 0) >= 1 and frozenset({0, 1, 2, 3}) in inst
    G = g([(1, 2, 30), (1, 3, 31), (2, 9, 20), (3, 9, 21)])          # gather before scatter: violation
    _, by, _ = kinds(G, 0, f=9)
    assert "SCATTER_GATHER" not in by


def test_gather_scatter():
    G = g([(1, 5, 10), (2, 5, 11), (5, 7, 20), (5, 8, 21)])
    inst, by, _ = kinds(G, 0, f=9)
    assert by.get("GATHER_SCATTER", 0) >= 1 and frozenset({0, 1, 2, 3}) in inst


def test_cycle_rotations_and_length():
    G = g([(1, 2, 10), (2, 3, 20), (3, 1, 30)])
    for s in (0, 1, 2):                                              # the seed may be any edge of the cycle
        inst, by, _ = kinds(G, s, f=9)
        assert by.get("CYCLE") == 1 and frozenset({0, 1, 2}) in inst
    G = g([(1, 2, 10), (2, 3, 20), (3, 4, 30), (4, 5, 40), (5, 1, 50)])
    _, by, _ = kinds(G, 0, f=9, L=4)
    assert "CYCLE" not in by
    _, by, _ = kinds(G, 0, f=9, L=6)
    assert by.get("CYCLE") == 1
    G = g([(1, 2, 30), (2, 3, 20), (3, 1, 10)])                      # times run backwards: no rotation is ordered
    _, by, _ = kinds(G, 1, f=9)
    assert "CYCLE" not in by


def test_bipartite_and_stack():
    G = g([(1, 3, 10), (1, 4, 11), (2, 3, 12), (2, 4, 13)])
    inst, by, _ = kinds(G, 0, f=9)
    assert by.get("BIPARTITE") == 1 and frozenset({0, 1, 2, 3}) in inst
    G = g([(1, 3, 10), (1, 4, 11), (2, 3, 12), (2, 4, 13), (3, 5, 20), (3, 6, 21), (4, 5, 22), (4, 6, 23)])
    inst, by, _ = kinds(G, 0, f=9)
    assert by.get("STACK", 0) >= 1 and frozenset(range(8)) in inst


def test_span_violation():
    G = g([(1, 2, 0), (1, 3, 20 * H), (1, 4, 30 * H)])
    _, by, _ = kinds(G, 0, T=24 * H)
    assert "FAN_OUT" not in by                                       # the 30 h edge is outside T = 24 h


def test_hub_cap():
    edges = [(1, 2, 10)] + [(2, 100 + i, 20 + i) for i in range(m2.HUB_DEG + 1)] + [(1, 3, 11), (1, 4, 12)]
    G = g(edges)
    _, by, _ = kinds(G, 0)
    assert "FAN_IN" not in by and "GATHER_SCATTER" not in by          # v = 2 is a hub
    assert by.get("FAN_OUT") == 1


def test_instance_cap_and_gate():
    edges = [(1, 2, 10)] + [(1, 10 + i, 11 + i) for i in range(5)]
    G = g(edges)
    old = m2.MAX_INST
    try:
        m2.MAX_INST = 0
        inst, _, st = kinds(G, 0)
        assert inst == [] and st["inst_cap_bound"] == 1
    finally:
        m2.MAX_INST = old
    ok = np.zeros(len(edges), bool); ok[0] = True                    # score gate: only the seed allowed
    _, by, _ = kinds(G, 0, ok=ok)
    assert by == {}


def test_merge_and_visibility():
    G = g([(1, 2, 10), (2, 3, 11), (7, 8, 12), (8, 9, 13), (3, 1, 14)])
    rings = m2.merge_groups(G, [frozenset({0, 1}), frozenset({1, 4}), frozenset({2, 3})])
    assert sorted(len(a) for a, _ in rings) == [3, 3]
    inst, _, _ = kinds(G, 0)
    assert all(i < len(G.src) for es in inst for i in es)            # only edges of the given split
