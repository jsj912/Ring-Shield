"""M3: flow-following expansion from seed-only rings (paper/PREREG_METHOD_2026-11-15.md §4).

    python -m evaluation.m3_flow grid --seed 1          # all 18 validation cells

Start: B0 rings at 0.1 % (connected components of the seed edges, >= 3 accounts). Anchors are the
ring's edges. Each hop, for an anchor u -> a (received amount x, time t) add a -> v with
t < t' <= t + D and |y - x| / x <= eps (y = the sent amount); for an anchor a -> v (sent y, time t')
add u -> a with t' - D <= t < t' and |y - x| / x <= eps. Edges added in a hop are the next hop's
anchors; up to H hops. Same currency: amounts compared as they are; different currencies: both
converted to the repository's hub currency (contract/fx_rates.json, ringshield.roles; currency 0,
not USD); an unconvertible currency never matches. Accounts with total degree > 100 in the split are
not traversed (as M2). Rings sharing >= 2 accounts are merged; >= 3 accounts.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.m2_motif import Graph, merge_groups  # noqa: E402

OUT = REPO_ROOT / "experiments" / "M3_flow"
R1 = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"
H = 3600
GRID = [{"eps": e, "D_h": d, "hops": h} for e, d, h in product((0.01, 0.05, 0.10), (6, 24, 72), (1, 2))]
REF_VAL_SEED1 = 0.5852


class FlowGraph(Graph):
    def __init__(self, src, dst, ts, amt_sent, amt_recv, ccy_sent, ccy_recv, fx=None, eid=None):
        super().__init__(src, dst, ts, np.zeros(len(src)), eid)
        self.y = np.asarray(amt_sent, float)                     # what leaves the sender
        self.x = np.asarray(amt_recv, float)                     # what reaches the receiver
        self.cs, self.cr = np.asarray(ccy_sent, np.int64), np.asarray(ccy_recv, np.int64)
        table = (fx or {}).get("rate_to_ccy0", {})
        rate = lambda c: np.array([float(table[int(v)]) if table.get(int(v)) is not None else np.nan for v in c])
        self.y_hub = self.y * rate(self.cs) if fx else np.full(len(self.y), np.nan)
        self.x_hub = self.x * rate(self.cr) if fx else np.full(len(self.x), np.nan)

    def match(self, i_in: int, i_out: int, eps: float) -> bool:
        """Incoming edge i_in's received amount vs outgoing edge i_out's sent amount."""
        if self.cr[i_in] == self.cs[i_out]:
            x, y = self.x[i_in], self.y[i_out]
        else:
            x, y = self.x_hub[i_in], self.y_hub[i_out]
        return bool(np.isfinite(x) and np.isfinite(y) and x > 0 and abs(y - x) / x <= eps)


def follow(G: FlowGraph, ring_edges: set, eps: float, D: int, hops: int, ok=None) -> set:
    edges, frontier = set(ring_edges), set(ring_edges)
    for _ in range(hops):
        new = set()
        for e in frontier:
            a, t = int(G.dst[e]), int(G.ts[e])                    # forward: e = u -> a
            if not G.hub(a):
                for j in G.outs(a, t + 1, t + D, ok if ok is not None else np.ones(len(G.src), bool)):
                    if j not in edges and G.match(e, j, eps):
                        new.add(j)
            a, t = int(G.src[e]), int(G.ts[e])                    # backward: e = a -> v
            if not G.hub(a):
                for j in G.ins(a, t - D, t - 1, ok if ok is not None else np.ones(len(G.src), bool)):
                    if j not in edges and G.match(j, e, eps):
                        new.add(j)
        if not new:
            break
        edges |= new
        frontier = new
    return edges


def b0_groups(G: Graph, seeds: np.ndarray, min_size: int = 3) -> list[frozenset]:
    from evaluation.m2_motif import seed_components
    out = []
    for c in seed_components(G, seeds):
        accs = set(G.src[list(c)].tolist()) | set(G.dst[list(c)].tolist())
        if len(accs) >= min_size:
            out.append(c)
    return out


def run_cell(G: FlowGraph, seeds: np.ndarray, cell: dict):
    ok = np.ones(len(G.src), bool)
    groups = [frozenset(follow(G, set(g), cell["eps"], int(cell["D_h"] * H), cell["hops"], ok)) for g in b0_groups(G, seeds)]
    n_added = sum(len(g) for g in groups) - sum(len(g) for g in b0_groups(G, seeds))
    return merge_groups(G, groups), {"n_b0_rings": len(groups), "n_added_edges": int(n_added)}


def cmd_grid(a):
    from contract.make_scored_edges import load_paths
    from evaluation.ring_metrics import evaluate_rings
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.roles import load_fx_rates
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth, split_window
    t0 = time.time()
    pdir = load_paths()["processed_dir"]
    se = build_scored_edges(R1 / f"scores_val_seed{a.seed}.parquet", "val", model_id="gine_causal", seed=a.seed, processed_dir=pdir)
    G = FlowGraph(se["from_id"], se["to_id"], se["timestamp"], se["amount_sent"], se["amount_received"],
                  se["currency_sent"], se["currency_received"], load_fx_rates(), se["edge_id"])
    seeds = np.flatnonzero(seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.10))
    truth, pat = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *split_window(pdir / "amlworld_val.parquet"),
                                   "test_visible", verbose=False)
    rows = []
    for cell in GRID:
        t1 = time.time()
        rings, st = run_cell(G, seeds, cell)
        m = evaluate_rings([r[0] for r in rings], truth, 0.5, pat)
        rows.append({**cell, "ring_f1": float(m.ring_f1), "ring_precision": float(m.ring_precision),
                     "ring_recall": float(m.ring_recall), "n_rings": len(rings),
                     "n_accounts": len(set().union(*[r[0] for r in rings])) if rings else 0, **st,
                     "seconds": round(time.time() - t1, 1)})
        print({k: (round(v, 4) if isinstance(v, float) else v) for k, v in rows[-1].items()}, flush=True)
    out = OUT / "val" / f"seed{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out / "grid.csv", index=False)
    print(f"[m3] {len(rows)} cells in {time.time() - t0:.0f}s, {len(seeds)} seeds -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("grid"); p.add_argument("--seed", type=int, required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cmd_grid(a)


if __name__ == "__main__":
    main()
