"""Single entry point for every ring aggregator (Step 4).

    python ringshield/run_rings.py --scores-val <parquet> --scores-test <parquet> \\
        --labels-dir contract/out --aggregator cc --choose-on val --scope test_visible --out <dir>

1. builds the scored_edges frame for val and test (ringshield/scored_edges.py);
2. grid-searches seed_frac_pct (configs/threshold_rule.yaml) x min_size on the VAL split's
   ring-F1 (test_visible val rings, Jaccard 0.5); the chosen cell and the whole grid go into
   <out>/config.yaml BEFORE the test split is touched;
3. runs the aggregator on TEST exactly once with the chosen values -> <out>/rings.parquet
   (contract schema);
4. evaluates under test_visible per evaluation window (configs/eval_window.yaml: primary = test
   days 8-9, tail = days 10-17, whole = the full split; truth AND predicted rings restricted to
   the window, ringshield/evaluate.py) -> <out>/metrics.json: per block ring precision / recall /
   F1, member coverage, mean Jaccard, per-pattern recall, Ring-Recall>=3, the Jaccard 0.3 / 0.7
   sweep and the strict / majority appendix numbers; seed-edge precision from the labels; the
   val numbers of the chosen cell. environment.txt as for every experiment.

--dry-run keeps 1 % of each split's scored edges (pipeline check; rings will be near-empty).
Every argument, the grid and the git commit are recorded in config.yaml.

--aggregator expand (Step 6.4) dispatches to ringshield/expand/run_expand.py: the B0 cell is fixed
(the seed's R2 config), the val grid is delta_t x p_min, and the policy comes from --policy-dir
(trained, ringshield/expand/policy.py) or --policy rule|rule_q (B1 / B1b):

    python ringshield/run_rings.py --aggregator expand --seed 1 --policy-dir experiments/R3_expansion/policy_proposed         --out experiments/R3_expansion/runs/proposed/seed1
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, aggregate_cc, score_column, threshold_for_pct  # noqa: E402
from ringshield.evaluate import evaluate_blocks, ring_metrics_full, seed_edges_vs_labels  # noqa: E402
from ringshield.rings import Ring, write_rings_parquet  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import POLICIES, load_ground_truth, split_window  # noqa: E402
from ringshield.windows import EVAL_WINDOW_YAML, load_windows  # noqa: E402

AGGREGATORS = {"cc": aggregate_cc, "expand": "ringshield.expand.run_expand"}   # expand: separate runner (own grid)
RULE_PATH = REPO_ROOT / "configs" / "threshold_rule.yaml"
DRY_RUN_FRAC = 0.01


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def write_environment(path: Path):
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}", f"git_commit: {_git_commit()}"]
    try:
        lines.append("\n# pip freeze\n" + subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    except Exception:  # pragma: no cover
        lines.append("pip freeze failed")
    path.write_text("\n".join(lines), encoding="utf-8")


def seed_edge_precision(rings: list[Ring], labels: pd.DataFrame | None) -> dict | None:
    if labels is None:
        return None
    lab = labels.set_index("edge_id")["true_label"]
    seeds = np.array(sorted({e for r in rings for e in r.seed_edges}), dtype=np.int64)
    members = np.array(sorted({e for r in rings for e in r.member_edges}), dtype=np.int64)
    n_pos = int(lab.sum())
    return {"n_seed_edges": int(len(seeds)), "seed_edge_precision": float(lab.reindex(seeds).mean()) if len(seeds) else None,
            "seed_edge_recall_of_illicit": float(lab.reindex(seeds).sum() / n_pos) if n_pos else None,
            "n_member_edges": int(len(members)),
            "member_edge_precision": float(lab.reindex(members).mean()) if len(members) else None,
            "member_edge_recall_of_illicit": float(lab.reindex(members).sum() / n_pos) if n_pos else None}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores-val", type=Path, default=None, help="required for --aggregator cc")
    ap.add_argument("--scores-test", type=Path, default=None, help="required for --aggregator cc")
    ap.add_argument("--policy-dir", type=Path, default=None, help="expand: trained policy directory")
    ap.add_argument("--policy", choices=["rule", "rule_q"], default=None, help="expand: rule baseline B1 / B1b")
    ap.add_argument("--r1-dir", type=Path, default=None, help="expand: R1 run dir with scores / embeddings / checkpoints")
    ap.add_argument("--labels-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    ap.add_argument("--aggregator", choices=sorted(AGGREGATORS), default="cc")
    ap.add_argument("--choose-on", choices=["val"], default="val", help="only val is allowed (nothing is tuned on test)")
    ap.add_argument("--scope", choices=POLICIES, default="test_visible")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ring-gt", type=Path, default=None, help="default <processed_dir>/amlworld_ring_ground_truth.parquet")
    ap.add_argument("--rule", type=Path, default=RULE_PATH, help="threshold grid / objective (configs/threshold_rule.yaml)")
    ap.add_argument("--eval-window", type=Path, default=EVAL_WINDOW_YAML, help="evaluation windows (configs/eval_window.yaml)")
    ap.add_argument("--max-gap-hours", type=float, default=None, help="passed through to the aggregator (not searched)")
    ap.add_argument("--model-id", default="gine")
    ap.add_argument("--feature-set", choices=["trailing_closescycle", "legacy_forwardcycle"], default="trailing_closescycle",
                    help="which GFP parquets the scores come from; legacy_forwardcycle runs are pipeline checks, never reported")
    ap.add_argument("--seed", type=int, default=1, help="training seed of the scores (recorded; also the dry-run sample seed)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    if args.aggregator == "expand":
        from ringshield.expand import run_expand
        sub = ["--seed", str(args.seed), "--out", str(args.out), "--scope", args.scope, "--model-id", args.model_id,
               "--labels-dir", str(args.labels_dir), "--eval-window", str(args.eval_window)]
        sub += ["--policy-dir", str(args.policy_dir)] if args.policy_dir else ["--policy", args.policy or "rule"]
        sub += ["--r1-dir", str(args.r1_dir)] if args.r1_dir else []
        sub += ["--max-gap-hours", str(args.max_gap_hours)] if args.max_gap_hours is not None else []
        sub += ["--dry-run"] if args.dry_run else []
        return run_expand.main(sub)
    assert args.scores_val and args.scores_test, "--aggregator cc needs --scores-val and --scores-test"

    t0 = time.time()
    rule = yaml.safe_load(args.rule.read_text(encoding="utf-8"))
    grid_pct, grid_size = list(rule["grid"]["seed_frac_pct"]), list(rule["grid"]["min_size"])
    objective, match_thr, sweep = rule.get("objective", "ring_f1"), float(rule.get("match_threshold", 0.5)), list(rule.get("jaccard_sweep", []))
    paths = load_paths()
    ring_gt = args.ring_gt or paths["processed_dir"] / "amlworld_ring_ground_truth.parquet"
    aggregate = AGGREGATORS[args.aggregator]
    args.out.mkdir(parents=True, exist_ok=True)

    # 1. scored edges ------------------------------------------------------------------------
    se = {}
    for split, p in (("val", args.scores_val), ("test", args.scores_test)):
        df = build_scored_edges(p, split, model_id=args.model_id, seed=args.seed, processed_dir=paths["processed_dir"])
        if args.dry_run:
            df = df.sample(frac=DRY_RUN_FRAC, random_state=args.seed).sort_values("edge_id").reset_index(drop=True)
        se[split] = df
        print(f"[run_rings] {split}: {len(df):,} edges, {int(df['score_raw'].notna().sum()):,} scored, from {p}")
    calibrated = not se["test"]["score_calibrated"].equals(se["test"]["score_raw"])
    print(f"[run_rings] seed selection on {SELECT_COL}; confidence from {score_column(se['test'])} "
          f"({'calibrated' if calibrated else '== score_raw, no calibration yet'}); feature set {args.feature_set}")
    labels = {}
    for split in ("val", "test"):
        lp = args.labels_dir / f"labels_{split}.parquet"
        labels[split] = pd.read_parquet(lp) if lp.exists() else None

    # 2. grid search on VAL ------------------------------------------------------------------
    windows = {s: list(split_window(paths["processed_dir"] / f"amlworld_{s}.parquet")) for s in ("val", "test")}
    eval_windows = load_windows(args.eval_window)
    test_windows = {k: w for k, w in eval_windows.items() if w.split == "test"}
    wv = eval_windows["val"]
    assert list(wv.days_of(windows["val"])) == [wv.day_lo, wv.day_hi], "eval_window.yaml val days != the val split's days"
    truth_val, pat_val = load_ground_truth(ring_gt, *windows["val"], args.scope, verbose=False)
    grid_rows = []
    sc_val = se["val"][SELECT_COL].to_numpy(float)      # selection is always on score_raw
    sc_test = se["test"][SELECT_COL].to_numpy(float)
    for pct in grid_pct:
        q_val, q_test = threshold_for_pct(sc_val, pct), threshold_for_pct(sc_test, pct)
        plateau = {"val_q": q_val, "val_n_seeds": int(np.sum(sc_val > q_val)), "val_n_on_boundary": int(np.sum(sc_val == q_val)),
                   "test_q": q_test, "test_n_seeds": int(np.sum(sc_test > q_test)), "test_n_on_boundary": int(np.sum(sc_test == q_test))}
        for ms in grid_size:
            rings = aggregate(se["val"], pct, ms, args.max_gap_hours)
            m = evaluate_rings([r.member_set for r in rings], truth_val, match_thr, pat_val)
            grid_rows.append({"seed_frac_pct": pct, "min_size": ms, "n_rings": len(rings),
                              "ring_precision": round(m.ring_precision, 4), "ring_recall": round(m.ring_recall, 4),
                              "ring_f1": round(m.ring_f1, 4), "member_coverage": round(m.member_coverage, 4),
                              "n_matched": m.n_matched, **plateau})
            print(f"  val grid pct={pct:<5} min_size={ms}: rings {len(rings):5d}  P {m.ring_precision:.3f}  "
                  f"R {m.ring_recall:.3f}  F1 {m.ring_f1:.3f}  | seeds {plateau['val_n_seeds']:,} "
                  f"(+{plateau['val_n_on_boundary']:,} tied on the boundary, excluded)")
    grid_df = pd.DataFrame(grid_rows)
    # objective max; ties -> smaller seed_frac_pct, then larger min_size (configs/threshold_rule.yaml)
    best = grid_df.sort_values([objective, "seed_frac_pct", "min_size"], ascending=[False, True, False]).iloc[0]
    chosen = {"seed_frac_pct": float(best["seed_frac_pct"]), "min_size": int(best["min_size"]),
              "max_gap_hours": args.max_gap_hours, f"val_{objective}": float(best[objective])}
    print(f"[run_rings] chosen on val: {chosen}")

    config = {
        "experiment": args.out.name, "step": "4 (R2 baselines through B0)", "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(), "aggregator": args.aggregator, "aggregator_fn": f"{aggregate.__module__}.{aggregate.__name__}",
        "scores_val": str(args.scores_val), "scores_test": str(args.scores_test), "labels_dir": str(args.labels_dir),
        "ring_gt": str(ring_gt), "scope": args.scope, "choose_on": args.choose_on, "model_id": args.model_id, "seed": args.seed,
        "feature_set": args.feature_set, "reportable": args.feature_set != "legacy_forwardcycle",
        "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]),
        "calibrated": bool(not se["test"]["score_calibrated"].equals(se["test"]["score_raw"])),
        "score_column_note": "seeds are selected by a strict quantile cut on score_raw; isotonic calibration is monotone "
                             "but collapses the score to ~100-150 tie levels, so cutting the calibrated score would drop a "
                             "slice of the intended seeds at the boundary (gfpxgb: 264/960 at 0.1%). Calibrated scores feed "
                             "confidence / max_edge_prob, XAI weights and the expansion policy, not selection",
        "threshold_rule": str(args.rule), "objective": objective, "match_threshold": match_thr, "jaccard_sweep": sweep,
        "grid": {"seed_frac_pct": grid_pct, "min_size": grid_size}, "grid_results_val": grid_rows,
        "chosen": chosen, "scope_windows": windows, "dry_run": bool(args.dry_run),
        "eval_window": str(args.eval_window), "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()},
        "primary_block": "primary",
        "n_val_truth_rings": len(truth_val),
    }
    (args.out / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")

    # 3. TEST, exactly once ----------------------------------------------------------------------
    rings = aggregate(se["test"], chosen["seed_frac_pct"], chosen["min_size"], args.max_gap_hours, verbose=True)
    write_rings_parquet(rings, args.out / "rings.parquet")

    # 4. evaluate per window ----------------------------------------------------------------------
    blocks = evaluate_blocks(rings, se["test"], ring_gt, args.scope, test_windows, match_thr, sweep, labels=labels["test"])
    val_rings = aggregate(se["val"], chosen["seed_frac_pct"], chosen["min_size"], args.max_gap_hours)
    metrics = {"experiment": args.out.name, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "git_commit": _git_commit(), "aggregator": args.aggregator, "scope": args.scope, "chosen": chosen,
               "feature_set": args.feature_set, "reportable": args.feature_set != "legacy_forwardcycle",
               "selection_column": SELECT_COL, "confidence_column": score_column(se["test"]),
               "eval_windows": {k: w.as_dict() for k, w in eval_windows.items()}, "primary_block": "primary",
               "blocks": blocks,
               "test": blocks["primary"],  # alias: the reportable block
               "rings_total": {"n_rings": len(rings), "n_seed_edges": int(sum(len(r.seed_edges) for r in rings)),
                               "n_member_edges": int(sum(len(r.member_edges) for r in rings))},
               "test_seed_edges_vs_labels": seed_edge_precision(rings, labels["test"]),
               "test_boundary_plateau": {"q": threshold_for_pct(sc_test, chosen["seed_frac_pct"]),
                                         "n_on_boundary": int(np.sum(sc_test == threshold_for_pct(sc_test, chosen["seed_frac_pct"]))),
                                         "n_seeds": int(np.sum(sc_test > threshold_for_pct(sc_test, chosen["seed_frac_pct"])))},
               "val_at_chosen": ring_metrics_full([r.member_set for r in val_rings], truth_val, pat_val, match_thr, sweep),
               "val_seed_edges_vs_labels": seed_edge_precision(val_rings, labels["val"]),
               "seconds": round(time.time() - t0, 1)}
    (args.out / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_environment(args.out / "environment.txt")

    bp = metrics["test_boundary_plateau"]
    print(f"[run_rings] test seeds at the chosen cell: {bp['n_seeds']:,} (score > q = {bp['q']:.6f}); "
          f"{bp['n_on_boundary']:,} edges tied on the boundary, excluded")
    for name, t in blocks.items():
        tag = "PRIMARY" if name == "primary" else name
        print(f"\n[run_rings] {tag:7s} days {t['window']['days']} ({args.scope}, {t['n_truth']} truth rings): "
              f"{t['n_predicted']} rings | P {t['ring_precision']:.4f} R {t['ring_recall']:.4f} F1 {t['ring_f1']:.4f} | "
              f"R>=3 {t['ring_recall_ge3']} ({t['n_matched_ge3']}/{t['n_truth_ge3']}) | coverage {t['member_coverage']:.4f} | "
              f"J0.3 F1 {t['jaccard_sweep'].get('0.3', {}).get('ring_f1')} J0.7 F1 {t['jaccard_sweep'].get('0.7', {}).get('ring_f1')}")
        print("  per pattern: " + ", ".join(f"{k} {v['recall']:.2f} ({int(v['n_matched'])}/{int(v['n_truth'])})"
                                           for k, v in sorted(t.get("per_pattern", {}).items())))
        for pol, a in t["appendix"].items():
            print(f"  appendix {pol:8s}: {a['n_truth']} rings | P {a['ring_precision']:.4f} R {a['ring_recall']:.4f} F1 {a['ring_f1']:.4f}")
        sv = t.get("seed_edges_vs_labels")
        if sv:
            print(f"  seed edges in window: {sv['n_seed_edges']:,} | precision {sv['seed_edge_precision'] if sv['seed_edge_precision'] is None else round(sv['seed_edge_precision'], 4)} "
                  f"| illicit recall {sv['seed_edge_recall_of_illicit']:.4f} of {sv['n_illicit_in_window']:,}")
    print(f"-> {args.out}")
    return metrics


if __name__ == "__main__":
    main()
