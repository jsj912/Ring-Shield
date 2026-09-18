"""Step 3b-x (1): how much of a seed's sampled neighbourhood is in-window future?

    python tests/measure_window_leak.py                       # val, W = 1,800 s, R1 config
    python tests/measure_window_leak.py --window-s 300
    python tests/measure_window_leak.py --dry-run             # 1% rows, pipeline check only

Iterates every validation batch of the causal loader (fallback route, R1_gine_causal config:
num_neighbors 100/100, batch 8192, window W). For every seed edge (u -> v, time t) it takes
the message-passing edges the model can actually see for that seed in the batch subgraph:

    hop 1  edges of the store incident to u or v (the seed's own copy excluded)
    hop 2  edges incident to any endpoint of a hop-1 edge, not already hop 1 / the seed

in BOTH stores (`to` and `rev_to`, sampled independently), and counts those whose timestamp
lies in (t, t_max_batch] -- "in-window future": edges the causal filter lets through because
they precede the latest seed of the batch, but which are after this seed. Reports, split by
illicit / licit seeds and by hop: mean and 90th percentile of the per-seed fraction
(seeds with an empty hop are excluded from the fraction and counted), the share of seeds
with >= 1 in-window-future neighbour, and -- for illicit seeds -- the share with >= 1
in-window-future neighbour that is itself illicit (hop 1, hop 2, either).

Writes docs/window_leak_<split>_w<W>.json (with --dry-run: *_dryrun.json, not reportable).
No model is run; this is a loader-only measurement.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy.sparse as sp
import torch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from models.causal_loader import REV, ROUTE, TO, WINDOW_S, make_loader, seed_mask  # noqa: E402
from models.score import args_from_run_config  # noqa: E402
from models.tgn import load_data  # noqa: E402

DEFAULT_RUN = REPO_ROOT / "experiments" / "R1_gine_causal"
CHUNK = 1024  # seeds per sparse product


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def incidence(edge_index: np.ndarray, n_nodes: int) -> sp.csr_matrix:
    """Binary node x edge incidence (src and dst rows)."""
    n_e = edge_index.shape[1]
    rows = np.concatenate([edge_index[0], edge_index[1]])
    cols = np.concatenate([np.arange(n_e), np.arange(n_e)])
    a = sp.csr_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n_nodes, n_e))
    a.data[:] = 1  # self-loop edges got a 2
    return a


def _binarize(m: sp.csr_matrix) -> sp.csr_matrix:
    m = m.tocsr()
    m.eliminate_zeros()  # first: explicit zeros from the subtractions must not become ones
    m.data[:] = 1
    return m


def _row_counts(m: sp.csr_matrix, ts: np.ndarray, y: np.ndarray, seed_t: np.ndarray, n_rows: int):
    """Per row: #edges, #edges with ts > seed_t[row], #those that are illicit."""
    coo = m.tocoo()
    fut = ts[coo.col] > seed_t[coo.row]
    n = np.bincount(coo.row, minlength=n_rows)
    n_fut = np.bincount(coo.row[fut], minlength=n_rows)
    n_fut_illicit = np.bincount(coo.row[fut & (y[coo.col] == 1)], minlength=n_rows)
    return n, n_fut, n_fut_illicit


