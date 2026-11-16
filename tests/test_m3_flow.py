"""M3 flow-following on hand-built graphs."""
from __future__ import annotations

import numpy as np

from evaluation import m3_flow as m3

H = 3600
FX = {"rate_to_ccy0": {0: 1.0, 1: 2.0}}


def fg(edges):
    """edges: (src, dst, ts, sent, received, ccy_sent, ccy_received)"""
    c = list(zip(*edges))
    return m3.FlowGraph(c[0], c[1], c[2], c[3], c[4], c[5], c[6], FX)


def test_forward_and_backward_match():
    G = fg([(1, 2, 10, 100, 100, 0, 0), (2, 3, 20, 99, 99, 0, 0), (9, 1, 5, 101, 101, 0, 0), (2, 4, 21, 50, 50, 0, 0)])
    got = m3.follow(G, {0}, 0.05, 24 * H, 1)
    assert got == {0, 1, 2}                      # 2->3 forward (99 vs 100), 9->1 backward; 2->4 amount mismatch


def test_delay_and_order():
    G = fg([(1, 2, 10, 100, 100, 0, 0), (2, 3, 10 + 25 * H, 100, 100, 0, 0), (2, 4, 5, 100, 100, 0, 0)])
    assert m3.follow(G, {0}, 0.05, 24 * H, 1) == {0}      # too late; and 2->4 is before the inflow


def test_hops_and_currency():
    G = fg([(1, 2, 10, 100, 100, 0, 0), (2, 3, 20, 100, 100, 0, 0), (3, 4, 30, 100, 100, 0, 0)])
    assert m3.follow(G, {0}, 0.01, 24 * H, 1) == {0, 1}
    assert m3.follow(G, {0}, 0.01, 24 * H, 2) == {0, 1, 2}
    G = fg([(1, 2, 10, 100, 100, 0, 0), (2, 3, 20, 50, 50, 1, 1), (2, 5, 21, 100, 100, 7, 7)])
    assert m3.follow(G, {0}, 0.01, 24 * H, 1) == {0, 1}   # 50 in ccy 1 = 100 in hub; ccy 7 unconvertible


def test_hub_not_traversed():
    edges = [(1, 2, 10, 100, 100, 0, 0), (2, 3, 20, 100, 100, 0, 0)] + \
            [(2, 100 + i, 30 + i, 1, 1, 0, 0) for i in range(m3.Graph.__init__.__defaults__ and 101 or 101)]
    G = fg(edges)
    assert m3.follow(G, {0}, 0.05, 24 * H, 1) == {0}


def test_b0_groups_min_size():
    G = fg([(1, 2, 10, 1, 1, 0, 0), (2, 3, 11, 1, 1, 0, 0), (7, 8, 12, 1, 1, 0, 0)])
    groups = m3.b0_groups(G, np.array([0, 1, 2]))
    assert groups == [frozenset({0, 1})]
