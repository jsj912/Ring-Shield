"""
Graph Feature Preprocessor (GFP) — parallelized per-edge pattern counting.
Uses all CPU cores via multiprocessing for the heavy per-transaction loop.

For each transaction e = (u → v, timestamp t):
    fan_out:          # txns u sends in [t-Δ, t+Δ]
    fan_in:           # txns v receives in [t-Δ, t+Δ]
    deg_out_src:      cumulative out-degree of u at time t
    deg_in_src:       cumulative in-degree of u at time t
    deg_out_dst:      cumulative out-degree of v at time t
    deg_in_dst:       cumulative in-degree of v at time t
    scatter_gather:   # 2-hop paths u→w→v with ts < t
    gather_scatter:   # 2-hop paths w→src, dst→w with ts < t
    temporal_cycle:   can we reach u from v via edges after t? (bounded BFS)
    cycle_length:     shortest such cycle length

Usage:
    python graph/motif_features.py \
        --data-dir data/processed \
        --out-dir data/processed \
        --window 86400 \
        --max-cycle-hops 5 \
        --workers 0        # 0 = use all CPU cores

Produces:
    data/processed/amlworld_gfp_features_{train,val,test}.parquet
"""

import argparse
import multiprocessing as mp
import os
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


# ============================================================================
# Global state for worker processes (set via initializer, avoids pickle overhead)
# ============================================================================
_ADJ_OUT = None       # dict: node -> sorted list of (timestamp, target)
_ADJ_IN = None        # dict: node -> sorted list of (timestamp, source)
_ADJ_OUT_TS = None    # dict: node -> numpy array of timestamps (out edges)
_ADJ_IN_TS = None     # dict: node -> numpy array of timestamps (in edges)
_SCC_NODES = None     # set of nodes in non-trivial SCCs
_WINDOW = None
_MAX_HOPS = None


def _init_worker(adj_out, adj_in, adj_out_ts, adj_in_ts, scc_nodes, window, max_hops):
    global _ADJ_OUT, _ADJ_IN, _ADJ_OUT_TS, _ADJ_IN_TS, _SCC_NODES, _WINDOW, _MAX_HOPS
    _ADJ_OUT = adj_out
    _ADJ_IN = adj_in
    _ADJ_OUT_TS = adj_out_ts
    _ADJ_IN_TS = adj_in_ts
    _SCC_NODES = scc_nodes
    _WINDOW = window
    _MAX_HOPS = max_hops


# ============================================================================
# Per-edge feature computation (runs in worker processes)
# ============================================================================
def _fan_out_count(node, t):
    ts_arr = _ADJ_OUT_TS.get(node)
    if ts_arr is None:
        return 0
    lo = bisect_left(ts_arr, t - _WINDOW)
    hi = bisect_left(ts_arr, t)  # strictly before t (backward only)
    return hi - lo


def _fan_in_count(node, t):
    ts_arr = _ADJ_IN_TS.get(node)
    if ts_arr is None:
        return 0
    lo = bisect_left(ts_arr, t - _WINDOW)
    hi = bisect_left(ts_arr, t)  # strictly before t (backward only)
    return hi - lo


def _cum_out_degree(node, t):
    ts_arr = _ADJ_OUT_TS.get(node)
    if ts_arr is None:
        return 0
    return bisect_right(ts_arr, t)


def _cum_in_degree(node, t):
    ts_arr = _ADJ_IN_TS.get(node)
    if ts_arr is None:
        return 0
    return bisect_right(ts_arr, t)


def _out_neighbors_before(node, t):
    edges = _ADJ_OUT.get(node)
    if not edges:
        return set()
    ts_arr = _ADJ_OUT_TS[node]
    hi = bisect_left(ts_arr, t)
    return {edges[i][1] for i in range(hi)}


def _in_neighbors_before(node, t):
    edges = _ADJ_IN.get(node)
    if not edges:
        return set()
    ts_arr = _ADJ_IN_TS[node]
    hi = bisect_left(ts_arr, t)
    return {edges[i][1] for i in range(hi)}


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