def store_counts(edge_index: torch.Tensor, ts: np.ndarray, y: np.ndarray, e_id: np.ndarray,
                 seed_local_idx: np.ndarray, seed_uv: np.ndarray, seed_t: np.ndarray, n_nodes: int) -> dict:
    """Hop-1 / hop-2 counts for every seed of the batch in one store.

    seed_local_idx: position of each seed's own copy in this store (excluded from hop 1);
    seed_uv: (n_seed, 2) local node ids of the seed endpoints."""
    ei = edge_index.numpy()
    n_e = ei.shape[1]
    A = incidence(ei, n_nodes)
    At = A.T.tocsr()
    n_seed = len(seed_t)
    out = {k: np.zeros(n_seed, dtype=np.int64) for k in
           ("h1", "h1_fut", "h1_fut_ill", "h2", "h2_fut", "h2_fut_ill")}
    for s0 in range(0, n_seed, CHUNK):
        s1 = min(n_seed, s0 + CHUNK)
        k = s1 - s0
        rows = np.repeat(np.arange(k), 2)
        S = sp.csr_matrix((np.ones(2 * k, dtype=np.int8), (rows, seed_uv[s0:s1].reshape(-1))), shape=(k, n_nodes))
        S.data[:] = 1
        H1 = _binarize(S @ A)                                       # k x E: edges touching u or v
        own = sp.csr_matrix((np.ones(k, dtype=np.int8), (np.arange(k), seed_local_idx[s0:s1])), shape=(k, n_e))
        H1 = _binarize(H1 - H1.multiply(own))                       # drop the seed's own copy
        N1 = _binarize(H1 @ At)                                     # k x nodes reached by hop-1 edges
        H2 = _binarize(N1 @ A)                                      # edges touching those nodes
        H2 = _binarize(H2 - H2.multiply(H1) - H2.multiply(own))     # minus hop 1 and the seed itself
        st = seed_t[s0:s1]
        n, f, fi = _row_counts(H1, ts, y, st, k)
        out["h1"][s0:s1], out["h1_fut"][s0:s1], out["h1_fut_ill"][s0:s1] = n, f, fi
        n, f, fi = _row_counts(H2, ts, y, st, k)
        out["h2"][s0:s1], out["h2_fut"][s0:s1], out["h2_fut_ill"][s0:s1] = n, f, fi
    return out


def measure(data, inds: torch.Tensor, args, window_s: int, max_batches: int | None = None) -> dict:
    """Run the causal val loader once and collect per-seed counts."""
    loader = make_loader(data, inds, args, causal=True, shuffle=False, window_s=window_s)
    assert ROUTE["route"] == "fallback", f"route {ROUTE['route']}: the window measurement is for the fallback route"
    y_all = data[TO].y.numpy()
    ts_all = data[TO].timestamps.numpy()
    cols = {k: [] for k in ("seed_global", "seed_y", "seed_t", "batch_tmax", "n_seed_batch",
                            "h1", "h1_fut", "h1_fut_ill", "h2", "h2_fut", "h2_fut_ill",
                            "to_h1", "to_h1_fut", "rev_h1", "rev_h1_fut", "to_h2", "to_h2_fut", "rev_h2", "rev_h2_fut")}
    t0 = time.time()
    n_batches = 0
    for bi, batch in enumerate(loader):
        if max_batches is not None and bi >= max_batches:
            break
        mask, seed_global = seed_mask(batch)
        seed_global = seed_global.numpy()
        n_seed = len(seed_global)
        seed_t = ts_all[seed_global].astype(np.int64)
        tmax = seed_t.max()
        n_nodes = batch["node"].num_nodes
        to, rev = batch[TO], batch[REV]
        assert int(mask.sum()) == n_seed and bool(mask[-n_seed:].all())
        seed_uv = to.edge_index[:, mask].numpy().T                     # (n_seed, 2) local ids of (u, v)
        n_to, n_rev = to.edge_index.size(1), rev.edge_index.size(1)
        tot = {k: np.zeros(n_seed, dtype=np.int64) for k in ("h1", "h1_fut", "h1_fut_ill", "h2", "h2_fut", "h2_fut_ill")}
        for name, st, n_e in (("to", to, n_to), ("rev", rev, n_rev)):
            ts = st.timestamps.numpy().astype(np.int64)
            assert ts.max() <= tmax, "causal filter violated"
            y = y_all[st.e_id.numpy()]
            own = np.arange(n_e - n_seed, n_e)                        # seeds are the last n_seed edges of each store
            assert np.array_equal(st.e_id.numpy()[own], seed_global), f"{name}: seed copies not last"
            c = store_counts(st.edge_index, ts, y, st.e_id.numpy(), own, seed_uv, seed_t, n_nodes)
            for k in tot:
                tot[k] += c[k]
            cols[f"{name}_h1"].append(c["h1"]); cols[f"{name}_h1_fut"].append(c["h1_fut"])
            cols[f"{name}_h2"].append(c["h2"]); cols[f"{name}_h2_fut"].append(c["h2_fut"])
        for k, v in tot.items():
            cols[k].append(v)
        cols["seed_global"].append(seed_global)
        cols["seed_y"].append(y_all[seed_global].astype(np.int64))
        cols["seed_t"].append(seed_t)
        cols["batch_tmax"].append(np.full(n_seed, tmax, dtype=np.int64))
        cols["n_seed_batch"].append(np.full(n_seed, n_seed, dtype=np.int64))
        n_batches += 1
        if bi % 20 == 0:
            print(f"  batch {bi:4d}: seeds {n_seed:5d} window [{seed_t.min()}, {tmax}] "
                  f"edges to/rev {n_to:,}/{n_rev:,} | {time.time() - t0:.0f}s")
    arr = {k: np.concatenate(v) for k, v in cols.items()}
    arr["n_batches"] = n_batches
    arr["seconds"] = time.time() - t0
    return arr


