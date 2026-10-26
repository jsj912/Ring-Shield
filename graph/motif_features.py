"""
Graph Feature Preprocessor (GFP) — parallelized per-edge pattern counting.
Uses all CPU cores via multiprocessing for the heavy per-transaction loop.

For each transaction e = (u → v, timestamp t) -- every feature reads only edges with
timestamp < t (or <= t for the cumulative degrees, which count e itself):
    fan_out:          # txns u sends in [t-Δ, t)          (trailing window, strictly before t)
    fan_in:           # txns v receives in [t-Δ, t)
    deg_out_src:      # txns u has sent up to and including t
    deg_in_src:       # txns u has received up to and including t
    deg_out_dst:      # txns v has sent up to and including t
    deg_in_dst:       # txns v has received up to and including t
    scatter_gather:   # 2-hop paths u→w→v with ts < t
    gather_scatter:   # 2-hop paths w→u, v→w with ts < t
    temporal_cycle:   closes_cycle -- 1 if a temporal path v → … → u exists using only edges
                      with timestamp < t, strictly increasing along the path, at most
                      --max-cycle-hops hops, and no edge older than t - LOOKBACK
                      (--lookback-days, default 14). Backward BFS from u over incoming
                      edges with decreasing timestamps. Column name kept for compatibility.
    cycle_length:     number of hops of the shortest such path, else 0

Step 3b-z (2026-09-17): temporal_cycle / cycle_length used to be a FORWARD search over
edges after t with no time bound (see docs/FEATURE_CAUSALITY.md); the SCC gate that went
with it was computed on the whole static graph and is gone. The look-back bound is written
into the parquet schema metadata (key b"gfp") together with the window and hop limit.

Usage:
    python graph/motif_features.py \
        --data-dir data/processed \
        --out-dir data/processed \
        --window 86400 \
        --max-cycle-hops 5 \
        --lookback-days 14 \
        --workers 0        # 0 = use all CPU cores

Produces:
    data/processed/amlworld_gfp_features_{train,val,test}.parquet   (EdgeID-keyed)
"""

import argparse
import json
import multiprocessing as mp
import os
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

LOOKBACK_DAYS_DEFAULT = 14


# ============================================================================
# Global state for worker processes (set via initializer, avoids pickle overhead)
# ============================================================================
_ADJ_OUT = None       # dict: node -> sorted list of (timestamp, target)
_ADJ_IN = None        # dict: node -> sorted list of (timestamp, source)
_ADJ_OUT_TS = None    # dict: node -> numpy array of timestamps (out edges)
_ADJ_IN_TS = None     # dict: node -> numpy array of timestamps (in edges)
_WINDOW = None
_MAX_HOPS = None
_LOOKBACK = None      # seconds; closes_cycle never reads an edge older than t - _LOOKBACK

# Step V3.2b: CSR mode. `_CSR` is None in the legacy dict mode (which `tests/test_gfp_causality.py`
# drives directly by assigning the four globals above, and which is therefore left untouched);
# when it is set, the kernels read memory-mapped CSR arrays instead. One implementation of every
# feature serves both modes, so the two cannot drift apart.
#
# Why: the dict mode hands each Pool worker its own pickled copy of the adjacency through
# `initargs`. On HI-Medium that is 63.8 M Python tuples over 2.08 M nodes -- ~8.5 GB per worker,
# measured -- so 36 workers need ~170 GB and simply never start computing (2 % CPU for 47
# minutes). The CSR arrays are ~1 GB total, are written once to .npy, and each worker opens them
# with mmap_mode="r": the OS keeps ONE physical copy in the page cache and every worker shares it.
_CSR = None           # dict of memory-mapped arrays: {out,in}_{indptr,ts,oth}
CSR_FILES = ("out_indptr", "out_ts", "out_oth", "in_indptr", "in_ts", "in_oth")


