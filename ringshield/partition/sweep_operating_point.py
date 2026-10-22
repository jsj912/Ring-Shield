"""Pre-registered extension: does the partition allow a looser operating point? (Step 7 close, item 3)

    python ringshield/partition/sweep_operating_point.py --seed 1 --variant full --out experiments/R4_sweep/full/seed1
    python ringshield/partition/sweep_operating_point.py --seed 1 --variant cc_partition --out experiments/R4_sweep/cc_partition/seed1

Hypothesis (docs/PARTITION.md, written before the run): partitioning prevents the chaining
collapse B0 shows above 0.3 % seeds, allowing a looser operating point.

VAL grid, per detector seed: seed_frac in {0.10, 0.15, 0.20, 0.30, 0.50} % x cut in {0.3, 0.5,
0.7} x min_size in {2, 3}. `--variant full` expands each seed set with the R3 policy at the
seed's val-chosen (delta_t, p_min) before partitioning; `--variant cc_partition` partitions the
plain seed components (no expansion). Objective val ring-F1; ties -> smaller seed_frac, then
larger min_size, then larger cut. The winner is evaluated on the test primary window exactly
once. For the val-only figure the grid also records B0 (plain components of the seeds, the
aggregate_cc rings) at every (seed_frac, min_size).

Outputs: <out>/config.yaml (full grid + chosen cell, written before the test run),
metrics.json (per-window blocks at the chosen cell, as run_partition), grid_val.csv.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, aggregate_cc, score_column, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters  # noqa: E402
from ringshield.evaluate import evaluate_blocks, ring_metrics_full  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.rings import write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit, seed_edge_precision, write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth, split_window  # noqa: E402
from ringshield.windows import EVAL_WINDOW_YAML, load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R3 = REPO_ROOT / "experiments" / "R3_expansion"
R4 = REPO_ROOT / "experiments" / "R4_partition"
SEED_FRAC = [0.10, 0.15, 0.20, 0.30, 0.50]
CUTS = [0.3, 0.5, 0.7]
MIN_SIZES = [2, 3]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--variant", choices=["full", "cc_partition"], required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--method", default="average", help="clustering (average | pivot)")
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--cluster-seed", type=int, default=0)
    ap.add_argument("--eval-window", type=Path, default=EVAL_WINDOW_YAML)
    args = ap.parse_args(argv)
    t_start = time.time()
    S = args.seed
    paths = load_paths()
    pdir = paths["processed_dir"]
    args.out.mkdir(parents=True, exist_ok=True)
    r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    delta_t_h, p_min = float(r3["delta_t_h"]), float(r3["p_min"])
    policy = Policy.load(R3 / "policy_proposed")
    affinity = Affinity.load(R4 / "affinity")
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()
    test_windows = {k: w for k, w in W.items() if w.split == "test"}
    labels = {s: (REPO_ROOT / "contract" / "out" / f"labels_{s}.parquet") for s in ("val", "test")}
    labels = {s: (pd.read_parquet(p) if p.exists() else None) for s, p in labels.items()}

    se, ctx = {}, {}
    for split in ("val", "test"):
        se[split] = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
        emb = R1 / f"embeddings_{split}_seed{S}.parquet"
        ctx[split] = build_context(se[split], gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                                   embeddings_parquet=emb if emb.exists() else None, checkpoint=R1 / f"model_best_seed{S}.pt")
    truth_val, pat_val = load_ground_truth(ring_gt, *split_window(pdir / "amlworld_val.parquet"), args.scope, verbose=False)

    cache: dict[tuple[str, float], tuple] = {}

    def included(split, k_pct):
        """(inc_pos, is_seed, comp, pairs) for a seed fraction, cached per split."""
        key = (split, k_pct)
        if key not in cache:
            mask = seed_mask_for_pct(se[split][SELECT_COL].to_numpy(float), k_pct)
            if args.variant == "full":
                trajs = expand_all(se[split], mask, policy, ctx[split], delta_t_h=delta_t_h, p_floor=p_min)
                inc_pos, is_seed = included_from_trajectories(se[split], mask, trajs, p_min)
            else:
                inc_pos, is_seed = np.flatnonzero(mask), mask[np.flatnonzero(mask)]
            comp = components_of(ctx[split].idx, inc_pos)
            P = component_pairs(ctx[split], inc_pos, is_seed, comp, affinity)
            cache[key] = (inc_pos, is_seed, comp, P)
            print(f"  [{split} {k_pct}%] {int(mask.sum()):,} seeds -> {len(inc_pos):,} included, {comp.max() + 1 if len(comp) else 0} components, "
                  f"{len(P):,} pairs", flush=True)
        return cache[key]

    def rings_at(split, k_pct, cut, min_size, method=None):
        inc_pos, is_seed, comp, P = included(split, k_pct)
        if method == "b0":
            return aggregate_cc(se[split], k_pct, min_size)
        lab = partition_labels(ctx[split], inc_pos, is_seed, comp, method=args.method, pairs=P, cut=cut,
                               seed=args.cluster_seed, min_members=min_size)
        return rings_from_edge_clusters(se[split], ctx[split].idx, inc_pos, is_seed, lab, min_size)

    # ---- val grid -----------------------------------------------------------------------------------
    grid = []
    for k_pct in SEED_FRAC:
        for ms in MIN_SIZES:
            r0 = rings_at("val", k_pct, None, ms, method="b0")
            m0 = evaluate_rings([r.member_set for r in r0], truth_val, 0.5, pat_val)
            grid.append({"variant": "b0", "seed_frac_pct": k_pct, "cut": None, "min_size": ms, "n_rings": len(r0),
                         "ring_precision": round(m0.ring_precision, 4), "ring_recall": round(m0.ring_recall, 4),
                         "ring_f1": round(m0.ring_f1, 4), "mean_jaccard": round(m0.mean_jaccard, 4),
                         "max_members": max((r.n_members for r in r0), default=0)})
            for cut in CUTS:
                rs = rings_at("val", k_pct, cut, ms)
                m = evaluate_rings([r.member_set for r in rs], truth_val, 0.5, pat_val)
                grid.append({"variant": args.variant, "seed_frac_pct": k_pct, "cut": cut, "min_size": ms, "n_rings": len(rs),
                             "ring_precision": round(m.ring_precision, 4), "ring_recall": round(m.ring_recall, 4),
                             "ring_f1": round(m.ring_f1, 4), "mean_jaccard": round(m.mean_jaccard, 4),
                             "max_members": max((r.n_members for r in rs), default=0)})
                print(f"  val {args.variant} k={k_pct}% cut={cut} min_size={ms}: rings {len(rs):5d}  P {m.ring_precision:.3f}  "
                      f"R {m.ring_recall:.3f}  F1 {m.ring_f1:.3f}  max members {grid[-1]['max_members']}", flush=True)
    gdf = pd.DataFrame(grid)
    gdf.to_csv(args.out / "grid_val.csv", index=False)
    cand = gdf[gdf["variant"] == args.variant]
    best = cand.sort_values(["ring_f1", "seed_frac_pct", "min_size", "cut"], ascending=[False, True, False, False]).iloc[0]
    chosen = {"seed_frac_pct": float(best["seed_frac_pct"]), "min_size": int(best["min_size"]), "cut": float(best["cut"]),
              "method": args.method, "delta_t_h": delta_t_h if args.variant == "full" else None,
              "p_min": p_min if args.variant == "full" else None, "val_ring_f1": float(best["ring_f1"])}
    print(f"[sweep] seed {S} {args.variant}: chosen on val {chosen}")
    config = {"experiment": args.out.name, "step": "7 close, item 3 (pre-registered operating-point sweep)",
              "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
              "hypothesis": "partitioning prevents the chaining collapse B0 shows above 0.3 % seeds, allowing a looser operating point",
              "variant": args.variant, "aggregator": "full" if args.variant == "full" else "cc+partition", "method": args.method,
              "detector_seed": S, "expansion_fixed": {"delta_t_h": delta_t_h, "p_min": p_min} if args.variant == "full" else None,
              "grid": {"seed_frac_pct": SEED_FRAC, "cut": CUTS, "min_size": MIN_SIZES}, "grid_results_val": grid, "chosen": chosen,
              "tie_break": ["smallest_seed_frac_pct", "largest_min_size", "largest_cut"], "scope": args.scope,
              "cluster_seed": args.cluster_seed, "eval_windows": {k: w.as_dict() for k, w in W.items()}, "primary_block": "primary"}
    (args.out / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # ---- test once ------------------------------------------------------------------------------------
    rings = rings_at("test", chosen["seed_frac_pct"], chosen["cut"], chosen["min_size"])
    write_rings_parquet(rings, args.out / "rings.parquet")
    blocks = evaluate_blocks(rings, se["test"], ring_gt, args.scope, test_windows, 0.5, [0.3, 0.7], labels=labels["test"])
    for name in blocks:
        blocks[name]["n_rings_gt100_in_window"] = int(sum(1 for r in rings if r.n_members > 100))
    val_rings = rings_at("val", chosen["seed_frac_pct"], chosen["cut"], chosen["min_size"])
    metrics = {"experiment": args.out.name, "created_utc": config["created_utc"], "git_commit": config["git_commit"],
               "aggregator": config["aggregator"], "method": f"sweep_{args.variant}", "detector_seed": S, "scope": args.scope,
               "chosen": chosen, "reportable": True, "eval_windows": config["eval_windows"], "primary_block": "primary",
               "blocks": blocks, "test": blocks["primary"],
               "rings_total": {"n_rings": len(rings), "max_members": max((r.n_members for r in rings), default=0),
                               "n_seed_edges": int(sum(len(r.seed_edges) for r in rings)),
                               "n_expanded_edges": int(sum(len(r.expanded_edges) for r in rings))},
               "test_partition": None, "val_at_chosen": ring_metrics_full([r.member_set for r in val_rings], truth_val, pat_val, 0.5, [0.3, 0.7]),
               "test_seed_edges_vs_labels": seed_edge_precision(rings, labels["test"]), "seconds": round(time.time() - t_start, 1)}
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    for name, t in blocks.items():
        print(f"[sweep] {name:7s}: {t['n_predicted']} rings | P {t['ring_precision']:.4f} R {t['ring_recall']:.4f} F1 {t['ring_f1']:.4f} | "
              f"J {t['mean_jaccard']:.4f} | max members {t['pred_size']['max_members']}")
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