def _frac_stats(num: np.ndarray, den: np.ndarray) -> dict:
    ok = den > 0
    f = num[ok] / den[ok]
    return {"n_seeds": int(len(den)), "n_seeds_with_empty_hop": int((~ok).sum()),
            "mean": float(f.mean()) if ok.any() else None,
            "p50": float(np.percentile(f, 50)) if ok.any() else None,
            "p90": float(np.percentile(f, 90)) if ok.any() else None,
            "p99": float(np.percentile(f, 99)) if ok.any() else None,
            "share_seeds_with_any_future": float((num > 0).mean()),
            "total_edges": int(den.sum()), "total_future_edges": int(num.sum()),
            "pooled_fraction": float(num.sum() / den.sum()) if den.sum() else None}


def summarise(arr: dict, window_s: int) -> dict:
    y = arr["seed_y"]
    groups = {"illicit": y == 1, "licit": y == 0, "all": np.ones_like(y, dtype=bool)}
    res = {"n_batches": int(arr["n_batches"]), "n_seeds": int(len(y)), "n_illicit_seeds": int((y == 1).sum()),
           "seconds": round(float(arr["seconds"]), 1),
           "batch_seeds": {"mean": float(arr["n_seed_batch"].mean()), "max": int(arr["n_seed_batch"].max())},
           "seed_to_batch_max_gap_s": {"mean": float((arr["batch_tmax"] - arr["seed_t"]).mean()),
                                       "p90": float(np.percentile(arr["batch_tmax"] - arr["seed_t"], 90)),
                                       "max": int((arr["batch_tmax"] - arr["seed_t"]).max())},
           "by_group": {}}
    for g, m in groups.items():
        d = {"n_seeds": int(m.sum())}
        for hop in ("h1", "h2"):
            d[f"hop{hop[-1]}"] = {"both_stores": _frac_stats(arr[f"{hop}_fut"][m], arr[hop][m]),
                                 "to": _frac_stats(arr[f"to_{hop}_fut"][m], arr[f"to_{hop}"][m]),
                                 "rev_to": _frac_stats(arr[f"rev_{hop}_fut"][m], arr[f"rev_{hop}"][m])}
        d["hop1+2"] = {"both_stores": _frac_stats((arr["h1_fut"] + arr["h2_fut"])[m], (arr["h1"] + arr["h2"])[m])}
        if g == "illicit":
            d["share_with_future_illicit_neighbour"] = {
                "hop1": float((arr["h1_fut_ill"][m] > 0).mean()),
                "hop2": float((arr["h2_fut_ill"][m] > 0).mean()),
                "either": float(((arr["h1_fut_ill"] + arr["h2_fut_ill"])[m] > 0).mean()),
                "n_illicit_seeds": int(m.sum())}
        res["by_group"][g] = d
    return res