def _init_worker(adj_out, adj_in, adj_out_ts, adj_in_ts, window, max_hops, lookback_s):
    global _ADJ_OUT, _ADJ_IN, _ADJ_OUT_TS, _ADJ_IN_TS, _WINDOW, _MAX_HOPS, _LOOKBACK
    _ADJ_OUT = adj_out
    _ADJ_IN = adj_in
    _ADJ_OUT_TS = adj_out_ts
    _ADJ_IN_TS = adj_in_ts
    _WINDOW = window
    _MAX_HOPS = max_hops
    _LOOKBACK = lookback_s


def _init_worker_csr(paths, window, max_hops, lookback_s):
    """Worker initializer for CSR mode: only file paths cross the process boundary."""
    global _CSR, _WINDOW, _MAX_HOPS, _LOOKBACK
    _CSR = {k: np.load(paths[k], mmap_mode="r") for k in CSR_FILES}
    _WINDOW = window
    _MAX_HOPS = max_hops
    _LOOKBACK = lookback_s


def _seg(side: str, node):
    """(lo, hi) offsets of `node`'s edges in the CSR arrays; (0, 0) when it has none."""
    ip = _CSR[side + "_indptr"]
    n = int(node)
    if n < 0 or n + 1 >= len(ip):
        return 0, 0
    return int(ip[n]), int(ip[n + 1])


# ============================================================================
# Per-edge feature computation (runs in worker processes)
# ============================================================================
def _window_count(side, node, t):
    """# edges at `node` with timestamp in [t - window, t). `bisect_left` and
    `np.searchsorted(side="left")` agree exactly on a sorted array."""
    if _CSR is None:
        ts_arr = (_ADJ_OUT_TS if side == "out" else _ADJ_IN_TS).get(node)
        if ts_arr is None:
            return 0
        return bisect_left(ts_arr, t) - bisect_left(ts_arr, t - _WINDOW)
    a, b = _seg(side, node)
    if a == b:
        return 0
    seg = _CSR[side + "_ts"][a:b]
    return int(np.searchsorted(seg, t, "left")) - int(np.searchsorted(seg, t - _WINDOW, "left"))


def _cum_degree(side, node, t):
    """# edges at `node` up to and including t. `bisect_right` == searchsorted(side="right")."""
    if _CSR is None:
        ts_arr = (_ADJ_OUT_TS if side == "out" else _ADJ_IN_TS).get(node)
        if ts_arr is None:
            return 0
        return bisect_right(ts_arr, t)
    a, b = _seg(side, node)
    if a == b:
        return 0
    return int(np.searchsorted(_CSR[side + "_ts"][a:b], t, "right"))


def _neighbors_before(side, node, t):
    """Counterparties of `node`'s edges strictly before t, as a set."""
    if _CSR is None:
        adj = _ADJ_OUT if side == "out" else _ADJ_IN
        edges = adj.get(node)
        if not edges:
            return set()
        ts_arr = (_ADJ_OUT_TS if side == "out" else _ADJ_IN_TS)[node]
        hi = bisect_left(ts_arr, t)
        return {edges[i][1] for i in range(hi)}
    a, b = _seg(side, node)
    if a == b:
        return set()
    hi = int(np.searchsorted(_CSR[side + "_ts"][a:b], t, "left"))
    if hi == 0:
        return set()
    return set(_CSR[side + "_oth"][a:a + hi].tolist())


def _fan_out_count(node, t):
    return _window_count("out", node, t)


def _fan_in_count(node, t):
    return _window_count("in", node, t)


def _cum_out_degree(node, t):
    return _cum_degree("out", node, t)


def _cum_in_degree(node, t):
    return _cum_degree("in", node, t)


def _out_neighbors_before(node, t):
    return _neighbors_before("out", node, t)


def _in_neighbors_before(node, t):
    return _neighbors_before("in", node, t)


def _scatter_gather(src, dst, t):
    """scatter-gather: src→w→dst (shared intermediaries before t)"""
    src_sent_to = _out_neighbors_before(src, t)
    dst_recv_from = _in_neighbors_before(dst, t)
    sg = len(src_sent_to & dst_recv_from)

    """gather-scatter: w→src, dst→w (reverse)"""
    src_recv_from = _in_neighbors_before(src, t)
    dst_sent_to = _out_neighbors_before(dst, t)
    gs = len(src_recv_from & dst_sent_to)

    return sg, gs


