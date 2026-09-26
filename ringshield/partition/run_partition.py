"""Run the partition stage for one detector seed: val grid -> config -> test once -> metrics (Step 7.4).

    python ringshield/partition/run_partition.py --seed 1 --method pivot   --out experiments/R4_partition/runs/pivot/seed1
    python ringshield/partition/run_partition.py --seed 1 --method average --out .../average/seed1
    python ringshield/partition/run_partition.py --seed 1 --method b2|b3|b4 --out .../b2/seed1
    (ringshield/run_rings.py --aggregator full --partition <method> ... dispatches here)

Every method sees the SAME expanded subgraph: the R3 proposed policy at the seed's val-chosen
(delta_t, p_min) from experiments/R3_expansion/runs/proposed/seed<S>/config.yaml, the B0 cell
from the same file. The expansion and the pair affinities are computed once per split and
reused by every method / grid cell.

Grid on VAL (test_visible val rings, Jaccard 0.5, objective ring-F1; ties -> the more
conservative cell):
    b2        nothing
    b3        gap_h in {6, 12, 24, 48, 72}
    b4        resolution in {0.5, 1.0, 2.0} (python-louvain, random_state 0)
    pivot     threshold 0.5 (w = logit(p) > 0), no grid
    average   cut in {0.3, 0.5, 0.7, 0.9}
The grid and the chosen cell go into config.yaml BEFORE the test split is touched. metrics.json:
per-window blocks as before plus mean Jaccard, the count of predicted rings with > 100 members
and the partition diagnostics (components, clusters, components split, dropped edges).
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
from ringshield.aggregators.cc import SELECT_COL, score_column, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import METHODS, component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters  # noqa: E402
from ringshield.evaluate import evaluate_blocks, ring_metrics_full  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.expand.run_expand import R1_DIR, expansion_vs_truth  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.rings import write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit, seed_edge_precision, write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import POLICIES, load_ground_truth, split_window  # noqa: E402
from ringshield.windows import EVAL_WINDOW_YAML, load_windows  # noqa: E402

R3_RUNS = REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed"
POLICY_DIR = REPO_ROOT / "experiments" / "R3_expansion" / "policy_proposed"
AFFINITY_DIR = REPO_ROOT / "experiments" / "R4_partition" / "affinity"
GRIDS = {"b2": [{}], "b3": [{"gap_h": g} for g in (6, 12, 24, 48, 72)], "b4": [{"resolution": r} for r in (0.5, 1.0, 2.0)],
         "pivot": [{"threshold": 0.5}], "average": [{"cut": c} for c in (0.3, 0.5, 0.7, 0.9)]}
CONSERVATIVE = {"b3": lambda c: -c["gap_h"], "b4": lambda c: c["resolution"], "average": lambda c: -c["cut"]}   # tie-break key (larger = more conservative)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--method", choices=METHODS, required=True)
    ap.add_argument("--r1-dir", type=Path, default=R1_DIR)
    ap.add_argument("--policy-dir", type=Path, default=POLICY_DIR)
    ap.add_argument("--affinity-dir", type=Path, default=AFFINITY_DIR)
    ap.add_argument("--r3-config", type=Path, default=None, help="default experiments/R3_expansion/runs/proposed/seed<S>/config.yaml")
    ap.add_argument("--scope", choices=POLICIES, default="test_visible")
    ap.add_argument("--model-id", default="gine_causal")
    ap.add_argument("--labels-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--eval-window", type=Path, default=EVAL_WINDOW_YAML)
    ap.add_argument("--cluster-seed", type=int, default=0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    t_start = time.time()
    S, method = args.seed, args.method
    paths = load_paths()
    pdir = paths["processed_dir"]
    args.out.mkdir(parents=True, exist_ok=True)
    r3_cfg_path = args.r3_config or R3_RUNS / f"seed{S}" / "config.yaml"
    r3 = yaml.safe_load(r3_cfg_path.read_text(encoding="utf-8"))
    ch = r3["chosen"]
    k_pct, min_size, delta_t_h, p_min = float(ch["seed_frac_pct"]), int(ch["min_size"]), float(ch["delta_t_h"]), float(ch["p_min"])
    policy = Policy.load(args.policy_dir)
    affinity = Affinity.load(args.affinity_dir) if method in ("b4", "pivot", "average") else None

    se, ctx, ring_id_of, trajs, inc, pairs = {}, {}, {}, {}, {}, {}
    for split in ("val", "test"):
        df = build_scored_edges(args.r1_dir / f"scores_{split}_seed{S}.parquet", split, model_id=args.model_id, seed=S, processed_dir=pdir)
        if args.dry_run:
            df = df.sample(frac=0.01, random_state=S).sort_values("edge_id").reset_index(drop=True)
        se[split] = df
        emb = args.r1_dir / f"embeddings_{split}_seed{S}.parquet"
        ckpt = args.r1_dir / f"model_best_seed{S}.pt"          # absent for a non-GNN detector (gfpxgb)
        ctx[split] = build_context(df, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet", embeddings_parquet=emb if emb.exists() else None,
                                   checkpoint=ckpt if ckpt.exists() else None)
        ring_id_of[split] = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
        t0 = time.time()
        mask = seed_mask_for_pct(df[SELECT_COL].to_numpy(float), k_pct)
        trajs[split] = expand_all(df, mask, policy, ctx[split], delta_t_h=delta_t_h, p_floor=p_min)
        inc_pos, is_seed = included_from_trajectories(df, mask, trajs[split], p_min)
        comp = components_of(ctx[split].idx, inc_pos)
        P = component_pairs(ctx[split], inc_pos, is_seed, comp, affinity) if affinity is not None else None
        inc[split] = (mask, inc_pos, is_seed, comp)
        pairs[split] = P
        print(f"[run_partition] {split}: {len(df):,} edges, {int(mask.sum()):,} seeds, {len(inc_pos):,} included in {int(comp.max()) + 1 if len(comp) else 0} "
              f"components{'' if P is None else f', {len(P):,} pairs (affinity mean {P['affinity'].mean():.3f})'} ({time.time() - t0:.0f}s)")
    labels = {s: (pd.read_parquet(args.labels_dir / f"labels_{s}.parquet") if (args.labels_dir / f"labels_{s}.parquet").exists() else None) for s in ("val", "test")}
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    windows = {s: list(split_window(pdir / f"amlworld_{s}.parquet")) for s in ("val", "test")}
    eval_windows = load_windows(args.eval_window)
    test_windows = {k: w for k, w in eval_windows.items() if w.split == "test"}
    truth_val, pat_val = load_ground_truth(ring_gt, *windows["val"], args.scope, verbose=False)

    def rings_for(split, cell, report=None, method=method):
        mask, inc_pos, is_seed, comp = inc[split]
        lab = partition_labels(ctx[split], inc_pos, is_seed, comp, method=method, pairs=pairs[split], seed=args.cluster_seed,
                               min_members=min_size, **cell)
        rings = rings_from_edge_clusters(se[split], ctx[split].idx, inc_pos, is_seed, lab, min_size)
        if report is not None:
            report.update({"n_included": int(len(inc_pos)), "n_components": int(comp.max()) + 1 if len(comp) else 0,
                           "n_clusters": int(len(np.unique(lab[lab >= 0]))), "n_dropped_edges": int((lab < 0).sum()),
                           "components_split": int(sum(1 for c in np.unique(comp) if len(np.unique(lab[(comp == c) & (lab >= 0)])) > 1)),
                           "n_pairs": int(len(pairs[split])) if pairs[split] is not None else 0, "n_rings": len(rings),
                           "n_rings_gt100": int(sum(1 for r in rings if r.n_members > 100))})
        return rings

    # ---- grid on VAL ----------------------------------------------------------------------------------------
    grid_rows = []
    for cell in GRIDS[method]:
        rep = {}
        rings = rings_for("val", cell, rep)
        m = evaluate_rings([r.member_set for r in rings], truth_val, 0.5, pat_val)
        grid_rows.append({**cell, "n_rings": len(rings), "ring_precision": round(m.ring_precision, 4), "ring_recall": round(m.ring_recall, 4),
                          "ring_f1": round(m.ring_f1, 4), "mean_jaccard": round(m.mean_jaccard, 4), "member_coverage": round(m.member_coverage, 4),
                          "n_matched": m.n_matched, "components_split": rep["components_split"], "n_clusters": rep["n_clusters"],
                          "n_rings_gt100": rep["n_rings_gt100"]})
        print(f"  val grid {cell}: rings {len(rings):4d}  P {m.ring_precision:.3f}  R {m.ring_recall:.3f}  F1 {m.ring_f1:.3f}  J {m.mean_jaccard:.3f}  "
              f"| components split {rep['components_split']}, clusters {rep['n_clusters']}")
    key = CONSERVATIVE.get(method, lambda c: 0)
    best = max(grid_rows, key=lambda r: (r["ring_f1"], key({k: r[k] for k in GRIDS[method][0]})))
    cell = {k: best[k] for k in GRIDS[method][0]}
    chosen = {"seed_frac_pct": k_pct, "min_size": min_size, "delta_t_h": delta_t_h, "p_min": p_min, "method": method, **cell, "val_ring_f1": best["ring_f1"]}
    print(f"[run_partition] seed {S} {method}: chosen on val {chosen}")
    config = {"experiment": args.out.name, "step": "7.4 (R4 partition)", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "git_commit": _git_commit(), "aggregator": "full", "method": method, "detector_seed": S, "r1_dir": str(args.r1_dir),
              "r3_config": str(r3_cfg_path), "expansion_fixed": {"delta_t_h": delta_t_h, "p_min": p_min, "policy_dir": str(args.policy_dir)},
              "affinity_dir": str(args.affinity_dir) if affinity is not None else None,
              "affinity_cv_auc_pr": (affinity.meta.get("cv") or {}).get("cv_auc_pr_mean") if affinity is not None else None,
              "cluster_seed": args.cluster_seed, "b0_cell_fixed": {"seed_frac_pct": k_pct, "min_size": min_size},
              "grid": GRIDS[method], "grid_results_val": grid_rows, "chosen": chosen, "scope": args.scope, "model_id": args.model_id,
              "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]), "context": {s: ctx[s].meta for s in ("val", "test")},
              "scope_windows": windows, "eval_window": str(args.eval_window), "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()},
              "primary_block": "primary", "n_val_truth_rings": len(truth_val), "dry_run": bool(args.dry_run)}
    (args.out / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # ---- TEST once ---------------------------------------------------------------------------------------------
    rep_test = {}
    rings = rings_for("test", cell, rep_test)
    write_rings_parquet(rings, args.out / "rings.parquet")
    from ringshield.aggregators.cc import aggregate_cc
    b0_rings = aggregate_cc(se["test"], k_pct, min_size)
    blocks = evaluate_blocks(rings, se["test"], ring_gt, args.scope, test_windows, 0.5, [0.3, 0.7], labels=labels["test"])
    for name, w in test_windows.items():
        truth_w, _ = load_ground_truth(ring_gt, *w.bounds, args.scope, verbose=False)
        blocks[name]["expansion"] = expansion_vs_truth(rings, b0_rings, se["test"], ring_id_of["test"], truth_w, w)
        blocks[name]["n_rings_gt100_in_window"] = int(sum(1 for r in rings if r.n_members > 100))
    val_rings = rings_for("val", cell)
    metrics = {"experiment": args.out.name, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
               "aggregator": "full", "method": method, "detector_seed": S, "scope": args.scope, "chosen": chosen, "feature_set": "trailing_closescycle",
               "reportable": True, "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]),
               "affinity_cv_auc_pr": config["affinity_cv_auc_pr"], "eval_windows": config["eval_windows"], "primary_block": "primary",
               "blocks": blocks, "test": blocks["primary"],
               "rings_total": {"n_rings": len(rings), "n_seed_edges": int(sum(len(r.seed_edges) for r in rings)),
                               "n_expanded_edges": int(sum(len(r.expanded_edges) for r in rings)), "n_member_edges": int(sum(len(r.member_edges) for r in rings)),
                               "max_members": max((r.n_members for r in rings), default=0), "n_rings_gt100": rep_test["n_rings_gt100"]},
               "test_partition": rep_test, "test_seed_edges_vs_labels": seed_edge_precision(rings, labels["test"]),
               "val_at_chosen": ring_metrics_full([r.member_set for r in val_rings], truth_val, pat_val, 0.5, [0.3, 0.7]),
               "val_seed_edges_vs_labels": seed_edge_precision(val_rings, labels["val"]), "seconds": round(time.time() - t_start, 1)}
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    for name, t in blocks.items():
        print(f"[run_partition] {name:7s} days {t['window']['days']} ({t['n_truth']} truth rings): {t['n_predicted']} rings | P {t['ring_precision']:.4f} "
              f"R {t['ring_recall']:.4f} F1 {t['ring_f1']:.4f} | J {t['mean_jaccard']:.4f} | R>=3 {t['ring_recall_ge3']} | coverage {t['member_coverage']:.4f} "
              f"| >100 members {t['n_rings_gt100_in_window']} | max {t['pred_size']['max_members']}")
    print(f"-> {args.out}")
    return metrics


if __name__ == "__main__":
    main()
