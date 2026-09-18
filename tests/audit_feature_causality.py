"""Step 3b-y (3): empirical causality check of the 10 GFP edge features.

    python tests/audit_feature_causality.py                 # 10,000 random test edges, seed 1
    python tests/audit_feature_causality.py --n 500 --dry-run

Independent of the code reading in docs/FEATURE_CAUSALITY.md: the production feature
functions of graph/motif_features.py are called unchanged, twice per sampled test edge
e = (u -> v, t_e):

    full        on the adjacency the production script builds (train + val + test edges)
    restricted  on the same adjacency truncated to edges with timestamp <= t_e
                (and, as a secondary variant, < t_e -- "strict", which also removes
                simultaneous edges of the same second)

The truncation is done by wrapping the module-level adjacency dicts so every per-node
list / timestamp array the feature code reads is cut at bisect_right(ts, t_cut); the
feature code itself is not touched. Reports, per feature, the fraction of sampled edges
whose value differs and the mean |full - restricted|, overall and split by illicit / licit,
and checks that the full-graph values reproduce
data/processed/amlworld_gfp_features_test.parquet.

--lookahead measures the LEGACY forward definition of temporal_cycle (pre Step 3b-z: BFS from
v over edges after t_e, static SCC gate) on the legacy parquets
amlworld_gfp_features_<split>_legacy_forwardcycle.parquet: closing-edge time - t_e for every
flagged edge. The legacy function is reproduced here verbatim so the number stays
computable after graph/motif_features.py switched to the trailing `_closes_cycle`.

Writes docs/feature_causality_check.json (with --dry-run: *_dryrun.json, not reportable).
Read-only: nothing under data/ or experiments/ is written.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp
import yaml
from scipy.sparse.csgraph import connected_components

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import graph.motif_features as mf  # noqa: E402  (the production feature code, used unchanged)

DATA = REPO_ROOT / "data" / "processed"
SEEDS_YAML = REPO_ROOT / "configs" / "seeds.yaml"
FEATURES = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
            "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]
WINDOW_S, MAX_HOPS = 86400, 5  # README: --window 86400 --max-cycle-hops 5
LOOKBACK_S = mf.LOOKBACK_DAYS_DEFAULT * 86400  # closes_cycle look-back (Step 3b-z)


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def build_adjacency_fast(src: np.ndarray, dst: np.ndarray, ts: np.ndarray):
    """Same structures as motif_features.build_adjacency (node -> [(ts, nbr)] sorted as
    tuples, node -> int64 ts array), built with numpy instead of iterrows."""
    def one_side(key, nbr):
        order = np.lexsort((nbr, ts, key))          # sort by key, then ts, then nbr == tuple sort
        k, t, n = key[order], ts[order], nbr[order]
        uniq, start = np.unique(k, return_index=True)
        end = np.append(start[1:], len(k))
        adj, adj_ts = {}, {}
        for node, s, e in zip(uniq.tolist(), start.tolist(), end.tolist()):
            adj[node] = list(zip(t[s:e].tolist(), n[s:e].tolist()))
            adj_ts[node] = t[s:e].copy()
        return adj, adj_ts
    adj_out, adj_out_ts = one_side(src, dst)
    adj_in, adj_in_ts = one_side(dst, src)
    return adj_out, adj_in, adj_out_ts, adj_in_ts


def scc_nodes_fast(src: np.ndarray, dst: np.ndarray, n_nodes: int) -> set:
    """Nodes in non-trivial SCCs of the static graph (== motif_features.build_scc_set)."""
    g = sp.csr_matrix((np.ones(len(src), dtype=np.int8), (src, dst)), shape=(n_nodes, n_nodes))
    n_comp, labels = connected_components(g, directed=True, connection="strong")
    counts = np.bincount(labels, minlength=n_comp)
    return set(np.flatnonzero(counts[labels] > 1).tolist())


class Truncated:
    """Read-only view of an adjacency dict cut at timestamp <= t_cut per node."""

    def __init__(self, adj: dict, adj_ts: dict, t_cut: int, arrays: bool):
        self.adj, self.adj_ts, self.t_cut, self.arrays = adj, adj_ts, t_cut, arrays

    def _cut(self, node):
        ts = self.adj_ts.get(node)
        if ts is None:
            return None
        hi = bisect_right(ts, self.t_cut)
        return ts[:hi] if self.arrays else self.adj[node][:hi]

    def get(self, node, default=None):
        v = self._cut(node)
        return default if v is None else v

    def __getitem__(self, node):
        v = self._cut(node)
        if v is None:
            raise KeyError(node)
        return v


def features_for(src: int, dst: int, t: int) -> np.ndarray:
    """The production per-edge computation (mirrors motif_features._process_chunk)."""
    out = np.zeros(10, dtype=np.int64)
    out[0] = mf._fan_out_count(src, t)
    out[1] = mf._fan_in_count(dst, t)
    out[2] = mf._cum_out_degree(src, t)
    out[3] = mf._cum_in_degree(src, t)
    out[4] = mf._cum_out_degree(dst, t)
    out[5] = mf._cum_in_degree(dst, t)
    out[6], out[7] = mf._scatter_gather(src, dst, t)
    out[8], out[9] = mf._closes_cycle(src, dst, t)
    return out


def legacy_forward_cycle_closing_time(src: int, dst: int, t: int, scc: set) -> int | None:
    """The pre-3b-z `_temporal_cycle` (forward BFS from dst over edges after t, static SCC
    gate, same BFS order), returning the timestamp of the edge that closes the cycle (None
    if no cycle). Look-ahead = closing time - t. Reads mf._ADJ_OUT / _ADJ_OUT_TS / _MAX_HOPS."""
    if src not in scc or dst not in scc:
        return None
    visited = {dst}
    queue = [(dst, t, 1)]
    while queue:
        current, min_ts, hops = queue.pop(0)
        if hops > mf._MAX_HOPS:
            continue
        edges = mf._ADJ_OUT.get(current)
        if not edges:
            continue
        lo = bisect_right(mf._ADJ_OUT_TS[current], min_ts)
        for idx in range(lo, len(edges)):
            edge_ts, neighbor = edges[idx]
            if neighbor == src:
                return int(edge_ts)
            if neighbor not in visited and hops < mf._MAX_HOPS:
                visited.add(neighbor)
                queue.append((neighbor, edge_ts, hops + 1))
    return None


def set_graph(adj_out, adj_in, adj_out_ts, adj_in_ts, t_cut: int | None):
    if t_cut is None:
        mf._ADJ_OUT, mf._ADJ_IN, mf._ADJ_OUT_TS, mf._ADJ_IN_TS = adj_out, adj_in, adj_out_ts, adj_in_ts
    else:
        mf._ADJ_OUT = Truncated(adj_out, adj_out_ts, t_cut, arrays=False)
        mf._ADJ_IN = Truncated(adj_in, adj_in_ts, t_cut, arrays=False)
        mf._ADJ_OUT_TS = Truncated(adj_out, adj_out_ts, t_cut, arrays=True)
        mf._ADJ_IN_TS = Truncated(adj_in, adj_in_ts, t_cut, arrays=True)
    mf._WINDOW, mf._MAX_HOPS, mf._LOOKBACK = WINDOW_S, MAX_HOPS, LOOKBACK_S


def summarise(full: np.ndarray, restricted: np.ndarray, y: np.ndarray) -> dict:
    diff = full - restricted
    out = {}
    for name, m in (("all", np.ones_like(y, dtype=bool)), ("illicit", y == 1), ("licit", y == 0)):
        d = diff[m]
        if not m.any():
            out[name] = {"n": 0}
            continue
        out[name] = {"n": int(m.sum()),
                     "frac_differs": {f: float((d[:, i] != 0).mean()) for i, f in enumerate(FEATURES)},
                     "mean_abs_diff": {f: float(np.abs(d[:, i]).mean()) for i, f in enumerate(FEATURES)},
                     "max_abs_diff": {f: int(np.abs(d[:, i]).max()) for i, f in enumerate(FEATURES)},
                     "mean_full": {f: float(full[m][:, i].mean()) for i, f in enumerate(FEATURES)}}
    return out


def print_table(res: dict, variant: str):
    s = res[variant]
    print(f"\n[{variant}] restricted graph = edges with timestamp {'<= t_e' if variant == 'le' else '< t_e'}")
    print(f"{'feature':16s} | {'differs all':>11s} {'MAD all':>9s} | {'differs ill':>11s} {'MAD ill':>9s} | "
          f"{'differs lic':>11s} {'MAD lic':>9s} | {'max|d|':>7s}")
    for f in FEATURES:
        cells = []
        for g in ("all", "illicit", "licit"):
            if s[g]["n"] == 0:
                cells.append(f"{'n/a':>11s} {'':9s}")
                continue
            cells.append(f"{100 * s[g]['frac_differs'][f]:10.2f}% {s[g]['mean_abs_diff'][f]:9.3f}")
        print(f"{f:16s} | " + " | ".join(cells) + f" | {s['all']['max_abs_diff'][f]:7d}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=None, help="default: first seed in configs/seeds.yaml")
    ap.add_argument("--data-dir", type=Path, default=DATA)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--all-illicit", action="store_true",
                    help="also run on EVERY illicit test edge (supplement: the random sample holds only ~18)")
    ap.add_argument("--lookahead", action="store_true",
                    help="supplement: observed look-ahead (closing-edge time - t_e) of every edge with "
                         "temporal_cycle == 1 in the stored train / val / test parquets")
    ap.add_argument("--dry-run", action="store_true", help="1% of the sample (100 edges) -- pipeline check")
    args = ap.parse_args(argv)
    seed = args.seed if args.seed is not None else int(yaml.safe_load(SEEDS_YAML.read_text())["seeds"][0])
    n = max(1, args.n // 100) if args.dry_run else args.n

    t0 = time.time()
    frames = [pd.read_parquet(args.data_dir / f"amlworld_edges_{s}.parquet", columns=["from_id", "to_id", "Timestamp"])
              for s in ("train", "val", "test")]
    all_edges = pd.concat(frames, ignore_index=True)  # same order as motif_features.main
    src = all_edges["from_id"].to_numpy(np.int64)
    dst = all_edges["to_id"].to_numpy(np.int64)
    ts = all_edges["Timestamp"].to_numpy(np.int64)
    n_nodes = int(max(src.max(), dst.max())) + 1
    adj_out, adj_in, adj_out_ts, adj_in_ts = build_adjacency_fast(src, dst, ts)
    print(f"[audit] {len(all_edges):,} edges, {n_nodes:,} node ids; adjacency built in {time.time() - t0:.0f}s")

    test = pd.read_parquet(args.data_dir / "amlworld_test.parquet",
                           columns=["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering"])
    gfp = pd.read_parquet(args.data_dir / "amlworld_gfp_features_test.parquet").set_index("EdgeID")
    rng = np.random.default_rng(seed)
    pick = np.sort(rng.choice(len(test), size=n, replace=False))
    sample = test.iloc[pick].reset_index(drop=True)
    y = sample["Is Laundering"].to_numpy(np.int64)
    print(f"[audit] {n:,} test edges sampled (seed {seed}); illicit {int(y.sum())}")

    def run(sample_df):
        k = len(sample_df)
        full = np.zeros((k, 10), dtype=np.int64)
        rest = {"le": np.zeros((k, 10), dtype=np.int64), "lt": np.zeros((k, 10), dtype=np.int64)}
        t1 = time.time()
        for i, r in enumerate(sample_df.itertuples(index=False)):
            u, v, t = int(r.from_id), int(r.to_id), int(r.Timestamp)
            set_graph(adj_out, adj_in, adj_out_ts, adj_in_ts, None)
            full[i] = features_for(u, v, t)
            set_graph(adj_out, adj_in, adj_out_ts, adj_in_ts, t)
            rest["le"][i] = features_for(u, v, t)
            set_graph(adj_out, adj_in, adj_out_ts, adj_in_ts, t - 1)
            rest["lt"][i] = features_for(u, v, t)
            if i % 1000 == 0:
                print(f"  {i:6d}/{k} | {time.time() - t1:.0f}s")
        return full, rest

    full, rest = run(sample)
    stored = gfp.loc[sample["EdgeID"].values, FEATURES].to_numpy(np.int64)
    repro = {f: float((full[:, i] == stored[:, i]).mean()) for i, f in enumerate(FEATURES)}
    print("[audit] full-graph recomputation == stored parquet: " +
          ", ".join(f"{f} {100 * v:.1f}%" for f, v in repro.items()))

    res = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "n_sampled": n, "n_illicit": int(y.sum()), "seed": seed, "dry_run": bool(args.dry_run),
           "window_s": WINDOW_S, "max_cycle_hops": MAX_HOPS,
           "adjacency": "train + val + test edges (as graph/motif_features.py main builds it)",
           "definition": "full = production feature functions on the full adjacency; le = same functions on the "
                         "adjacency truncated to timestamp <= t_e; lt = truncated to < t_e (strict). "
                         "frac_differs = share of sampled edges with full != restricted; mean_abs_diff = "
                         "mean |full - restricted| over the sample (raw counts, before log1p).",
           "reproduces_stored_parquet": repro,
           "le": summarise(full, rest["le"], y), "lt": summarise(full, rest["lt"], y),
           "seconds": round(time.time() - t0, 1)}
    if args.all_illicit:
        ill = test[test["Is Laundering"] == 1].reset_index(drop=True)
        print(f"[audit] supplement: all {len(ill):,} illicit test edges")
        f_ill, r_ill = run(ill)
        y_ill = np.ones(len(ill), dtype=np.int64)
        res["all_illicit_test_edges"] = {"n": int(len(ill)),
                                         "le": summarise(f_ill, r_ill["le"], y_ill)["illicit"],
                                         "lt": summarise(f_ill, r_ill["lt"], y_ill)["illicit"]}
    if args.lookahead:
        set_graph(adj_out, adj_in, adj_out_ts, adj_in_ts, None)
        scc = scc_nodes_fast(src, dst, n_nodes)  # the legacy gate (static, all splits)
        split_end = {}
        la = {}
        for split in ("train", "val", "test"):
            d = pd.read_parquet(args.data_dir / f"amlworld_{split}.parquet", columns=["EdgeID", "from_id", "to_id", "Timestamp"])
            split_end[split] = int(d["Timestamp"].max())
            legacy = args.data_dir / f"amlworld_gfp_features_{split}_legacy_forwardcycle.parquet"
            if not legacy.exists():
                legacy = args.data_dir / f"amlworld_gfp_features_{split}.parquet"  # before 3b-z regenerated them
            g = pd.read_parquet(legacy, columns=["EdgeID", "temporal_cycle"])
            cyc = d[d["EdgeID"].isin(g.loc[g["temporal_cycle"] == 1, "EdgeID"])]
            gaps, beyond = [], 0
            for r in cyc.itertuples(index=False):
                c = legacy_forward_cycle_closing_time(int(r.from_id), int(r.to_id), int(r.Timestamp), scc)
                assert c is not None, f"{legacy.name}: temporal_cycle == 1 but the legacy search finds no cycle"
                gaps.append(c - int(r.Timestamp))
                beyond += int(c > split_end[split])
            gaps = np.array(gaps, dtype=np.int64)
            la[split] = {"n_edges_with_cycle": int(len(gaps)), "n_closing_after_split_end": int(beyond),
                         "lookahead_s": {"min": int(gaps.min()), "median": float(np.median(gaps)),
                                         "p90": float(np.percentile(gaps, 90)), "max": int(gaps.max())},
                         "frac_lookahead_over": {f"{h}h": float((gaps > h * 3600).mean()) for h in (1, 6, 24, 72)}}
            print(f"[lookahead] {split}: {len(gaps):,} edges with temporal_cycle=1; look-ahead median "
                  f"{np.median(gaps) / 3600:.1f} h, p90 {np.percentile(gaps, 90) / 3600:.1f} h, max "
                  f"{gaps.max() / 86400:.1f} d; {beyond:,} close after the split's last timestamp")
        res["temporal_cycle_lookahead"] = {"definition": "LEGACY forward temporal_cycle (pre 3b-z): closing-edge "
                                                         "timestamp - t_e for every edge flagged in the legacy "
                                                         "parquet (same BFS order as the old production code)",
                                           "source_parquets": "amlworld_gfp_features_<split>_legacy_forwardcycle.parquet",
                                           "split_end_timestamp": split_end, **la}
    print_table(res, "le")
    print_table(res, "lt")
    if args.all_illicit:
        s = res["all_illicit_test_edges"]
        print(f"\n[all illicit test edges, n = {s['n']:,}] differs (<= t_e) / MAD:")
        for f in FEATURES:
            print(f"  {f:16s} {100 * s['le']['frac_differs'][f]:7.2f}%  {s['le']['mean_abs_diff'][f]:.3f}"
                  f"   (< t_e: {100 * s['lt']['frac_differs'][f]:7.2f}%  {s['lt']['mean_abs_diff'][f]:.3f})")
    out = args.out or (REPO_ROOT / "docs" / f"feature_causality_check{'_dryrun' if args.dry_run else ''}.json")
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return res


if __name__ == "__main__":
    main()