def _closes_cycle(src, dst, t):
    """(closes_cycle, cycle_length) for edge src -> dst at time t.

    Is there a temporal path dst -> ... -> src whose edges all have timestamp < t, strictly
    increasing along the path, with at most _MAX_HOPS edges and none older than
    t - _LOOKBACK?  Backward BFS from src: a state (node, bound) means "node is reached by a
    path whose earliest edge is at `bound`"; it expands over the incoming edges of node with
    timestamp in [t - _LOOKBACK, bound), newest first. Level k of the BFS holds paths of k
    edges, so the first level at which dst appears is the shortest cycle. A node is
    re-expanded only when reached with a larger bound (a larger bound admits a superset of
    continuations), which keeps the search exact and bounded.
    """
    t_lo = t - _LOOKBACK
    best = {src: t}
    frontier = {src: t}
    for hops in range(1, _MAX_HOPS + 1):
        nxt = {}
        for node, bound in frontier.items():
            # the in-edges of `node` with timestamp in [t_lo, bound), newest first
            if _CSR is None:
                ts_arr = _ADJ_IN_TS.get(node)
                if ts_arr is None:
                    continue
                edges = _ADJ_IN[node]
                hi = bisect_left(ts_arr, bound)   # ts < bound
                lo = bisect_left(ts_arr, t_lo)    # ts >= t - lookback
                seg = ((edges[idx][0], edges[idx][1]) for idx in range(hi - 1, lo - 1, -1))
            else:
                a, b = _seg("in", node)
                if a == b:
                    continue
                seg_ts = _CSR["in_ts"][a:b]
                hi = int(np.searchsorted(seg_ts, bound, "left"))
                lo = int(np.searchsorted(seg_ts, t_lo, "left"))
                if hi <= lo:
                    continue
                # materialise the sub-range once, as Python ints, then walk it newest-first --
                # element-wise indexing of a memmap in this loop would dominate the runtime
                tl = seg_ts[lo:hi].tolist()
                wl = _CSR["in_oth"][a + lo:a + hi].tolist()
                seg = ((tl[j], wl[j]) for j in range(len(tl) - 1, -1, -1))
            for edge_ts, w in seg:
                if w == dst:
                    return 1, hops
                if hops < _MAX_HOPS and edge_ts > best.get(w, -1):
                    best[w] = edge_ts
                    nxt[w] = edge_ts
        if not nxt:
            break
        frontier = nxt
    return 0, 0


def _process_chunk(chunk_data):
    """Process a chunk of transactions, return feature arrays."""
    from_ids, to_ids, timestamps, chunk_idx = chunk_data
    n = len(from_ids)

    results = np.zeros((n, 10), dtype=np.int32)

    for i in range(n):
        src = from_ids[i]
        dst = to_ids[i]
        t = timestamps[i]

        results[i, 0] = _fan_out_count(src, t)
        results[i, 1] = _fan_in_count(dst, t)
        results[i, 2] = _cum_out_degree(src, t)
        results[i, 3] = _cum_in_degree(src, t)
        results[i, 4] = _cum_out_degree(dst, t)
        results[i, 5] = _cum_in_degree(dst, t)

        sg, gs = _scatter_gather(src, dst, t)
        results[i, 6] = sg
        results[i, 7] = gs

        cyc, cyc_len = _closes_cycle(src, dst, t)
        results[i, 8] = cyc
        results[i, 9] = cyc_len

    return chunk_idx, results


