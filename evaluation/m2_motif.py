"""M2: temporal motif search from 0.1 % seeds (paper/PREREG_METHOD_2026-11-15.md §3).

    python -m evaluation.m2_motif grid --seed 1          # all 24 validation cells for one detector seed

From each seed edge, time-ordered instances that contain the seed are enumerated in the scored
split's transaction multigraph, all edges within T of the seed:
  FAN_OUT / FAN_IN  >= f edges out of the seed's source / into its target
  SCATTER_GATHER    a -> m_i -> b, a->m_i before m_i->b, >= 2 middles
  GATHER_SCATTER    s_i -> m -> d_j, every in-edge before the last out, out after the first in, >= 2 + 2
  CYCLE             a time-ordered cycle (one rotation) through the seed, 3 <= length <= L
  BIPARTITE         complete 2x2 blocks through the seed: all edges between the sources and targets found
  STACK             a bipartite block through the seed chained to a second complete 2x2 layer
                    (after the seed's layer, or before it), time-ordered between layers
Fixed caps (prereg): <= 50 instances per seed (highest mean score rank first); accounts with
total degree > 100 in the split are never traversed. Implementation limit (stated in the notes,
not a grid cell): a cycle search stops after 20,000 steps per seed; binding counts are logged.
Rings: seed connected components plus instances, merged when they share >= 2 accounts; >= 3 accounts.
M2-G (score-gated): a non-seed edge must have score rank in the split's top g.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timezone
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

OUT = REPO_ROOT / "experiments" / "M2_motif"
R1 = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"
MAX_INST, HUB_DEG, CYCLE_STEPS, K_PCT = 50, 100, 20000, 0.10
H = 3600
GRID_S = [{"variant": "M2-S", "T_h": T, "f": f, "L": L} for T, f, L in product((24, 72), (3, 5), (4, 6))]
GRID_G = [{"variant": "M2-G", "T_h": T, "f": f, "L": L, "g": g} for T, f, L, g in product((24, 72), (3, 5), (4, 6), (0.01, 0.05))]
GRID = GRID_S + GRID_G          # grid order = tie-break order (first wins)
REF_VAL_SEED1 = 0.5852


class Graph:
    """Edges of one split. Per account, out- and in-edges sorted by time."""

    def __init__(self, src, dst, ts, rank, eid=None):
        self.src, self.dst = np.asarray(src, np.int64), np.asarray(dst, np.int64)
        self.ts, self.rank = np.asarray(ts, np.int64), np.asarray(rank, float)
        self.eid = np.arange(len(self.src)) if eid is None else np.asarray(eid, np.int64)
        order = np.argsort(self.ts, kind="stable")
        self.out, self.inn = defaultdict(list), defaultdict(list)
        for i in order.tolist():
            self.out[int(self.src[i])].append(i)
            self.inn[int(self.dst[i])].append(i)
        self.out_t = {a: [int(self.ts[i]) for i in l] for a, l in self.out.items()}
        self.in_t = {a: [int(self.ts[i]) for i in l] for a, l in self.inn.items()}
        self.deg = defaultdict(int)
        for a, l in self.out.items():
            self.deg[a] += len(l)
        for a, l in self.inn.items():
            self.deg[a] += len(l)

    def hub(self, a) -> bool:
        return self.deg[a] > HUB_DEG

    def _slice(self, lst, tl, lo, hi):
        return lst[bisect_left(tl, lo):bisect_right(tl, hi)] if lst else []

    def outs(self, a, lo, hi, ok):
        return [i for i in self._slice(self.out.get(a, []), self.out_t.get(a, []), lo, hi) if ok[i]]

    def ins(self, a, lo, hi, ok):
        return [i for i in self._slice(self.inn.get(a, []), self.in_t.get(a, []), lo, hi) if ok[i]]


def instances(G: Graph, s: int, T: int, f: int, L: int, ok: np.ndarray, stats: dict) -> list[frozenset]:
    """Instances (edge-index sets) containing seed edge s; `ok[i]` = edge i may be used."""
    u, v, t0 = int(G.src[s]), int(G.dst[s]), int(G.ts[s])
    lo, hi = t0 - T, t0 + T
    out = []
    # FAN-OUT / FAN-IN
    if not G.hub(u):
        e = G.outs(u, lo, hi, ok)
        if len(e) >= f:
            out.append(("FAN_OUT", frozenset(e) | {s}))
    if not G.hub(v):
        e = G.ins(v, lo, hi, ok)
        if len(e) >= f:
            out.append(("FAN_IN", frozenset(e) | {s}))

    # SCATTER-GATHER: seed as the scatter leg (a=u, m=v) or the gather leg (m=u, b=v)
    def sg(a, b):
        mids = {}
        if G.hub(a) or G.hub(b):
            return None
        first_out = {}
        for i in G.outs(a, lo, hi, ok):
            m = int(G.dst[i])
            if m != b and not G.hub(m) and m not in first_out:
                first_out[m] = i
        for m, i1 in first_out.items():
            for i2 in G.outs(m, int(G.ts[i1]) + 1, hi, ok):
                if int(G.dst[i2]) == b:
                    mids[m] = (i1, i2)
                    break
        if len(mids) >= 2:
            return frozenset(x for p in mids.values() for x in p)
        return None
    if not G.hub(v):
        for i in G.outs(v, t0 + 1, hi, ok):
            b = int(G.dst[i])
            if b != u:
                x = sg(u, b)
                if x is not None and s in x:
                    out.append(("SCATTER_GATHER", x))
    if not G.hub(u):
        for i in G.ins(u, lo, t0 - 1, ok):
            a = int(G.src[i])
            if a != v:
                x = sg(a, v)
                if x is not None and s in x:
                    out.append(("SCATTER_GATHER", x))

    # GATHER-SCATTER around m = v (seed in) or m = u (seed out)
    def gs(m):
        if G.hub(m):
            return None
        ins_, outs_ = G.ins(m, lo, hi, ok), G.outs(m, lo, hi, ok)
        if not ins_ or not outs_:
            return None
        t_last_out, t_first_in = int(G.ts[outs_[-1]]), int(G.ts[ins_[0]])
        ins_ = [i for i in ins_ if int(G.ts[i]) < t_last_out]
        outs_ = [i for i in outs_ if int(G.ts[i]) > t_first_in]
        if len({int(G.src[i]) for i in ins_}) >= 2 and len({int(G.dst[i]) for i in outs_}) >= 2:
            return frozenset(ins_) | frozenset(outs_)
        return None
    for m in (v, u):
        x = gs(m)
        if x is not None and s in x:
            out.append(("GATHER_SCATTER", x))

    # CYCLE through the seed: one time-ordered rotation e1 < ... < en with s = e_k.
    # Phase A walks from v with times > previous (> t0); at any account it may switch to phase B,
    # whose edges are increasing and < t0, and must end at u.
    if not G.hub(v) or v == u:
        steps = [0]
        found = []

        def dfs(a, path, accs, phase, last):
            if steps[0] >= CYCLE_STEPS or len(found) >= MAX_INST:
                return
            steps[0] += 1
            if len(path) + 2 > L:                 # the next edge plus the seed must fit in L
                return
            if phase == "A":
                cands = [("A", i) for i in G.outs(a, last + 1, hi, ok)]
                cands += [("B", i) for i in G.outs(a, lo, t0 - 1, ok)]
            else:
                cands = [("B", i) for i in G.outs(a, last + 1, t0 - 1, ok)]
            for ph, i in cands:
                b = int(G.dst[i])
                if b == u:
                    if len(path) + 2 >= 3:
                        found.append(frozenset(path + [i, s]))
                    continue
                if b in accs or G.hub(b):
                    continue
                dfs(b, path + [i], accs | {b}, ph, int(G.ts[i]))
        dfs(v, [], {u, v}, "A", t0)
        if steps[0] >= CYCLE_STEPS:
            stats["cycle_cap_bound"] = stats.get("cycle_cap_bound", 0) + 1
        out += [("CYCLE", c) for c in found]

    # BIPARTITE through the seed: sources S (into v), targets D (out of u), complete 2x2 blocks
    def bip(a, b, lo_, hi_):
        if G.hub(a) or G.hub(b):
            return None, None
        S = {a}
        D = {b}
        srcs = {int(G.src[i]) for i in G.ins(b, lo_, hi_, ok)} - {a, b}
        dsts = {int(G.dst[i]) for i in G.outs(a, lo_, hi_, ok)} - {a, b}
        for a2 in srcs:
            if G.hub(a2):
                continue
            hit = {int(G.dst[i]) for i in G.outs(a2, lo_, hi_, ok)} & dsts
            hit = {d for d in hit if not G.hub(d)}
            if hit:
                S.add(a2)
                D |= hit
        if len(S) < 2 or len(D) < 2:
            return None, None
        es = frozenset(i for x in S for i in G.outs(x, lo_, hi_, ok) if int(G.dst[i]) in D)
        return es, (S, D)
    b1, sd = bip(u, v, lo, hi)
    if b1 is not None and s in b1:
        out.append(("BIPARTITE", b1))
        S, D = sd
        tmax, tmin = max(int(G.ts[i]) for i in b1), min(int(G.ts[i]) for i in b1)
        # STACK: a second complete 2x2 layer after (from D) or before (into S)
        for d in sorted(D):
            for i in G.outs(d, tmax + 1, hi, ok):
                w = int(G.dst[i])
                b2, _ = bip(d, w, tmax + 1, hi)
                if b2 is not None:
                    out.append(("STACK", b1 | b2))
                    break
        for a_ in sorted(S):
            for i in G.ins(a_, lo, tmin - 1, ok):
                p = int(G.src[i])
                b2, _ = bip(p, a_, lo, tmin - 1)
                if b2 is not None:
                    out.append(("STACK", b1 | b2))
                    break

    uniq = {}
    for kind, es in out:
        uniq.setdefault(es, kind)
    ranked = sorted(uniq.items(), key=lambda kv: -float(np.mean(G.rank[list(kv[0])])))
    if len(ranked) > MAX_INST:
        stats["inst_cap_bound"] = stats.get("inst_cap_bound", 0) + 1
    for _, kind in ranked[:MAX_INST]:
        stats.setdefault("by_shape", {}).setdefault(kind, 0)
        stats["by_shape"][kind] += 1
    return [es for es, _ in ranked[:MAX_INST]]


def merge_groups(G: Graph, groups: list[frozenset], min_size: int = 3) -> list[tuple[set, set]]:
    """Union-find over edge groups sharing >= 2 accounts -> [(accounts, edges)] with >= min_size accounts."""
    accs = [set(G.src[list(g)].tolist()) | set(G.dst[list(g)].tolist()) for g in groups]
    parent = list(range(len(groups)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    by_acc = defaultdict(list)
    for gi, a in enumerate(accs):
        for x in a:
            by_acc[x].append(gi)
    for gi, a in enumerate(accs):
        cnt = defaultdict(int)
        for x in a:
            for gj in by_acc[x]:
                if gj > gi:
                    cnt[gj] += 1
        for gj, c in cnt.items():
            if c >= 2:
                parent[find(gj)] = find(gi)
    comp = defaultdict(lambda: (set(), set()))
    for gi, g in enumerate(groups):
        r = find(gi)
        comp[r][0].update(accs[gi])
        comp[r][1].update(g)
    return [(a, e) for a, e in comp.values() if len(a) >= min_size]


def seed_components(G: Graph, seeds: np.ndarray) -> list[frozenset]:
    """Connected components (shared account) of the seed edges, any size."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for i in seeds.tolist():
        parent[find(int(G.src[i]))] = find(int(G.dst[i]))
    comp = defaultdict(set)
    for i in seeds.tolist():
        comp[find(int(G.src[i]))].add(i)
    return [frozenset(c) for c in comp.values()]


