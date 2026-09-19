"""Run the 'expand' aggregator for one detector seed: val grid -> config -> test once -> metrics (Step 6.4).

    python ringshield/expand/run_expand.py --seed 1 --policy-dir experiments/R3_expansion/policy_proposed \\
        --out experiments/R3_expansion/runs/proposed/seed1
    python ringshield/expand/run_expand.py --seed 1 --policy rule_q --out .../b1b/seed1          # B1b
    (ringshield/run_rings.py --aggregator expand ... dispatches here)

Inputs per detector seed S (--r1-dir, default experiments/R1_gine_causal): scores_{val,test}_seed<S>
(calibrated), embeddings_{val,test}_seed<S>, model_best_seed<S>.pt (dead-region constants); the
B0 cell (seed_frac_pct, min_size) comes from --b0-config (default the R2 B0 run of the same
seed, chosen on val) and is NOT re-searched here.

Grid on VAL (test_visible val rings, Jaccard 0.5, objective ring-F1): delta_t in {24, 48, 72} h x
p_min in {0.3, 0.5, 0.7} for a model policy; delta_t only for the rules (B1 = rule, B1b = rule_q,
p is 0/1). Ties -> larger p_min, then smaller delta_t. The whole grid and the chosen cell go into
config.yaml BEFORE the test split is touched; test runs once with the chosen cell.

metrics.json: per-window blocks as B0 (ringshield.evaluate.evaluate_blocks) plus, per window,
the two interim Step 6 numbers -- expanded edges that are member edges of a truth ring vs not,
and the truth member accounts newly covered relative to the seed-only (B0) rings of the same
seed / cell -- and the expansion diagnostics (components, additions, stop reasons).
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
from ringshield.aggregators.expand import expand_all, rings_from_trajectories  # noqa: E402
from ringshield.evaluate import evaluate_blocks, restrict_rings, ring_metrics_full  # noqa: E402
from ringshield.expand.candidates import MAX_EVENTS_PER_QUERY  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.rings import Ring, write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit, seed_edge_precision, write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import POLICIES, load_ground_truth, split_window  # noqa: E402
from ringshield.windows import EVAL_WINDOW_YAML, Window, load_windows  # noqa: E402

R1_DIR = REPO_ROOT / "experiments" / "R1_gine_causal"
P_MIN_GRID = [0.3, 0.5, 0.7]
DELTA_GRID_H = [24, 48, 72]
DRY_RUN_FRAC = 0.01


def expansion_vs_truth(rings: list[Ring], b0_rings: list[Ring], se: pd.DataFrame, split_ring_id: pd.Series,
                       truth: dict, window: Window) -> dict:
    """Interim Step 6 numbers inside a window: expanded edges that are member edges of a truth ring
    vs not; truth member accounts covered by `rings` but not by the seed-only `b0_rings`."""
    ts = se.set_index("edge_id")["timestamp"]
    exp = sorted({e for r in rings for e in r.expanded_edges})
    exp_in = [e for e in exp if window.mask(np.array([ts.loc[e]]))[0]] if exp else []
    is_member = split_ring_id.reindex(exp_in).fillna(-1).to_numpy() > 0
    truth_acc = set().union(*truth.values()) if truth else set()
    cov = set().union(*restrict_rings(rings, se, window)) if rings else set()
    cov0 = set().union(*restrict_rings(b0_rings, se, window)) if b0_rings else set()
    return {"n_expanded_edges_in_window": len(exp_in), "expanded_true_member": int(is_member.sum()),
            "expanded_not_member": int((~is_member).sum()),
            "expanded_member_precision": float(is_member.mean()) if len(exp_in) else None,
            "truth_accounts": len(truth_acc), "covered_accounts_expand": len(cov & truth_acc),
            "covered_accounts_b0": len(cov0 & truth_acc), "quiet_accounts_newly_covered": len((cov - cov0) & truth_acc),
            "accounts_lost_vs_b0": len((cov0 - cov) & truth_acc),
            "non_truth_accounts_added": len((cov - cov0) - truth_acc)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True, help="detector (R1) seed")
    ap.add_argument("--r1-dir", type=Path, default=R1_DIR)
    ap.add_argument("--policy-dir", type=Path, default=None, help="a trained policy directory (kind model)")
    ap.add_argument("--policy", choices=["rule", "rule_q"], default=None, help="rule baseline instead of --policy-dir")
    ap.add_argument("--b0-config", type=Path, default=None, help="default experiments/R2_b0/gine_causal/seed<S>/config.yaml")
    ap.add_argument("--seed-frac-pct", type=float, default=None, help="override the B0 cell")
    ap.add_argument("--min-size", type=int, default=None)
    ap.add_argument("--max-gap-hours", type=float, default=None)
    ap.add_argument("--p-min-grid", type=float, nargs="*", default=P_MIN_GRID)
    ap.add_argument("--delta-grid-h", type=float, nargs="*", default=DELTA_GRID_H)
    ap.add_argument("--max-hops", type=int, default=2)
    ap.add_argument("--scope", choices=POLICIES, default="test_visible")
    ap.add_argument("--model-id", default="gine_causal")
    ap.add_argument("--labels-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--eval-window", type=Path, default=EVAL_WINDOW_YAML)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    assert (args.policy_dir is None) != (args.policy is None), "give exactly one of --policy-dir / --policy"
    t_start = time.time()
    paths = load_paths()
    pdir = paths["processed_dir"]
    S = args.seed
    args.out.mkdir(parents=True, exist_ok=True)
    policy = Policy.load(args.policy_dir) if args.policy_dir else Policy.rule(args.policy)
    method = f"policy:{args.policy_dir}" if args.policy_dir else f"rule:{args.policy}"
    is_model = policy.kind == "model"

    # ---- B0 cell (chosen on val in Step 4) -------------------------------------------------------
    b0_cfg_path = args.b0_config or REPO_ROOT / "experiments" / "R2_b0" / "gine_causal" / f"seed{S}" / "config.yaml"
    b0_cfg = yaml.safe_load(b0_cfg_path.read_text(encoding="utf-8")) if b0_cfg_path.exists() else {"chosen": {"seed_frac_pct": 0.1, "min_size": 3}}
    k_pct = args.seed_frac_pct if args.seed_frac_pct is not None else float(b0_cfg["chosen"]["seed_frac_pct"])
    min_size = args.min_size if args.min_size is not None else int(b0_cfg["chosen"]["min_size"])

    # ---- data, contexts ---------------------------------------------------------------------------
    se, ctx, ring_id_of = {}, {}, {}
    for split in ("val", "test"):
        df = build_scored_edges(args.r1_dir / f"scores_{split}_seed{S}.parquet", split, model_id=args.model_id, seed=S, processed_dir=pdir)
        if args.dry_run:
            df = df.sample(frac=DRY_RUN_FRAC, random_state=S).sort_values("edge_id").reset_index(drop=True)
        se[split] = df
        emb = args.r1_dir / f"embeddings_{split}_seed{S}.parquet"
        ctx[split] = build_context(df, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                                   embeddings_parquet=emb if emb.exists() else None,
                                   checkpoint=args.r1_dir / f"model_best_seed{S}.pt")
        ring_id_of[split] = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
        print(f"[run_expand] {split}: {len(df):,} edges, dead-region {ctx[split].meta['n_dead_region']:,}, "
              f"embeddings {'yes' if emb.exists() else 'NO'}")
    calibrated = not se["test"]["score_calibrated"].equals(se["test"]["score_raw"])
    labels = {s: (pd.read_parquet(args.labels_dir / f"labels_{s}.parquet") if (args.labels_dir / f"labels_{s}.parquet").exists() else None)
              for s in ("val", "test")}
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    windows = {s: list(split_window(pdir / f"amlworld_{s}.parquet")) for s in ("val", "test")}
    eval_windows = load_windows(args.eval_window)
    test_windows = {k: w for k, w in eval_windows.items() if w.split == "test"}
    truth_val, pat_val = load_ground_truth(ring_gt, *windows["val"], args.scope, verbose=False)
    seed_mask = {s: seed_mask_for_pct(se[s][SELECT_COL].to_numpy(float), k_pct) for s in ("val", "test")}
    print(f"[run_expand] seed {S}, {method}, B0 cell {k_pct} % / min_size {min_size} (from {b0_cfg_path.name}); "
          f"val seeds {int(seed_mask['val'].sum()):,}, test seeds {int(seed_mask['test'].sum()):,}")

    # ---- grid on VAL -------------------------------------------------------------------------------
    p_grid = list(args.p_min_grid) if is_model else [1.0]
    p_floor = min(p_grid)
    grid_rows, trajs_val = [], {}
    for dt in args.delta_grid_h:
        t0 = time.time()
        trajs = expand_all(se["val"], seed_mask["val"], policy, ctx["val"], delta_t_h=dt, p_floor=p_floor, max_hops=args.max_hops)
        trajs_val[dt] = trajs
        for pm in p_grid:
            rep = {}
            rings = rings_from_trajectories(se["val"], seed_mask["val"], trajs, pm, min_size, args.max_gap_hours, report=rep)
            m = evaluate_rings([r.member_set for r in rings], truth_val, 0.5, pat_val)
            grid_rows.append({"delta_t_h": dt, "p_min": pm, "n_rings": len(rings), "ring_precision": round(m.ring_precision, 4),
                              "ring_recall": round(m.ring_recall, 4), "ring_f1": round(m.ring_f1, 4),
                              "member_coverage": round(m.member_coverage, 4), "n_matched": m.n_matched,
                              "n_expanded_edges": rep["n_expanded_edges"], "n_components_expanded": rep["n_components_expanded"],
                              "seconds": round(time.time() - t0, 1)})
            print(f"  val grid dt={dt:<3} p_min={pm}: rings {len(rings):4d}  P {m.ring_precision:.3f}  R {m.ring_recall:.3f}  "
                  f"F1 {m.ring_f1:.3f}  | expanded edges {rep['n_expanded_edges']} in {rep['n_components_expanded']} components")
    grid_df = pd.DataFrame(grid_rows)
    best = grid_df.sort_values(["ring_f1", "p_min", "delta_t_h"], ascending=[False, False, True]).iloc[0]
    chosen = {"seed_frac_pct": k_pct, "min_size": min_size, "max_gap_hours": args.max_gap_hours,
              "delta_t_h": float(best["delta_t_h"]), "p_min": float(best["p_min"]), "val_ring_f1": float(best["ring_f1"])}
    print(f"[run_expand] chosen on val: {chosen}")
    config = {"experiment": args.out.name, "step": "6.4 (R3 expansion)", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "git_commit": _git_commit(), "aggregator": "expand", "method": method, "policy_kind": policy.kind,
              "policy_features": policy.features if is_model else None, "policy_drop_groups": list(policy.drop_groups),
              "policy_hop1_only": policy.hop1_only, "policy_cv": (policy.meta.get("cv") or {}).get("cv_auc_pr_mean") if is_model else None,
              "detector_seed": S, "r1_dir": str(args.r1_dir), "model_id": args.model_id, "scope": args.scope, "choose_on": "val",
              "b0_config": str(b0_cfg_path), "b0_cell_fixed": {"seed_frac_pct": k_pct, "min_size": min_size},
              "grid": {"delta_t_h": list(args.delta_grid_h), "p_min": p_grid}, "grid_results_val": grid_rows, "chosen": chosen,
              "candidate_definition": {"max_hops": args.max_hops, "max_events_per_query": MAX_EVENTS_PER_QUERY,
                                       "window": "[min seed time - delta_t, max seed time + delta_t]"},
              "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]), "calibrated": bool(calibrated),
              "context": {s: ctx[s].meta for s in ("val", "test")}, "scope_windows": windows,
              "eval_window": str(args.eval_window), "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()},
              "primary_block": "primary", "n_val_truth_rings": len(truth_val), "dry_run": bool(args.dry_run)}
    (args.out / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # ---- TEST, once -----------------------------------------------------------------------------------
    t0 = time.time()
    trajs_test = expand_all(se["test"], seed_mask["test"], policy, ctx["test"], delta_t_h=chosen["delta_t_h"], p_floor=chosen["p_min"],
                            max_hops=args.max_hops, verbose=True)
    rep_test = {}
    rings = rings_from_trajectories(se["test"], seed_mask["test"], trajs_test, chosen["p_min"], min_size, args.max_gap_hours,
                                    verbose=True, report=rep_test)
    write_rings_parquet(rings, args.out / "rings.parquet")
    b0_rings = aggregate_cc(se["test"], k_pct, min_size, args.max_gap_hours)
    blocks = evaluate_blocks(rings, se["test"], ring_gt, args.scope, test_windows, 0.5, [0.3, 0.7], labels=labels["test"])
    for name, w in test_windows.items():
        truth_w, _ = load_ground_truth(ring_gt, *w.bounds, args.scope, verbose=False)
        blocks[name]["expansion"] = expansion_vs_truth(rings, b0_rings, se["test"], ring_id_of["test"], truth_w, w)
    val_rings = rings_from_trajectories(se["val"], seed_mask["val"], trajs_val[chosen["delta_t_h"]], chosen["p_min"], min_size, args.max_gap_hours)
    b0_val = aggregate_cc(se["val"], k_pct, min_size, args.max_gap_hours)
    wv = eval_windows["val"]
    stops = pd.Series([t["stop"] for t in trajs_test]).value_counts().to_dict()
    metrics = {"experiment": args.out.name, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
               "aggregator": "expand", "method": method, "policy_kind": policy.kind, "policy_drop_groups": list(policy.drop_groups),
               "policy_hop1_only": policy.hop1_only, "policy_cv_auc_pr": (policy.meta.get("cv") or {}).get("cv_auc_pr_mean") if is_model else None,
               "detector_seed": S, "scope": args.scope, "chosen": chosen, "feature_set": "trailing_closescycle", "reportable": True,
               "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]),
               "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()}, "primary_block": "primary",
               "blocks": blocks, "test": blocks["primary"],
               "rings_total": {"n_rings": len(rings), "n_seed_edges": int(sum(len(r.seed_edges) for r in rings)),
                               "n_expanded_edges": int(sum(len(r.expanded_edges) for r in rings)),
                               "n_member_edges": int(sum(len(r.member_edges) for r in rings)),
                               "n_rings_with_expansion": int(sum(1 for r in rings if r.expanded_edges))},
               "test_expansion": {**rep_test, "n_additions_total": int(sum(len(t["adds"]) for t in trajs_test)), "stops": stops,
                                  "seconds": round(time.time() - t0, 1)},
               "test_seed_edges_vs_labels": seed_edge_precision(rings, labels["test"]),
               "val_at_chosen": ring_metrics_full([r.member_set for r in val_rings], truth_val, pat_val, 0.5, [0.3, 0.7]),
               "val_expansion": expansion_vs_truth(val_rings, b0_val, se["val"], ring_id_of["val"], truth_val, wv),
               "val_seed_edges_vs_labels": seed_edge_precision(val_rings, labels["val"]),
               "seconds": round(time.time() - t_start, 1)}
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    for name, t in blocks.items():
        e = t["expansion"]
        print(f"[run_expand] {name:7s} days {t['window']['days']} ({t['n_truth']} truth rings): {t['n_predicted']} rings | "
              f"P {t['ring_precision']:.4f} R {t['ring_recall']:.4f} F1 {t['ring_f1']:.4f} | R>=3 {t['ring_recall_ge3']} | "
              f"coverage {t['member_coverage']:.4f} | expanded {e['expanded_true_member']} member / {e['expanded_not_member']} not | "
              f"quiet accounts newly covered {e['quiet_accounts_newly_covered']} (lost {e['accounts_lost_vs_b0']})")
    print(f"-> {args.out}")
    return metrics


if __name__ == "__main__":
    main()