# ============================================================================
# Build adjacency structures
# ============================================================================
def build_adjacency(edges_df, legacy: bool = False):
    """Build sorted adjacency dicts from an edge DataFrame.

    Step V3.2: vectorised. The original walked the frame with `iterrows`, which is ~10 minutes on
    HI-Small's 5.1 M edges and roughly an hour on HI-Medium's 31.9 M. Each node's list was then
    sorted with `list.sort()` over `(ts, other)` tuples, so a single `lexsort` keyed
    (node, ts, other) puts every node's edges in exactly that order, and the per-node lists are
    contiguous slices of it. The output is identical in type and content -- dicts of
    `node -> [(ts, other), ...]` plus `node -> np.int64 array of ts` -- so no caller changes.
    `legacy=True` keeps the old path; the two are asserted equal in `--verify-adjacency`.
    """
    if legacy:
        adj_out = defaultdict(list)
        adj_in = defaultdict(list)
        for _, row in edges_df.iterrows():
            src, dst, ts = int(row["from_id"]), int(row["to_id"]), int(row["Timestamp"])
            adj_out[src].append((ts, dst))
            adj_in[dst].append((ts, src))
        adj_out_sorted, adj_out_ts = {}, {}
        for node, edges in adj_out.items():
            edges.sort()
            adj_out_sorted[node] = edges
            adj_out_ts[node] = np.array([e[0] for e in edges], dtype=np.int64)
        adj_in_sorted, adj_in_ts = {}, {}
        for node, edges in adj_in.items():
            edges.sort()
            adj_in_sorted[node] = edges
            adj_in_ts[node] = np.array([e[0] for e in edges], dtype=np.int64)
        return adj_out_sorted, adj_in_sorted, adj_out_ts, adj_in_ts

    src = edges_df["from_id"].to_numpy(np.int64)
    dst = edges_df["to_id"].to_numpy(np.int64)
    ts = edges_df["Timestamp"].to_numpy(np.int64)

    def side(key, other):
        # primary key = node, then ts, then the counterparty -- the order list.sort() gives
        order = np.lexsort((other, ts, key))
        k, t2, o2 = key[order], ts[order], other[order]
        if len(k) == 0:
            return {}, {}
        cuts = np.flatnonzero(np.diff(k)) + 1
        starts = np.concatenate(([0], cuts))
        ends = np.concatenate((cuts, [len(k)]))
        nodes = k[starts]
        adj, adj_ts = {}, {}
        for n, s, e in zip(nodes.tolist(), starts.tolist(), ends.tolist()):
            tt = t2[s:e]
            adj[n] = list(zip(tt.tolist(), o2[s:e].tolist()))
            adj_ts[n] = tt
        return adj, adj_ts

    adj_out_sorted, adj_out_ts = side(src, dst)
    adj_in_sorted, adj_in_ts = side(dst, src)
    return adj_out_sorted, adj_in_sorted, adj_out_ts, adj_in_ts


