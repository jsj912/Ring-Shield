"""Pure-python stand-in for MEGA-GNN's `ports_cpp` pybind11 extension (Step 10 adapter).

The upstream repo ships `ports_cpp.cpython-39-x86_64-linux-gnu.so`, a Linux / Python 3.9 binary;
this project runs Windows / Python 3.12, and building it needs MSVC + pybind11. The extension is
only used by `data_util.assign_ports_with_cpp`, which asks for port numbers -- the same quantity
`models/tgn.py::compute_ports` already computes for our own detector. This module provides the
one entry point their code calls, with identical semantics:

    ports_1, ports_2 = ports_cpp.assign_ports(edges, edge_index, num_nodes)

`edges` is an (M, 3) int array of (src, dst, timestamp); `edge_index` is (2, M). For each edge,
`ports_1` is the index of the SOURCE among the destination's in-neighbours ordered by first
contact time, and `ports_2` the index of the DESTINATION among the source's out-neighbours,
counted the same way -- one number per distinct counterparty, ties broken by time then by the
order the edges appear. Their model code is untouched; only this import is substituted.
"""
from __future__ import annotations

import numpy as np


def _ports_one_side(key: np.ndarray, other: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """Port index of `other` among the counterparties of `key`, ordered by first contact time."""
    n = len(key)
    out = np.zeros(n, dtype=np.int64)
    order = np.lexsort((np.arange(n), ts, other, key))
    k, o = key[order], other[order]
    first = np.ones(n, dtype=bool)
    first[1:] = (k[1:] != k[:-1]) | (o[1:] != o[:-1])      # first edge of each (key, counterparty)
    firsts = order[first]
    fk, fo, fts = key[firsts], other[firsts], ts[firsts]
    rank_order = np.lexsort((fo, fts, fk))                  # per key: counterparties by first contact
    rk, ro = fk[rank_order], fo[rank_order]
    rank = np.zeros(len(rk), dtype=np.int64)
    if len(rk):
        newk = np.ones(len(rk), dtype=bool)
        newk[1:] = rk[1:] != rk[:-1]
        starts = np.flatnonzero(newk)
        idx = np.arange(len(rk))
        base = np.repeat(starts, np.diff(np.r_[starts, len(rk)]))
        rank = idx - base
    lookup = {(int(a), int(b)): int(r) for a, b, r in zip(rk, ro, rank)}
    for i in range(n):
        out[i] = lookup[(int(key[i]), int(other[i]))]
    return out


def assign_ports(edges, edge_index, num_nodes):
    """(ports_1, ports_2) as MEGA-GNN's C++ extension returns them."""
    e = np.asarray(edges, dtype=np.int64)
    src, dst, ts = e[:, 0], e[:, 1], e[:, 2]
    return _ports_one_side(dst, src, ts).tolist(), _ports_one_side(src, dst, ts).tolist()
