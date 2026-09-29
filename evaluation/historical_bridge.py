"""14.1a: can the missing members of under-covered rings be reached through HISTORY?

    python evaluation/historical_bridge.py --dry-run     # seed 1, control check only
    python evaluation/historical_bridge.py

`FINDINGS.md` B13: 80.7 % of the missing members of under-covered rings have no path to the
recovered fragment *inside the evaluation window* (STACK 140/140). Candidate generation only ever
sees the split's own edges, but the detector's loader already samples the full past and an analyst
on test day 9 can see days 0-8 — those transactions are observable, only their labels are not. So
this asks whether the path exists through **earlier** edges.

The walk mirrors `ringshield.expand.candidates`: from an included edge at an account, step to edges
incident to that account within the run's own **val-chosen Δt**, capped at `MAX_EVENTS_PER_QUERY`
per query. Two differences, both deliberate:

* the graph is **every edge of the dataset**, not the split's — days 0-8 are reachable from a day-9
  seed, and at Δt = 72 h that crosses into the train split;
* the walk is **backwards in time**: no edge later than the fragment's latest seed is ever
  traversed, which is the causal constraint an analyst at detection time actually has.

Verdict criteria are pre-registered in `docs/HISTORICAL_BRIDGE.md` and were written before this ran.
Column (f) is the null — the identical walk from random non-ring fragments — because day 0 holds
34 % of the edges at 10x density (C8) and a backward walk through that will find hub paths whether
or not laundering structure connects them.

Outputs `results/tables/r_historical_bridge.csv` (one row per missing edge) and `.json` (the
aggregate table the doc quotes, including the B13 control).
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.expand.candidates import MAX_EVENTS_PER_QUERY  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

ROOT = REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average"
SCORES = REPO_ROOT / "experiments" / "R1_gine_causal"
SEEDS = [1, 2, 3, 4, 5]


class TimeGraph:
    """Every edge of the dataset, indexed by account and sorted by time."""

    def __init__(self, edges: pd.DataFrame):
        self.eid = edges["EdgeID"].to_numpy(np.int64)
        self.ts = edges["Timestamp"].to_numpy(np.int64)
        self.ring = edges["ring_id"].to_numpy(np.int64)
        self.frm = edges["from_id"].to_numpy(np.int64)
        self.to = edges["to_id"].to_numpy(np.int64)
        self.pos = {int(e): i for i, e in enumerate(self.eid)}
        acc = np.concatenate([self.frm, self.to])
        pos = np.concatenate([np.arange(len(self.eid)), np.arange(len(self.eid))])
        t = np.concatenate([self.ts, self.ts])
        order = np.lexsort((t, acc))
        self.a_acc, self.a_pos, self.a_ts = acc[order], pos[order], t[order]
        uniq, start = np.unique(self.a_acc, return_index=True)
        self.start = dict(zip(uniq.tolist(), start.tolist()))
        self.end = dict(zip(uniq.tolist(), (list(start[1:]) + [len(self.a_acc)])))

    def neighbours(self, account: int, t: int, delta: int, t_max: int, cap: int) -> np.ndarray:
        """Edge positions incident to `account` within [t-delta, t+delta] and NOT later than t_max."""
        s = self.start.get(int(account))
        if s is None:
            return np.zeros(0, dtype=np.int64)
        e = self.end[int(account)]
        seg_ts = self.a_ts[s:e]
        lo = s + int(np.searchsorted(seg_ts, t - delta, "left"))
        hi = s + int(np.searchsorted(seg_ts, min(t + delta, t_max), "right"))
        if hi <= lo:
            return np.zeros(0, dtype=np.int64)
        out = self.a_pos[lo:hi]
        if cap and len(out) > cap:                      # Step 6 cap, applied to historical hops too
            keep = np.argsort(np.abs(self.a_ts[lo:hi] - t), kind="stable")[:cap]
            out = out[keep]
        return out

    def reach(self, start_pos, targets: set, delta: int, t_max: int, max_hops: int, cap: int,
              max_visits: int = 400_000) -> tuple[dict, bool]:
        """BFS backwards through history. Returns ({target_pos: (hops, min_ts, via_ring_ids)}, truncated).

        `max_visits` bounds the frontier: with a 500-edge cap per query the third hop can branch into
        millions, and an unbounded walk would be measuring how long we were willing to wait. When the
        budget is exhausted the result is marked truncated, and a target not found under truncation is
        recorded as `unknown` rather than `unreachable` -- the distinction matters for the verdict."""
        seen = {int(p): 0 for p in start_pos}
        parent: dict = {int(p): None for p in start_pos}
        found: dict = {}
        truncated = False
        q = deque((int(p), 0) for p in start_pos)
        while q:
            if len(seen) > max_visits:
                truncated = True
                break
            p, h = q.popleft()
            if h >= max_hops:
                continue
            for a in (self.frm[p], self.to[p]):
                for nxt in self.neighbours(int(a), int(self.ts[p]), delta, t_max, cap):
                    nxt = int(nxt)
                    if nxt in seen:
                        continue
                    seen[nxt] = h + 1
                    parent[nxt] = p
                    if nxt in targets:
                        path, cur = [], nxt
                        while cur is not None:
                            path.append(cur)
                            cur = parent[cur]
                        found[nxt] = (h + 1, int(self.ts[path].min()),
                                      [int(self.ring[x]) for x in path[1:-1]])
                    q.append((nxt, h + 1))
        return found, truncated


def in_window_disconnected(ring_edges: pd.DataFrame, included: set, in_win: set) -> tuple[int, int]:
    """B13's control: distance through the ring's own in-window edges."""
    g = ring_edges[ring_edges["EdgeID"].isin(in_win)]
    adj: dict = {}
    for r in g.itertuples():
        adj.setdefault(r.from_id, []).append(r.EdgeID)
        adj.setdefault(r.to_id, []).append(r.EdgeID)
    ends = {r.EdgeID: (r.from_id, r.to_id) for r in g.itertuples()}
    inc = set(included) & set(ends)
    if not inc:
        return 0, 0
    dist = {e: 0 for e in inc}
    q = deque(inc)
    while q:
        e = q.popleft()
        for a in ends[e]:
            for f in adj[a]:
                if f not in dist:
                    dist[f] = dist[e] + 1
                    q.append(f)
    missing = set(ends) - inc
    return len(missing), sum(1 for m in missing if m not in dist)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=SEEDS)
    ap.add_argument("--max-hops", type=int, default=2, help="shipped value; also swept in the report")
    ap.add_argument("--hop-sweep", type=int, nargs="*", default=[2, 3])
    ap.add_argument("--n-null", type=int, default=200, help="random non-ring fragments for column (f)")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r_historical_bridge.csv")
    ap.add_argument("--dry-run", action="store_true", help="seed 1 only; prints the B13 control and stops")
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    cols = ["EdgeID", "from_id", "to_id", "Timestamp", "ring_id"]
    full = pd.concat([pd.read_parquet(pdir / f"amlworld_{s}.parquet", columns=cols)
                      for s in ("train", "val", "test")], ignore_index=True).sort_values("EdgeID")
    print(f"[bridge] full graph: {len(full):,} edges, days "
          f"{int(full.Timestamp.min()//86400)}-{int(full.Timestamp.max()//86400)}")
    G = TimeGraph(full)
    ring_edges = {int(r): g for r, g in full[full.ring_id > 0].groupby("ring_id")}

    rows, ctrl_tot, ctrl_disc = [], 0, 0
    FRAGMENTS: list = []
    classb_rows = []
    seeds = a.seeds[:1] if a.dry_run else a.seeds
    for s in seeds:
        cfg = yaml.safe_load((ROOT / f"seed{s}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        delta = int(round(float(cfg["delta_t_h"]) * 3600))
        se = build_scored_edges(SCORES / f"scores_test_seed{s}.parquet", "test",
                                model_id="gine_causal", seed=s, processed_dir=pdir)
        rings = read_rings_any(ROOT / f"seed{s}" / "rings.parquet")
        kl = classify(rings, se, truth, patterns, W).set_index("ring_id")
        ts = se.set_index("edge_id")["timestamp"]
        in_win = set(ts.index[W.mask(ts.values)].tolist())
        pred = restrict_rings(rings, se, W)
        kept = [i for i, r in enumerate(rings) if any(e in in_win for e in r.member_edges)]
        matched = {m.truth_id for m in match_rings(pred, truth, 0.5)[0]}
        mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
        seed_ids = set(se.loc[mask, "edge_id"]) & in_win

        for tid, accs in truth.items():
            klass = kl.loc[tid, "klass"]
            if tid in matched or klass not in ("c_under_covered", "b_untouched"):
                continue
            pat = patterns.get(tid, "?")
            g = ring_edges.get(int(tid))
            if g is None:
                continue
            if klass == "c_under_covered":
                bj, bi = 0.0, None
                for j, P in enumerate(pred):
                    it = len(P & accs)
                    if it and it / len(P | accs) > bj:
                        bj, bi = it / len(P | accs), j
                if bi is None:
                    continue
                ring = rings[kept[bi]]
                frag = [e for e in ring.member_edges if e in in_win]
            else:                                   # class (b): no fragment -- start from ALL seeds
                frag = sorted(seed_ids)
            if not frag:
                continue
            n_miss, n_disc = in_window_disconnected(g, set(frag), in_win)
            if klass == "c_under_covered":
                ctrl_tot += n_miss
                ctrl_disc += n_disc
            if a.dry_run:
                continue

            start_pos = [G.pos[e] for e in frag if e in G.pos]
            if not start_pos:
                continue
            t_max = int(max(G.ts[p] for p in start_pos))
            miss_ids = sorted(set(g["EdgeID"].astype(int)) & in_win) if klass == "c_under_covered" else \
                sorted(set(g["EdgeID"].astype(int)))
            miss_ids = [e for e in miss_ids if e not in set(frag)]
            targets = {G.pos[e] for e in miss_ids if e in G.pos}
            if not targets:
                continue
            if klass == "c_under_covered":
                FRAGMENTS.append((start_pos, sorted(targets), delta, t_max))
            for H in ([a.max_hops] if klass == "b_untouched" else a.hop_sweep):
                found, trunc = G.reach(start_pos, targets, delta, t_max, H, MAX_EVENTS_PER_QUERY)
                for tp in targets:
                    hit = found.get(tp)
                    via = hit[2] if hit else []
                    rows.append({
                        "seed": s, "ring_id": int(tid), "klass": klass, "pattern": pat,
                        "max_hops": H, "delta_t_h": cfg["delta_t_h"],
                        "edge_id": int(G.eid[tp]), "reached": hit is not None,
                        "hops": hit[0] if hit else np.nan,
                        "reach_back_s": (t_max - hit[1]) if hit else np.nan,
                        "n_bridge_edges": len(via),
                        "n_bridge_same_ring": sum(1 for r in via if r == int(tid)),
                        "n_bridge_other_ring": sum(1 for r in via if r > 0 and r != int(tid)),
                        "n_bridge_non_ring": sum(1 for r in via if r <= 0),
                        "search_truncated": trunc})
        print(f"  seed {s}: control so far {ctrl_disc}/{ctrl_tot} disconnected in-window "
              f"({ctrl_disc/max(ctrl_tot,1)*100:.1f} %)", flush=True)

    print(f"\n(b) CONTROL — disconnected in-window: {ctrl_disc}/{ctrl_tot} = "
          f"{ctrl_disc/max(ctrl_tot,1)*100:.1f} %   [B13 says 80.7 %]")
    if a.dry_run:
        print("[bridge] DRY RUN -- control only, nothing written")
        return None

    d = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)

    # ---- null: PERMUTATION control -------------------------------------------------------------
    # Pairing a random fragment with random targets in a 5 M-edge graph reaches 0 % by construction
    # and proves nothing. The informative null keeps the real fragments and the real target sets and
    # only destroys the pairing: each fragment is walked toward ANOTHER ring's missing edges. Size,
    # position in time and account degree are all preserved; only the true correspondence is gone.
    rng = np.random.default_rng(0)
    pairs = [(f, t, d, tm) for (f, t, d, tm) in FRAGMENTS]
    null_hits = null_tot = 0
    if len(pairs) > 1:
        perm = rng.permutation(len(pairs))
        for i, j in enumerate(perm):
            if i == j:
                j = (j + 1) % len(pairs)
            frag, _, dlt, tmx = pairs[i]
            _, tgt, _, _ = pairs[j]
            if not frag or not tgt:
                continue
            f, _ = G.reach(frag, set(tgt), dlt, tmx, a.max_hops, MAX_EVENTS_PER_QUERY)
            null_hits += len(f)
            null_tot += len(tgt)
    null_rate = null_hits / max(null_tot, 1)
    print(f"(f) NULL — permuted fragment/target pairing: {null_hits}/{null_tot} = {null_rate*100:.1f} % "
          f"reached at max_hops {a.max_hops}")

    uc = d[(d.klass == "c_under_covered") & (d.max_hops == a.max_hops)]
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "control_disconnected_in_window": {"n": ctrl_tot, "disconnected": ctrl_disc,
                                                  "share": ctrl_disc / max(ctrl_tot, 1)},
               "null_rate": null_rate, "max_hops": a.max_hops,
               "by_pattern": {}, "hop_sweep": {}, "class_b": {}}
    print(f"\n(c) HISTORICAL reach at max_hops {a.max_hops}, under-covered rings:")
    for pat, g in uc.groupby("pattern"):
        r = float(g["reached"].mean())
        same = int(g["n_bridge_same_ring"].sum())
        tot_b = int(g["n_bridge_edges"].sum())
        summary["by_pattern"][pat] = {"n_missing": int(len(g)), "reached": int(g["reached"].sum()),
                                      "share": r, "bridge_edges": tot_b, "bridge_same_ring": same,
                                      "share_bridge_same_ring": (same / tot_b) if tot_b else None,
                                      "median_hops": float(g.loc[g.reached, "hops"].median()) if g["reached"].any() else None,
                                      "median_reach_back_h": float(g.loc[g.reached, "reach_back_s"].median() / 3600) if g["reached"].any() else None}
        sp = summary["by_pattern"][pat]
        print(f"   {pat:16s} {int(g['reached'].sum()):4d}/{len(g):4d} = {r*100:5.1f} % | "
              f"bridge same-ring {sp['share_bridge_same_ring'] if sp['share_bridge_same_ring'] is None else round(sp['share_bridge_same_ring'],3)} | "
              f"median hops {sp['median_hops']} | back {sp['median_reach_back_h']} h")
    for H, g in d[d.klass == "c_under_covered"].groupby("max_hops"):
        summary["hop_sweep"][int(H)] = float(g["reached"].mean())
    print(f"\n(d) hop sweep (all under-covered): " +
          ", ".join(f"{h}: {v*100:.1f} %" for h, v in sorted(summary["hop_sweep"].items())))
    cb = d[d.klass == "b_untouched"]
    if len(cb):
        summary["class_b"] = {"n_rings": int(cb["ring_id"].nunique()),
                              "n_missing": int(len(cb)), "reached": int(cb["reached"].sum()),
                              "share": float(cb["reached"].mean())}
        print(f"\nclass (b) untouched rings: {int(cb['reached'].sum())}/{len(cb)} member edges reached "
              f"= {cb['reached'].mean()*100:.1f} % over {cb['ring_id'].nunique()} rings")
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(summary, indent=2, default=str),
                                                         encoding="utf-8")
    print(f"\n-> {a.out}")
    return summary


if __name__ == "__main__":
    main()