def build_adjacency_csr(edges_df, out_dir: Path, prefix: str = "gfp_adj") -> dict:
    """Write the adjacency as CSR `.npy` files and return {name: path}.

    Per direction: `indptr` (n_nodes + 1 offsets), `ts` and `oth` (one entry per edge, grouped by
    node and sorted within a node by (ts, counterparty) -- the same order `list.sort()` gives the
    dict form, so the two are interchangeable). Workers memory-map these read-only, so the whole
    pool shares one physical copy instead of one pickled copy each.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    src = edges_df["from_id"].to_numpy(np.int64)
    dst = edges_df["to_id"].to_numpy(np.int64)
    ts = edges_df["Timestamp"].to_numpy(np.int64)
    n_nodes = int(max(src.max(initial=0), dst.max(initial=0))) + 1
    paths = {}
    for name, key, other in (("out", src, dst), ("in", dst, src)):
        order = np.lexsort((other, ts, key))
        indptr = np.zeros(n_nodes + 1, dtype=np.int64)
        np.add.at(indptr, key + 1, 1)
        np.cumsum(indptr, out=indptr)
        for suffix, arr in (("indptr", indptr), ("ts", ts[order]), ("oth", other[order])):
            p = out_dir / f"{prefix}_{name}_{suffix}.npy"
            np.save(p, np.ascontiguousarray(arr))
            paths[f"{name}_{suffix}"] = str(p)
    total = sum(Path(p).stat().st_size for p in paths.values())
    print(f"  CSR adjacency: {n_nodes:,} nodes, {len(ts):,} edges, "
          f"{total / 1e9:.2f} GB on disk -> {out_dir}", flush=True)
    return paths


# ============================================================================
# Main
# ============================================================================
def compute_features_parallel(df, adj_out, adj_in, adj_out_ts, adj_in_ts,
                               window, max_hops, lookback_s, n_workers, csr_paths=None):
    """Parallel GFP feature computation using a multiprocessing Pool.

    With `csr_paths`, workers are initialised in CSR mode and only the file paths are pickled;
    the adjacency itself is memory-mapped and shared. Without it, the legacy dict path is used,
    which pickles a full copy of the adjacency into every worker and does not scale past
    HI-Small (see the note on `_CSR`).
    """
    n = len(df)
    from_ids = df["from_id"].values.astype(np.int64)
    to_ids = df["to_id"].values.astype(np.int64)
    timestamps = df["Timestamp"].values.astype(np.int64)

    # Split into chunks for workers
    chunk_size = max(n // (n_workers * 4), 1000)  # ~4 chunks per worker for load balancing
    chunks = []
    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        chunks.append((
            from_ids[start:end],
            to_ids[start:end],
            timestamps[start:end],
            start,  # chunk index for reassembly
        ))

    print(f"    {n} transactions → {len(chunks)} chunks across {n_workers} workers")

    results_array = np.zeros((n, 10), dtype=np.int32)
    completed = 0

    t0 = time.time()
    if csr_paths is not None:
        init, args = _init_worker_csr, (csr_paths, window, max_hops, lookback_s)
    else:
        init = _init_worker
        args = (adj_out, adj_in, adj_out_ts, adj_in_ts, window, max_hops, lookback_s)
    with mp.Pool(processes=n_workers, initializer=init, initargs=args) as pool:
        for chunk_idx, chunk_result in pool.imap_unordered(_process_chunk, chunks):
            chunk_len = len(chunk_result)
            results_array[chunk_idx:chunk_idx + chunk_len] = chunk_result
            completed += chunk_len
            elapsed = time.time() - t0
            rate = completed / elapsed
            eta = (n - completed) / rate / 60 if rate > 0 else 0
            pct = completed / n * 100
            print(f"    {pct:5.1f}%  {completed}/{n}  "
                  f"{rate:.0f} txn/s  ETA: {eta:.1f}min", end="\r")

    print(f"\n    Done: {n} transactions in {time.time()-t0:.1f}s "
          f"({n/(time.time()-t0):.0f} txn/s)")

    col_names = ["fan_out", "fan_in", "deg_out_src", "deg_in_src",
                 "deg_out_dst", "deg_in_dst", "scatter_gather",
                 "gather_scatter", "temporal_cycle", "cycle_length"]
    return pd.DataFrame(results_array, columns=col_names)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--window", type=int, default=86400,
                        help="Time window in seconds for fan-in/out (default: 1 day)")
    parser.add_argument("--max-cycle-hops", type=int, default=5,
                        help="Max BFS depth for temporal cycles (default: 5)")
    parser.add_argument("--lookback-days", type=float, default=LOOKBACK_DAYS_DEFAULT,
                        help="closes_cycle never reads an edge older than t - this (default: 14 days)")
    parser.add_argument("--legacy-adjacency", action="store_true",
                        help="use the pre-V3.2b dict adjacency, pickled into every worker. Kept "
                             "for comparison only; it needs ~8.5 GB per worker on HI-Medium and "
                             "does not finish.")
    parser.add_argument("--adj-dir", type=Path, default=None,
                        help="where to write the CSR .npy files (default: --out-dir)")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of worker processes (0 = all cores)")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    n_workers = args.workers if args.workers > 0 else mp.cpu_count()
    lookback_s = int(round(args.lookback_days * 86400))
    print(f"Using {n_workers} worker processes (CPU cores: {mp.cpu_count()})")
    print(f"fan window {args.window}s | closes_cycle: <= {args.max_cycle_hops} hops, look-back {lookback_s}s "
          f"({args.lookback_days} d)")

    # --- Build temporal graph from ALL edges (incremental adjacency) ---
    # Every feature reads only edges with timestamp < t (<= t for the cumulative
    # degrees) through bisect on the per-account sorted arrays, so including
    # val/test edges in the adjacency is not leakage -- a transaction at time t
    # never sees edges after t (verified: tests/test_gfp_causality.py,
    # tests/audit_feature_causality.py). This matches the incremental GFP
    # protocol and keeps fan_in/fan_out nonzero for val/test transactions.
    print("\nLoading ALL edges (train + val + test) for incremental adjacency...")
    edge_frames = []
    for split in ["train", "val", "test"]:
        edge_path = args.data_dir / f"amlworld_edges_{split}.parquet"
        if edge_path.exists():
            df_e = pd.read_parquet(edge_path)
            edge_frames.append(df_e)
            print(f"  {split}: {len(df_e)} edges")
    all_edges = pd.concat(edge_frames, ignore_index=True)
    print(f"  Total: {len(all_edges)} edges")

    print("Building temporal adjacency structures...")
    t0 = time.time()
    adj_out = adj_in = adj_out_ts = adj_in_ts = None
    csr_paths = None
    if args.legacy_adjacency:
        adj_out, adj_in, adj_out_ts, adj_in_ts = build_adjacency(all_edges)
        print(f"  Done in {time.time()-t0:.1f}s "
              f"({len(adj_out)} out-nodes, {len(adj_in)} in-nodes)")
    else:
        csr_paths = build_adjacency_csr(all_edges, args.adj_dir or args.out_dir)
        print(f"  Done in {time.time()-t0:.1f}s")

    # --- Compute GFP features for each split ---
    for split in ["train", "val", "test"]:
        split_path = args.data_dir / f"amlworld_{split}.parquet"
        if not split_path.exists():
            print(f"\nSkipping {split} (not found)")
            continue

        print(f"\n{'='*60}")
        print(f"Computing GFP features for {split} split...")
        df = pd.read_parquet(split_path)
        print(f"  {len(df)} transactions")

        gfp_df = compute_features_parallel(
            df, adj_out, adj_in, adj_out_ts, adj_in_ts,
            args.window, args.max_cycle_hops, lookback_s, n_workers, csr_paths=csr_paths
        )

        gfp_df["EdgeID"] = df["EdgeID"].values

        out_path = args.out_dir / f"amlworld_gfp_features_{split}.parquet"
        table = pa.Table.from_pandas(gfp_df, preserve_index=False)
        meta = dict(table.schema.metadata or {})
        meta[b"gfp"] = json.dumps({
            "window_s": args.window, "max_cycle_hops": args.max_cycle_hops,
            "cycle_lookback_s": lookback_s, "cycle_lookback_days": args.lookback_days,
            "cycle_definition": "closes_cycle: temporal path dst->...->src, all edges < t, strictly "
                                "increasing, <= max_cycle_hops hops, none older than t - lookback "
                                "(backward BFS over incoming edges); cycle_length = shortest such path",
            "trailing": True, "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }).encode()
        pq.write_table(table.replace_schema_metadata(meta), out_path)
        print(f"  Saved to {out_path}")

        print(f"  Feature stats:")
        for col in gfp_df.columns:
            if col == "EdgeID":
                continue
            vals = gfp_df[col]
            print(f"    {col}: mean={vals.mean():.2f}, max={vals.max()}, "
                  f"nonzero={(vals != 0).sum()}")

    print(f"\n{'='*60}")
    print("All GFP features computed.")
    print(f"Next: python baselines/gfp_xgboost_aml.py --data-dir data/processed "
          f"--out-dir experiments/E5b_gfp_xgboost --n-trials 50")


if __name__ == "__main__":
    main()