def print_table(res: dict, window_s: int):
    print(f"\n[window_leak] W = {window_s}s  batches {res['n_batches']}  seeds {res['n_seeds']:,} "
          f"(illicit {res['n_illicit_seeds']:,})  mean seeds/batch {res['batch_seeds']['mean']:.0f}  "
          f"seed->batch-max gap mean {res['seed_to_batch_max_gap_s']['mean']:.0f}s p90 "
          f"{res['seed_to_batch_max_gap_s']['p90']:.0f}s")
    print(f"{'group':8s} {'hop':6s} {'seeds':>8s} {'empty':>6s} {'mean':>7s} {'p50':>7s} {'p90':>7s} {'p99':>7s} "
          f"{'any>0':>7s} {'pooled':>7s} {'edges':>12s}")
    for g in ("illicit", "licit", "all"):
        d = res["by_group"][g]
        for hop in ("hop1", "hop2", "hop1+2"):
            s = d[hop]["both_stores"]
            fmt = lambda v: f"{v:7.4f}" if v is not None else f"{'-':>7s}"
            print(f"{g:8s} {hop:6s} {s['n_seeds']:8d} {s['n_seeds_with_empty_hop']:6d} {fmt(s['mean'])} "
                  f"{fmt(s['p50'])} {fmt(s['p90'])} {fmt(s['p99'])} {s['share_seeds_with_any_future']:7.4f} "
                  f"{fmt(s['pooled_fraction'])} {s['total_edges']:12,d}")
    ill = res["by_group"]["illicit"]["share_with_future_illicit_neighbour"]
    print(f"illicit seeds with >= 1 in-window-future ILLICIT neighbour: hop1 {ill['hop1']:.4f}  "
          f"hop2 {ill['hop2']:.4f}  either {ill['either']:.4f}  (n = {ill['n_illicit_seeds']})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", type=Path, default=DEFAULT_RUN, help="config.yaml source (loader settings)")
    ap.add_argument("--split", choices=("val", "test", "train"), default="val")
    ap.add_argument("--window-s", type=int, default=WINDOW_S)
    ap.add_argument("--seed", type=int, default=1, help="dry-run sample seed only; no randomness otherwise")
    ap.add_argument("--max-batches", type=int, default=None, help="debug: stop after this many batches")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    run_args, cfg = args_from_run_config(args.run_dir, dry_run=args.dry_run, dry_run_seed=args.seed)
    t0 = time.time()
    tr, va, te, tr_inds, val_inds, te_inds, _ = load_data(run_args.raw_dir, run_args.data_dir, run_args)
    data, inds = {"train": (tr, tr_inds), "val": (va, val_inds), "test": (te, te_inds)}[args.split]
    print(f"[window_leak] data ready in {time.time() - t0:.0f}s; {args.split}: {inds.numel():,} seeds")

    arr = measure(data, inds, run_args, args.window_s, args.max_batches)
    res = summarise(arr, args.window_s)
    res = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "run_dir": str(args.run_dir), "split": args.split, "window_s": args.window_s,
           "loader_route": ROUTE["route"], "num_neighbors": run_args.num_neighs, "batch_size": run_args.batch_size,
           "dry_run": bool(args.dry_run), "max_batches": args.max_batches,
           "definition": "per seed edge (u->v, t): hop-1 = batch edges incident to u or v (own copy excluded), "
                         "hop-2 = edges incident to endpoints of hop-1 edges minus hop-1 / own copy; counted in "
                         "both stores (to, rev_to) which are sampled independently; in-window future = timestamp "
                         "in (t, max seed timestamp of the batch]. Fractions are per seed; seeds with an empty hop "
                         "are excluded from mean/percentiles and counted in n_seeds_with_empty_hop. pooled_fraction "
                         "= sum(future) / sum(edges).",
           **res}
    print_table(res, args.window_s)
    out = args.out or (REPO_ROOT / "docs" / f"window_leak_{args.split}_w{args.window_s}"
                       f"{'_dryrun' if args.dry_run else ''}{'_partial' if args.max_batches else ''}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"-> {out}")
    return res


if __name__ == "__main__":
    main()