def _temporal_cycle(src, dst, t):
    """BFS from dst to find path back to src using edges after t (bounded hops)."""
    if src not in _SCC_NODES or dst not in _SCC_NODES:
        return 0, 0

    visited = {dst}
    queue = [(dst, t, 1)]

    while queue:
        current, min_ts, hops = queue.pop(0)
        if hops > _MAX_HOPS:
            continue

        edges = _ADJ_OUT.get(current)
        if not edges:
            continue
        ts_arr = _ADJ_OUT_TS[current]
        lo = bisect_right(ts_arr, min_ts)

        for idx in range(lo, len(edges)):
            edge_ts, neighbor = edges[idx]
            if neighbor == src:
                return 1, hops
            if neighbor not in visited and hops < _MAX_HOPS:
                visited.add(neighbor)
                queue.append((neighbor, edge_ts, hops + 1))

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

        cyc, cyc_len = _temporal_cycle(src, dst, t)
        results[i, 8] = cyc
        results[i, 9] = cyc_len

    return chunk_idx, results


# ============================================================================
# Build adjacency structures
# ============================================================================
def build_adjacency(edges_df):
    """Build sorted adjacency dicts from edge DataFrame."""
    adj_out = defaultdict(list)
    adj_in = defaultdict(list)

    for _, row in edges_df.iterrows():
        src, dst, ts = int(row["from_id"]), int(row["to_id"]), int(row["Timestamp"])
        adj_out[src].append((ts, dst))
        adj_in[dst].append((ts, src))

    # Sort by timestamp
    adj_out_sorted = {}
    adj_out_ts = {}
    for node, edges in adj_out.items():
        edges.sort()
        adj_out_sorted[node] = edges
        adj_out_ts[node] = np.array([e[0] for e in edges], dtype=np.int64)

    adj_in_sorted = {}
    adj_in_ts = {}
    for node, edges in adj_in.items():
        edges.sort()
        adj_in_sorted[node] = edges
        adj_in_ts[node] = np.array([e[0] for e in edges], dtype=np.int64)

    return adj_out_sorted, adj_in_sorted, adj_out_ts, adj_in_ts


def build_scc_set(adj_out):
    """Find nodes in non-trivial SCCs."""
    G = nx.DiGraph()
    for src, edges in adj_out.items():
        for ts, dst in edges:
            G.add_edge(src, dst)
    scc_nodes = set()
    for scc in nx.strongly_connected_components(G):
        if len(scc) > 1:
            scc_nodes |= scc
    n_scc = sum(1 for scc in nx.strongly_connected_components(G) if len(scc) > 1)
    print(f"  {len(scc_nodes)} nodes in {n_scc} non-trivial SCCs")
    del G
    return scc_nodes


# ============================================================================
# Main
# ============================================================================
def compute_features_parallel(df, adj_out, adj_in, adj_out_ts, adj_in_ts,
                               scc_nodes, window, max_hops, n_workers):
    """Parallel GFP feature computation using multiprocessing Pool."""
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
    with mp.Pool(
        processes=n_workers,
        initializer=_init_worker,
        initargs=(adj_out, adj_in, adj_out_ts, adj_in_ts, scc_nodes, window, max_hops),
    ) as pool:
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
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of worker processes (0 = all cores)")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    n_workers = args.workers if args.workers > 0 else mp.cpu_count()
    print(f"Using {n_workers} worker processes (CPU cores: {mp.cpu_count()})")

    # --- Build temporal graph from ALL edges (incremental adjacency) ---
    # Each transaction's features only look BACKWARD (timestamp < t), so
    # including val/test edges in the adjacency is NOT leakage — a transaction
    # at time t never sees edges after t. This matches IBM's incremental GFP
    # and ensures fan_in/fan_out are nonzero for val/test transactions.
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
    adj_out, adj_in, adj_out_ts, adj_in_ts = build_adjacency(all_edges)
    print(f"  Done in {time.time()-t0:.1f}s "
          f"({len(adj_out)} out-nodes, {len(adj_in)} in-nodes)")

    print("Finding SCC nodes for cycle detection...")
    t0 = time.time()
    scc_nodes = build_scc_set(adj_out)
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
            scc_nodes, args.window, args.max_cycle_hops, n_workers
        )

        gfp_df["EdgeID"] = df["EdgeID"].values

        out_path = args.out_dir / f"amlworld_gfp_features_{split}.parquet"
        gfp_df.to_parquet(out_path, index=False)
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