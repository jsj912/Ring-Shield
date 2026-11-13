"""HI-Medium pre-registration close-out runs (deep-analysis #7). One detector seed per process.

    set RINGSHIELD_PATHS=<paths yaml for HI-Medium>
    python evaluation/hm_closeout.py --seed 1 --exp-dir E:/JSJ/Ring-Shield/experiments_hi_medium

Everything is the registered, val-chosen HI-Medium configuration (results/tables/v33_a12_val_chosen.json):
policy variant no_detector, p_min 0.9, delta_t 48 h, k* 0.1 %, min_size 3, partition average cut 0.3.
B1b (rule_q) has no recorded HI-Medium cell, so its delta_t is chosen per seed on HI-Medium validation
from the registered grid {24, 48, 72} h (highest val ring-F1, ties -> smaller), never on test.

Amendment 15 (2026-11-12): tie-safe top-k seed cut; primary = days 6-14 (budget over the window); day 15 run alone.
Runs per seed (Amendments 13 and 14):
  primary   days 6-15, context = whole test split; budget rules: global (registered) and per_day
  block     each of 6-7, 8-9, 10-11, 12-13, 14-15; context = the block's edges only (run as validation
            is run); budget rules: global (quantile within the block) and per_day
Methods per run: b0 (cc of the seeds), b1b (rule_q expansion, components), proposed (policy expansion,
plain components = b2), full (partition average). Rings are written to <out>/<window>/<rule>/<method>/
seed<S>.parquet; P1-P4 are computed from them by evaluation/hm_closeout_report.py.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from evaluation.window_budget import cc_rings_from_mask  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.rings import write_rings_parquet  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import Window, load_windows  # noqa: E402

CHOSEN = json.loads((REPO_ROOT / "results/tables/v33_a12_val_chosen.json").read_text(encoding="utf-8"))["chosen"]
K, MIN_SIZE, DT, PMIN, CUT = (float(CHOSEN["seed_frac_pct"]), int(CHOSEN["min_size"]), float(CHOSEN["delta_t_h"]),
                              float(CHOSEN["p_min"]), float(CHOSEN["cut"]))
BLOCKS = [(6, 7), (8, 9), (10, 11), (12, 13), (14, 15)]
B1B_GRID = [24.0, 48.0, 72.0]


def topk_mask(scores, edge_ids, pct=None):
    """Amendment 15: the floor(n*k/100) highest scores, ties broken by ascending edge_id (NaN never a seed)."""
    pct = K if pct is None else pct
    s = np.asarray(scores, dtype=float)
    ok = ~np.isnan(s)
    n_k = int(np.floor(ok.sum() * pct / 100.0))
    m = np.zeros(len(s), dtype=bool)
    if n_k:
        idx = np.flatnonzero(ok)
        order = np.lexsort((np.asarray(edge_ids)[idx], -s[idx]))
        m[idx[order[:n_k]]] = True
    return m


def per_day_mask(scores, ts, day_of, edge_ids, base=None):
    days = day_of(ts)
    m = np.zeros(len(scores), dtype=bool)
    base = np.ones(len(scores), dtype=bool) if base is None else base
    for d in np.unique(days[base]):
        sel = (days == d) & base
        m[sel] = topk_mask(scores[sel], edge_ids[sel])
    return m


def build_methods(se, ctx, mask, policy, rule, affinity, dt_b1b):
    out = {"b0": cc_rings_from_mask(se, mask, MIN_SIZE)}
    for name, pol, dt, pf in (("proposed", policy, DT, PMIN), ("b1b", rule, dt_b1b, 0.5)):
        trajs = expand_all(se, mask, pol, ctx, delta_t_h=dt, p_floor=pf)
        inc_pos, is_seed = included_from_trajectories(se, mask, trajs, pf)
        comp = components_of(ctx.idx, inc_pos)
        lab_b2 = partition_labels(ctx, inc_pos, is_seed, comp, method="b2", pairs=None, min_members=MIN_SIZE)
        out[name] = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab_b2, MIN_SIZE)
        if name == "proposed":
            P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
            lab = partition_labels(ctx, inc_pos, is_seed, comp, method="average", pairs=P, min_members=MIN_SIZE, cut=CUT)
            out["full"] = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, MIN_SIZE)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--exp-dir", type=Path, required=True, help="experiments_hi_medium holding R1_gine_causal_c1prime")
    ap.add_argument("--policy-dir", type=Path, default=REPO_ROOT / "experiments_hi_medium/R3_expansion/policy_no_detector")
    ap.add_argument("--affinity-dir", type=Path, default=REPO_ROOT / "experiments_hi_medium/R4_partition/affinity")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "experiments_hi_medium/closeout_a15")
    ap.add_argument("--only", nargs="*", default=None, help="subset of run keys, e.g. primary block6-7")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    S = a.seed
    pdir = load_paths()["processed_dir"]
    r1 = a.exp_dir / "R1_gine_causal_c1prime"
    Wall = load_windows(REPO_ROOT / "configs/eval_window_hi_medium.yaml")
    policy, rule, affinity = Policy.load(a.policy_dir), Policy.rule("rule_q"), Affinity.load(a.affinity_dir)
    gt = pdir / "amlworld_ring_ground_truth.parquet"
    log = {"seed": S, "chosen": CHOSEN, "runs": []}
    a.out.mkdir(parents=True, exist_ok=True)

    def ctx_for(se, split):
        return build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                             embeddings_parquet=r1 / f"embeddings_{split}_seed{S}.parquet", checkpoint=r1 / f"model_best_seed{S}.pt")

    # ---- B1b delta_t on validation
    t0 = time.time()
    sv = build_scored_edges(r1 / f"scores_val_seed{S}.parquet", "val", model_id="gine_causal", seed=S, processed_dir=pdir)
    cv = ctx_for(sv, "val")
    Wv = Wall["val"]
    tv, pv = load_ground_truth(gt, *Wv.bounds, "test_visible", verbose=False)
    mv = topk_mask(sv[SELECT_COL].to_numpy(float), sv["edge_id"].to_numpy(np.int64))
    grid = []
    for dt in B1B_GRID:
        trajs = expand_all(sv, mv, rule, cv, delta_t_h=dt, p_floor=0.5)
        inc_pos, is_seed = included_from_trajectories(sv, mv, trajs, 0.5)
        comp = components_of(cv.idx, inc_pos)
        lab = partition_labels(cv, inc_pos, is_seed, comp, method="b2", pairs=None, min_members=MIN_SIZE)
        m = evaluate_rings(restrict_rings(rings_from_edge_clusters(sv, cv.idx, inc_pos, is_seed, lab, MIN_SIZE), sv, Wv), tv, 0.5, pv)
        grid.append({"delta_t_h": dt, "val_ring_f1": round(m.ring_f1, 4)})
    dt_b1b = sorted(grid, key=lambda r: (-r["val_ring_f1"], r["delta_t_h"]))[0]["delta_t_h"]
    log["b1b_val_grid"], log["b1b_delta_t_h"] = grid, dt_b1b
    print(f"seed {S}: B1b val grid {grid} -> delta_t {dt_b1b} ({time.time() - t0:.0f}s)", flush=True)
    del sv, cv

    se_all = build_scored_edges(r1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
    P0 = Wall["primary"]
    P = Window("primary", "test", 6, 14, P0.day_zero, P0.seconds_per_day)   # Amendment 15
    runs = [("primary", None)] + [(f"block{lo}-{hi}", (lo, hi)) for lo, hi in BLOCKS] + [("day15", (15, 15))]
    for key, days in runs:
        if a.only and key not in a.only:
            continue
        t0 = time.time()
        if days is None:
            se, W = se_all, P
        else:
            W = Window(key, "test", days[0], days[1], P.day_zero, P.seconds_per_day)
            se = se_all[W.mask(se_all["timestamp"].to_numpy())].reset_index(drop=True)
        ctx = ctx_for(se, "test")
        truth, pats = load_ground_truth(gt, *W.bounds, "test_visible", verbose=False)
        sc, ts = se[SELECT_COL].to_numpy(float), se["timestamp"].to_numpy(np.int64)
        eid = se["edge_id"].to_numpy(np.int64)
        in_w = W.mask(ts)
        for rule_name in ("global", "per_day"):
            if rule_name == "global":   # Amendment 15: budget over the window's own edges
                mask = np.zeros(len(sc), dtype=bool)
                mask[in_w] = topk_mask(sc[in_w], eid[in_w])
            else:
                mask = per_day_mask(sc, ts, P.days_of, eid, base=in_w)
            rings = build_methods(se, ctx, mask, policy, rule, affinity, dt_b1b)
            for meth, rr in rings.items():
                p = a.out / key / rule_name / meth / f"seed{S}.parquet"
                p.parent.mkdir(parents=True, exist_ok=True)
                write_rings_parquet(rr, p)
                m = evaluate_rings(restrict_rings(rr, se, W), truth, 0.5, pats)
                row = {"seed": S, "window": key, "rule": rule_name, "method": meth, "n_truth": len(truth),
                       "n_seeds": int(mask.sum()), "n_seeds_in_window": int((mask & in_w).sum()), "n_rings": len(rr),
                       "ring_f1": round(m.ring_f1, 4), "ring_p": round(m.ring_precision, 4), "ring_r": round(m.ring_recall, 4)}
                log["runs"].append(row)
                print(f"  {key} {rule_name} {meth}: seeds {row['n_seeds_in_window']}/{row['n_seeds']} rings {len(rr)} "
                      f"F1 {m.ring_f1:.4f} R {m.ring_recall:.4f} ({time.time() - t0:.0f}s)", flush=True)
        (a.out / f"log_seed{S}.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
        del ctx
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
