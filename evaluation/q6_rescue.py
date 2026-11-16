"""Q6: undersized-group rescue (paper/PREREG_Q_2026-11-15.md, section Q6).

    CUDA_VISIBLE_DEVICES="" python -m evaluation.q6_rescue --split val --seeds 1 2 3 4 5
    CUDA_VISIBLE_DEVICES="" python -m evaluation.q6_rescue --split test --cells-from experiments/Q6_rescue/choices.json

Shipped full pipeline per detector seed (route of evaluation.q0_loss_decomposition.build_full_rings).
A group = connected component of the shipped included edges (seeds + additions at p_min 0.7).
Groups with < 3 accounts are re-expanded from their own seeds under each grid cell
(p_min, hops); groups with >= 3 accounts and the shipped rings are left unchanged. Rescued edges
that touch an account of a shipped >= 3-account group are dropped. Each connected component of the
rescued edges (seeds + kept additions) with >= 3 accounts becomes one extra ring.

Hop 3 (not supported by ringshield/expand/candidates.py, which is read-only here) is added by
wrapping `candidates`: from each hop-2 candidate's far endpoint, the events within delta_t of that
candidate, under the same per-query event cap and the seed time window. Features of a hop-3 row are
computed as if it were a hop-2 row whose touching edge is its hop-2 parent; the `hop` feature is then
set to 3, a value the policy never saw in training (it extrapolates).

Trajectories are run once per (group, hops) down to p_floor 0.1, and the higher p_min cells are
their prefixes (ringshield.aggregators.expand.truncate, the repository's convention).

Outputs experiments/Q6_rescue/<split>/<cell>/seed<S>/rings.parquet (minimal schema: ring_id,
members, member_edges; shipped rings + rescued rings), plus rescue_stats.json per seed.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import ringshield.aggregators.expand as EX  # noqa: E402
from ringshield.expand import candidates as CM  # noqa: E402

E2E = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"   # read-only embeddings / checkpoints
OUT = REPO_ROOT / "experiments" / "Q6_rescue"
SHIPPED = (0.7, 2)
GRID = [(0.7, 2), (0.5, 2), (0.3, 2), (0.1, 2), (0.7, 3), (0.5, 3), (0.3, 3), (0.1, 3)]
P_FLOOR = 0.1


def cell_name(p, h):
    return f"p{p:.1f}_h{h}"


# ----------------------------------------------------------------------------- hop 3
_orig_candidates = CM.candidates
_orig_features = EX.compute_features


def candidates_h3(scored_edges, included_edge_ids, delta_t_h, max_hops=2, *, index=None,
                  max_events_per_query=CM.MAX_EVENTS_PER_QUERY, time_bounds=None):
    if max_hops <= 2:
        return _orig_candidates(scored_edges, included_edge_ids, delta_t_h, max_hops, index=index,
                                max_events_per_query=max_events_per_query, time_bounds=time_bounds)
    idx = index or CM.index_for(scored_edges)
    df = _orig_candidates(scored_edges, included_edge_ids, delta_t_h, 2, index=idx,
                          max_events_per_query=max_events_per_query, time_bounds=None)
    win = df.attrs.get("window")
    if time_bounds is not None:
        win = (int(time_bounds[0]), int(time_bounds[1]))
    h2 = df[df["hop"] == 2]
    if len(h2):
        delta = int(round(float(delta_t_h) * 3600))
        c2 = idx.pos_of(h2["candidate_edge_id"].to_numpy())
        s2 = np.searchsorted(idx.acc_uniq, h2["shared_account"].to_numpy())
        far = np.where(idx.from_dense[c2] == s2, idx.to_dense[c2], idx.from_dense[c2])
        ok = far != s2
        c2, far, a2 = c2[ok], far[ok], idx.pos_of(h2["anchor_edge_id"].to_numpy()[ok])
        t_via = idx.ts[c2]
        lo, hi = idx.window(far, t_via - delta, t_via + delta)
        if max_events_per_query:
            lo, hi, _ = CM._truncate(idx, lo, hi, t_via, max_events_per_query)
        rows, ev = idx.expand(lo, hi)
        c3 = idx.ev_pos[ev]
        seen = np.zeros(idx.n_edges, dtype=bool)
        seen[idx.pos_of(np.asarray(list(included_edge_ids), dtype=np.int64))] = True
        seen[idx.pos_of(df["candidate_edge_id"].to_numpy())] = True
        keep = ~seen[c3]
        rows, c3 = rows[keep], c3[keep]
        via, a3, s3 = c2[rows], a2[rows], far[rows]
        g3, gv3 = idx.ts[c3] - idx.ts[a3], idx.ts[c3] - idx.ts[via]
        c3, a3, s3, g3, via, gv3 = CM._dedupe(c3, a3, s3, g3, via, gv3, gv3)
        h3 = pd.DataFrame({"candidate_edge_id": idx.edge_id[c3], "anchor_edge_id": idx.edge_id[a3],
                           "shared_account": idx.acc_uniq[s3], "hop": np.full(len(c3), 3, np.int64), "gap_s": g3,
                           "via_edge_id": idx.edge_id[via], "gap_via_s": gv3, "n_anchors": np.zeros(len(c3), np.int64)})
        df = pd.concat([df, h3], ignore_index=True)
    if win is not None:
        t = idx.ts[idx.pos_of(df["candidate_edge_id"].to_numpy())]
        df = df[(t >= win[0]) & (t <= win[1])]
    df = df.sort_values(["hop", "candidate_edge_id"]).reset_index(drop=True)
    for c in CM.COLUMNS:
        df[c] = df[c].astype(np.int64)
    assert df["candidate_edge_id"].is_unique
    return df


def features_h3(ctx, cand, included, delta_t_h, *a, **k):
    is3 = (cand["hop"] == 3).to_numpy()
    if not is3.any():
        return _orig_features(ctx, cand, included, delta_t_h, *a, **k)
    c = cand.copy()
    c.loc[is3, "hop"] = 2
    X = _orig_features(ctx, c, included, delta_t_h, *a, **k)
    X.loc[is3, "hop"] = 3
    return X


EX.candidates = candidates_h3
EX.compute_features = features_h3


# ----------------------------------------------------------------------------- pure rescue step
def rescued_rings(groups: list[dict], big_accounts: set, edge_ends: dict, p_min: float) -> list[dict]:
    """groups: [{"seeds": [eid], "adds": [(eid, p, ...)]}] for undersized groups at one hop setting.
    edge_ends: eid -> (from_acc, to_acc). Returns [{"members": set, "member_edges": list}] with >= 3 accounts."""
    edges = []
    for g in groups:
        take = list(g["seeds"]) + EX.truncate(g, p_min)
        for e in take:
            a, b = edge_ends[e]
            if a in big_accounts or b in big_accounts:
                continue
            edges.append(e)
    parent = {}

    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in set(edges):
        a, b = edge_ends[e]
        parent[find(a)] = find(b)
    comp = defaultdict(lambda: {"members": set(), "member_edges": []})
    for e in sorted(set(edges)):
        a, b = edge_ends[e]
        r = comp[find(a)]
        r["members"] |= {a, b}
        r["member_edges"].append(e)
    return [r for r in comp.values() if len(r["members"]) >= 3]


# ----------------------------------------------------------------------------- driver
def run_seed(S: int, split: str, cells: list[tuple[float, int]]):
    import yaml
    from preprocessing.account_bank import load_paths
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.aggregators.full import component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters
    from ringshield.expand.context import build_context
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    from ringshield.partition.pairs import components_of
    from ringshield.scored_edges import build_scored_edges
    pdir = load_paths()["processed_dir"]
    R1, R3, R4 = (REPO_ROOT / "experiments" / d for d in ("R1_gine_causal", "R3_expansion", "R4_partition"))
    r3 = yaml.safe_load((R3 / "runs/proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    r4 = yaml.safe_load((R4 / "runs/average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    assert (float(r3["p_min"]), float(r3["delta_t_h"]), float(r3["seed_frac_pct"])) == (0.7, 24.0, 0.1), r3
    se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
    emb = R1 / f"embeddings_{split}_seed{S}.parquet"
    emb = emb if emb.exists() else E2E / f"embeddings_{split}_seed{S}.parquet"
    ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet", embeddings_parquet=emb,
                        checkpoint=E2E / f"model_best_seed{S}.pt")
    policy = Policy.load(R3 / "policy_proposed")
    mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
    trajs = EX.expand_all(se, mask, policy, ctx, delta_t_h=24.0, p_floor=0.7)
    inc_pos, is_seed = included_from_trajectories(se, mask, trajs, 0.7)
    comp = components_of(ctx.idx, inc_pos)
    P = component_pairs(ctx, inc_pos, is_seed, comp, Affinity.load(R4 / "affinity"))
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=3,
                           **{k: r4[k] for k in ("cut", "threshold", "gap_h", "resolution") if k in r4})
    shipped = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, 3)

    idx = ctx.idx
    f_acc, t_acc = idx.acc_uniq[idx.from_dense[inc_pos]], idx.acc_uniq[idx.to_dense[inc_pos]]
    accs = defaultdict(set)
    for c, a, b in zip(comp, f_acc, t_acc):
        accs[c] |= {int(a), int(b)}
    small_all = sorted(c for c, s in accs.items() if len(s) < 3)
    has_seed = set(comp[is_seed].tolist())
    small = [c for c in small_all if c in has_seed]      # seedless groups (a hop-2 addition whose hop-1 link
                                                         # was not included) have nothing to re-expand from
    big_accounts = set().union(*(s for c, s in accs.items() if len(s) >= 3))
    eid_inc = idx.edge_id[inc_pos]
    e_from = dict(zip(se["edge_id"].to_numpy(), se["from_id"].to_numpy()))
    e_to = dict(zip(se["edge_id"].to_numpy(), se["to_id"].to_numpy()))
    stats = {"seed": S, "split": split, "n_groups": len(accs), "n_undersized": len(small_all),
             "n_undersized_seedless_skipped": len(small_all) - len(small), "cells": {}}
    traj_by_h = {}
    for h in sorted({h for _, h in cells}):
        t0 = time.time()
        traj_by_h[h] = [EX.expand_component(se, [int(e) for e in eid_inc[(comp == c) & is_seed]], policy, ctx,
                                            delta_t_h=24.0, p_floor=P_FLOOR, max_hops=h) for c in small]
        stats[f"seconds_h{h}"] = round(time.time() - t0, 1)
        print(f"  seed {S} {split} hops {h}: {len(small)} groups re-expanded in {stats[f'seconds_h{h}']}s", flush=True)
    base = [{"members": sorted(int(a) for a in r.members), "member_edges": [int(e) for e in r.member_edges]} for r in shipped]
    for p, h in cells:
        groups = traj_by_h[h]
        ends = {}
        for g in groups:
            for e in list(g["seeds"]) + [x[0] for x in g["adds"]]:
                ends[e] = (int(e_from[e]), int(e_to[e]))
        extra = rescued_rings(groups, big_accounts, ends, p)
        n_add = sum(len(EX.truncate(g, p)) for g in groups)
        rows = base + [{"members": sorted(r["members"]), "member_edges": r["member_edges"]} for r in extra]
        d = OUT / split / cell_name(p, h) / f"seed{S}"
        d.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"ring_id": np.arange(len(rows)), "members": [r["members"] for r in rows],
                      "member_edges": [r["member_edges"] for r in rows]}).to_parquet(d / "rings.parquet", index=False)
        stats["cells"][cell_name(p, h)] = {"n_additions": n_add, "n_rescued_rings": len(extra),
                                           "n_rescued_accounts": int(sum(len(r["members"]) for r in extra)),
                                           "n_shipped_rings": len(base)}
        print(f"  {cell_name(p, h)}: additions {n_add}, rescued rings {len(extra)}", flush=True)
    (OUT / split / f"rescue_stats_seed{S}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


def select(seeds: list[int]) -> dict:
    """Validation ring-F1 (test_visible, tau 0.5) of every cell per seed; choose by the registered rule
    (highest; ties -> higher p_min, then fewer hops). Writes choices.json and val_grid.csv."""
    import subprocess
    rows = []
    for S in seeds:
        for p, h in GRID:
            c = cell_name(p, h)
            d = OUT / "val" / c / f"seed{S}"
            sc = OUT / "val_scored" / c / f"seed{S}"
            if not (sc / "summary.csv").exists():
                subprocess.run([sys.executable, str(REPO_ROOT / "evaluation" / "score_external.py"), "--rings", str(d / "rings.parquet"),
                                "--split", "val", "--window", "val", "--conventions", "test_visible", "--thresholds", "0.5",
                                "--n-boot", "10", "--out", str(sc)], check=True, capture_output=True)
            m = pd.read_csv(sc / "summary.csv").iloc[0]
            rows.append({"seed": S, "cell": c, "p_min": p, "hops": h, "val_ring_f1": float(m["ring_f1"]),
                         "val_ring_precision": float(m["ring_precision"]), "val_ring_recall": float(m["ring_recall"]),
                         "predicted_per_run": float(m["predicted_per_run"])})
    g = pd.DataFrame(rows)
    g.to_csv(OUT / "val_grid.csv", index=False)
    choices = {}
    for S, x in g.groupby("seed"):
        x = x.assign(r=x["val_ring_f1"].round(12)).sort_values(["r", "p_min", "hops"], ascending=[False, False, True])
        b = x.iloc[0]
        choices[str(S)] = {"p_min": float(b["p_min"]), "hops": int(b["hops"]), "val_ring_f1": float(b["val_ring_f1"]),
                           "shipped_val_ring_f1": float(x[(x.p_min == 0.7) & (x.hops == 2)]["val_ring_f1"].iloc[0])}
    (OUT / "choices.json").write_text(json.dumps(choices, indent=2), encoding="utf-8")
    return choices


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["val", "test"], default=None)
    ap.add_argument("--select", action="store_true", help="score the validation grid and write choices.json")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--cells-from", type=Path, default=None, help="choices.json: run only each seed's chosen cell")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.select:
        print(json.dumps(select(a.seeds), indent=2))
        return
    assert a.split, "--split required"
    if a.split == "test":
        assert a.cells_from, "test runs only the validation-chosen cells (--cells-from choices.json)"
    choices = json.loads(a.cells_from.read_text(encoding="utf-8")) if a.cells_from else None
    for S in a.seeds:
        if choices:
            p, h = choices[str(S)]["p_min"], choices[str(S)]["hops"]
            cells = [(p, h)] if (p, h) != SHIPPED else [SHIPPED]
        else:
            cells = GRID
        run_seed(S, a.split, cells)


if __name__ == "__main__":
    main()