def run_cell(G: Graph, seeds: np.ndarray, cell: dict) -> tuple[list, dict]:
    T = int(cell["T_h"] * H)
    ok = np.ones(len(G.src), bool)
    if cell["variant"] == "M2-G":
        ok = G.rank >= 1.0 - cell["g"]
        ok[seeds] = True
    stats = {"n_seeds": int(len(seeds))}
    groups = seed_components(G, seeds)
    n_inst = 0
    for s in seeds.tolist():
        inst = instances(G, s, T, cell["f"], cell["L"], ok, stats)
        n_inst += len(inst)
        groups += inst
    stats["n_instances"] = n_inst
    rings = merge_groups(G, groups)
    return rings, stats


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_split(split: str, S: int):
    from contract.make_scored_edges import load_paths
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.scored_edges import build_scored_edges
    pdir = load_paths()["processed_dir"]
    se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
    rank = se["score_raw"].rank(method="average").to_numpy() / len(se)
    G = Graph(se["from_id"], se["to_id"], se["timestamp"], rank, se["edge_id"])
    seeds = np.flatnonzero(seed_mask_for_pct(se[SELECT_COL].to_numpy(float), K_PCT))
    return G, seeds, pdir


def cmd_grid(a):
    from evaluation.ring_metrics import evaluate_rings
    from ringshield.truth import load_ground_truth, split_window
    t0 = time.time()
    G, seeds, pdir = load_split("val", a.seed)
    truth, pat = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *split_window(pdir / "amlworld_val.parquet"),
                                   "test_visible", verbose=False)
    out = OUT / "val" / f"seed{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    cells = GRID if a.cells is None else [GRID[i] for i in a.cells]
    rows = []
    for cell in cells:
        t1 = time.time()
        rings, st = run_cell(G, seeds, cell)
        m = evaluate_rings([r[0] for r in rings], truth, 0.5, pat)
        row = {**cell, "ring_f1": float(m.ring_f1), "ring_precision": float(m.ring_precision), "ring_recall": float(m.ring_recall),
               "n_rings": len(rings), "n_accounts": len(set().union(*[r[0] for r in rings])) if rings else 0,
               "seconds": round(time.time() - t1, 1), **{k: v for k, v in st.items() if k != "by_shape"},
               "by_shape": json.dumps(st.get("by_shape", {}))}
        rows.append(row)
        print({k: row[k] for k in ("variant", "T_h", "f", "L") } | {"g": cell.get("g"), "F1": round(row["ring_f1"], 4),
              "rings": row["n_rings"], "s": row["seconds"], "inst_cap": st.get("inst_cap_bound", 0),
              "cyc_cap": st.get("cycle_cap_bound", 0)}, flush=True)
    tag = "" if a.cells is None else "_" + "-".join(map(str, a.cells))
    pd.DataFrame(rows).to_csv(out / f"grid{tag}.csv", index=False)
    print(f"[m2] {len(rows)} cells in {time.time() - t0:.0f}s -> {out}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("grid"); p.add_argument("--seed", type=int, required=True)
    p.add_argument("--cells", type=int, nargs="*", default=None, help="grid indices (default all 24, in order)")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    {"grid": cmd_grid}[a.cmd](a)


if __name__ == "__main__":
    main()
