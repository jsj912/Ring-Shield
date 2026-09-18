"""
GFP XGBoost with real per-edge pattern features + Optuna tuning — E5b v3.

Uses per-transaction GFP features (fan-in/out, scatter-gather, temporal cycles)
computed by graph/motif_features.py v2, instead of the per-node proxy features.

Usage:
    python baselines/gfp_xgboost_aml.py \
        --data-dir data/processed \
        --out-dir experiments/E5b_gfp_xgboost \
        --n-trials 50

Step 4 refit (model_id 'gfpxgb', supersedes the E5b figure; E5b itself is retired):

    python baselines/gfp_xgboost_aml.py --refit-from experiments/E5b_gfp_xgboost/config.yaml \
        --seeds 1 2 3 4 5 --out-dir experiments/R2_b0/gfpxgb_scores

Takes the E5b best hyper-parameters including num_round (fixed, no early stopping -- exactly
how E5b fit its final model; with early stopping at patience 30 the val aucpr curve's noisy
first rounds stopped three of five seeds after 1-5 trees), fits on TRAIN only once per XGBoost
seed (val is only scored, never fit on), and writes scores_<split>_seed<S>.parquet (edge_id,
timestamp, score_raw = predict_proba) for val and test in the models/score.py layout, plus
config.yaml / metrics.json / environment.txt. The GFP parquets must be the re-keyed, trailing
(Step 3b-z) files: the EdgeID join is asserted one-to-one and the schema metadata is checked.
Feature set: the 7 transaction fields (amounts, currencies, payment format, hour, weekday) +
the 10 GFP columns. Not used: day_index (absolute calendar day -- identifies the split and the
test tail), the sender_*/receiver_* train-period account aggregates (look ahead within train,
docs/FEATURE_CAUSALITY.md section 6), from_bank/to_bank (not in E5b's 28 features).
"""

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
import xgboost as xgb
import optuna
from sklearn.metrics import f1_score, precision_score, recall_score, average_precision_score

optuna.logging.set_verbosity(optuna.logging.WARNING)

SEED = 42
GFP_COLS = ["fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst", "deg_in_dst",
            "scatter_gather", "gather_scatter", "temporal_cycle", "cycle_length"]
REFIT_TABULAR = ["Amount Sent", "Sent Currency", "Amount Received", "Received Currency", "Payment Format",
                 "hour_of_day", "day_of_week"]
REFIT_EXCLUDED = ["day_index", "from_bank", "to_bank"] + [f"{p}_{k}" for p in ("sender_out", "receiver_in")
                                                          for k in ("degree", "amount_mean", "amount_std", "amount_max",
                                                                    "volume_total")]


def load_split_for_refit(data_dir: Path, split: str):
    """Split parquet + trailing GFP parquet, joined 1:1 on EdgeID; asserts the re-keyed files."""
    import pyarrow.parquet as pq
    df = pd.read_parquet(data_dir / f"amlworld_{split}.parquet")
    gfp_path = data_dir / f"amlworld_gfp_features_{split}.parquet"
    gfp = pd.read_parquet(gfp_path)
    meta = pq.ParquetFile(gfp_path).schema_arrow.metadata or {}
    assert b"gfp" in meta and json.loads(meta[b"gfp"]).get("trailing"), \
        f"{gfp_path}: not the Step 3b-z trailing GFP parquet (no 'gfp' schema metadata)"
    assert gfp["EdgeID"].is_unique and set(gfp["EdgeID"]) == set(df["EdgeID"]), \
        f"{gfp_path}: EdgeID set differs from the split parquet (not re-keyed / edge_id aligned)"
    df = df.merge(gfp, on="EdgeID", how="inner", validate="one_to_one")
    assert len(df) == len(gfp) and not df[GFP_COLS].isna().any().any()
    feature_cols = REFIT_TABULAR + GFP_COLS
    return df, df[feature_cols].values.astype(np.float32), df["Is Laundering"].values.astype(np.int64), feature_cols


def refit(args):
    """Step 4: E5b best params, five XGBoost seeds, train-only fit, val/test score files."""
    from datetime import datetime, timezone
    cfg = yaml.safe_load(Path(args.refit_from).read_text(encoding="utf-8"))
    best = dict(cfg["best_params"])
    num_round = int(best.pop("num_round"))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    frames, X, y = {}, {}, {}
    for split in ("train", "val", "test"):
        frames[split], X[split], y[split], feature_cols = load_split_for_refit(args.data_dir, split)
        if args.dry_run:
            rng = np.random.default_rng(args.seeds[0])
            keep = np.sort(rng.choice(len(y[split]), size=max(1, len(y[split]) // 100), replace=False))
            frames[split], X[split], y[split] = frames[split].iloc[keep].reset_index(drop=True), X[split][keep], y[split][keep]
        print(f"  {split}: {len(y[split]):,} rows, {int(y[split].sum()):,} illicit")
    print(f"  features ({len(feature_cols)}): {feature_cols}")
    dtrain = xgb.DMatrix(X["train"], label=y["train"], feature_names=feature_cols)
    dval = xgb.DMatrix(X["val"], label=y["val"], feature_names=feature_cols)
    dtest = xgb.DMatrix(X["test"], feature_names=feature_cols)

    per_seed, logs = [], {}
    for seed in args.seeds:
        params = {"objective": "binary:logistic", "eval_metric": "aucpr", "tree_method": "hist", "device": "cpu",
                  "seed": int(seed), **best}
        t1 = time.time()
        evals_result = {}
        model = xgb.train(params, dtrain, num_boost_round=num_round, evals=[(dval, "val")],
                          evals_result=evals_result, verbose_eval=False)      # fixed rounds, as E5b's final fit
        curve = evals_result["val"]["aucpr"]
        best_iter = int(np.argmax(curve))                                    # informational only
        p_val = model.predict(dval)
        p_test = model.predict(dtest)
        for split, p in (("val", p_val), ("test", p_test)):
            out = pd.DataFrame({"edge_id": frames[split]["EdgeID"].to_numpy(np.int64),
                                "timestamp": frames[split]["Timestamp"].to_numpy(np.int64),
                                "score_raw": p.astype(np.float64)}).sort_values("edge_id").reset_index(drop=True)
            tag = f"{split}_seed{seed}" + ("_dryrun" if args.dry_run else "")
            out.to_parquet(args.out_dir / f"scores_{tag}.parquet", index=False)
        model.save_model(str(args.out_dir / f"model_seed{seed}.json"))
        ap_val = average_precision_score(y["val"], p_val)
        ap_test = average_precision_score(y["test"], p_test)
        imp = model.get_score(importance_type="gain")
        gfp_pct = 100 * sum(v for k, v in imp.items() if k in GFP_COLS) / max(sum(imp.values()), 1e-12)
        per_seed.append({"seed": int(seed), "rounds": num_round, "val_aucpr_argmax_round_informational": best_iter,
                         "val_aucpr_final": float(curve[-1]), "val_aucpr_max": float(max(curve)),
                         "val_ap": float(ap_val), "test_ap_whole_split_informational": float(ap_test),
                         "gfp_gain_pct": float(gfp_pct), "seconds": round(time.time() - t1, 1),
                         "top_features": [k for k, _ in sorted(imp.items(), key=lambda kv: -kv[1])[:8]]})
        logs[seed] = evals_result["val"]["aucpr"]
        print(f"  seed {seed}: {num_round} rounds (val aucpr max {max(curve):.4f} at round {best_iter}, final {curve[-1]:.4f}) "
              f"| val AP {ap_val:.4f} | GFP gain {gfp_pct:.1f}% | {time.time() - t1:.0f}s")
    pd.DataFrame({f"seed{s}": pd.Series(v) for s, v in logs.items()}).to_csv(args.out_dir / "training_log.csv", index_label="round")
    config = {
        "experiment": args.out_dir.name, "model_id": "gfpxgb", "step": "4.3 (R2 gfpxgb refit; supersedes E5b, which is retired)",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "refit_from": str(args.refit_from), "e5b_best_params": cfg["best_params"], "e5b_best_val_f1": cfg.get("best_val_f1"),
        "params_used": {**best, "num_round": num_round, "early_stopping": None},
        "early_stopping_note": "not used: with patience 30 on val aucpr the noisy first rounds stopped seeds 1-3 after "
                               "1-5 trees (val AP 0.12-0.15) while seed 4 ran to round 512 (val AP 0.37); E5b's own final "
                               "fit used the fixed num_round, so the refit does too",
        "fit_on": "train only (E5b refit on train+val; here val must stay out-of-sample for thresholds and grids)",
        "seeds": [int(s) for s in args.seeds], "seed_source": "configs/seeds.yaml",
        "feature_cols": feature_cols, "excluded_features": REFIT_EXCLUDED,
        "feature_set": "trailing_closescycle", "gfp_parquets": "data/processed/amlworld_gfp_features_<split>.parquet (re-keyed, trailing; asserted)",
        "outputs": "scores_<split>_seed<S>.parquet (edge_id, timestamp, score_raw = predict_proba), val + test",
        "dry_run": bool(args.dry_run), "seconds": round(time.time() - t0, 1),
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({"per_seed": per_seed, "note": "edge metrics per window: "
                                                           "evaluation/edge_metrics.py; ring rows: ringshield/run_rings.py"},
                                                          indent=2), encoding="utf-8")
    write_environment(args.out_dir / "environment.txt")
    print(f"[gfpxgb] wrote {args.out_dir}")


def load_split_with_gfp(data_dir: Path, split: str):
    """Load tabular features + per-edge GFP features for a split."""
    df = pd.read_parquet(data_dir / f"amlworld_{split}.parquet")
    gfp = pd.read_parquet(data_dir / f"amlworld_gfp_features_{split}.parquet")

    # Join GFP features on EdgeID
    df = df.merge(gfp, on="EdgeID", how="left")
    gfp_cols = [c for c in gfp.columns if c != "EdgeID"]
    for col in gfp_cols:
        df[col] = df[col].fillna(0)

    meta_cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering",
                 "ring_id", "pattern_type"]
    feature_cols = [c for c in df.columns if c not in meta_cols]

    return df[feature_cols].values, df["Is Laundering"].values, feature_cols


def compute_metrics(y_true, y_pred, y_prob=None):
    m = {
        "f1_minority": f1_score(y_true, y_pred, pos_label=1, zero_division=0),
        "precision_minority": precision_score(y_true, y_pred, pos_label=1, zero_division=0),
        "recall_minority": recall_score(y_true, y_pred, pos_label=1, zero_division=0),
    }
    if y_prob is not None:
        m["average_precision"] = average_precision_score(y_true, y_prob)
    return m


def write_environment(path: Path):
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}",
             f"xgboost: {xgb.__version__}", f"optuna: {optuna.__version__}"]
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/E5b_gfp_xgboost"))
    parser.add_argument("--n-trials", type=int, default=50)
    parser.add_argument("--max-rounds", type=int, default=1000)
    parser.add_argument("--refit-from", type=Path, default=None,
                        help="Step 4 refit mode: E5b config.yaml with best_params; no Optuna")
    parser.add_argument("--seeds", "--seed", dest="seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--dry-run", action="store_true", help="refit mode: 1%% of every split")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.refit_from is not None:
        refit(args)
        return

    # --- Load data ---
    print("Loading AMLworld data + per-edge GFP features...")
    X_train, y_train, feature_cols = load_split_with_gfp(args.data_dir, "train")
    X_val, y_val, _ = load_split_with_gfp(args.data_dir, "val")
    X_test, y_test, _ = load_split_with_gfp(args.data_dir, "test")

    n_tabular = len([c for c in feature_cols if c not in [
        "fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst",
        "deg_in_dst", "scatter_gather", "gather_scatter", "temporal_cycle",
        "cycle_length"]])
    n_gfp = len(feature_cols) - n_tabular
    print(f"  Features: {len(feature_cols)} total ({n_tabular} tabular + {n_gfp} GFP)")
    print(f"  Train: {len(y_train)} ({y_train.sum()} laund)")
    print(f"  Val:   {len(y_val)} ({y_val.sum()} laund)")
    print(f"  Test:  {len(y_test)} ({y_test.sum()} laund)")

    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    base_spw = n_neg / n_pos
    print(f"  Base scale_pos_weight: {base_spw:.1f}")

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_cols)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_cols)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=feature_cols)

    # --- Optuna search ---
    print(f"\nStarting Optuna search ({args.n_trials} trials)...")
    t_search_start = time.time()

    def objective(trial):
        params = {
            "objective": "binary:logistic",
            "eval_metric": "aucpr",
            "tree_method": "hist",
            "device": "cpu",
            "seed": SEED,
            "max_depth": trial.suggest_int("max_depth", 3, 12),
            "learning_rate": trial.suggest_float("learning_rate", 0.003, 0.1, log=True),
            "scale_pos_weight": trial.suggest_float("scale_pos_weight", base_spw * 0.3, base_spw * 1.5),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 50),
            "gamma": trial.suggest_float("gamma", 0, 5.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
        }
        num_round = trial.suggest_int("num_round", 50, args.max_rounds)

        model = xgb.train(
            params, dtrain,
            num_boost_round=num_round,
            evals=[(dval, "val")],
            early_stopping_rounds=30,
            verbose_eval=False,
        )

        y_prob_val = model.predict(dval)
        y_pred_val = (y_prob_val >= 0.5).astype(int)
        return f1_score(y_val, y_pred_val, pos_label=1, zero_division=0)

    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=SEED))
    study.optimize(objective, n_trials=args.n_trials, show_progress_bar=True)

    t_search_elapsed = time.time() - t_search_start
    best = study.best_trial
    print(f"\nOptuna done in {t_search_elapsed:.1f}s")
    print(f"  Best val F1: {best.value:.4f}  (trial {best.number})")
    print(f"  Best params: {json.dumps(best.params, indent=4)}")

    # --- Final model on train+val ---
    print("\nRetraining on train+val with best params...")
    best_params = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "tree_method": "hist",
        "device": "cpu",
        "seed": SEED,
        **{k: v for k, v in best.params.items() if k != "num_round"},
    }

    X_trainval = np.vstack([X_train, X_val])
    y_trainval = np.concatenate([y_train, y_val])
    dtrainval = xgb.DMatrix(X_trainval, label=y_trainval, feature_names=feature_cols)

    t_final = time.time()
    evals_result = {}
    final_model = xgb.train(
        best_params, dtrainval,
        num_boost_round=best.params["num_round"],
        evals=[(dtrainval, "trainval"), (dtest, "test")],
        evals_result=evals_result,
        verbose_eval=50,
    )
    t_final_elapsed = time.time() - t_final

    y_prob = final_model.predict(dtest)
    y_pred = (y_prob >= 0.5).astype(int)
    test_metrics = compute_metrics(y_test, y_pred, y_prob)

    y_prob_tv = final_model.predict(dtrainval)
    y_pred_tv = (y_prob_tv >= 0.5).astype(int)
    tv_metrics = compute_metrics(y_trainval, y_pred_tv, y_prob_tv)

    print(f"  Trainval minority-F1: {tv_metrics['f1_minority']:.4f}")
    print(f"  Test    minority-F1:  {test_metrics['f1_minority']:.4f}")
    print(f"  Test    AP:           {test_metrics['average_precision']:.4f}")

    importance = final_model.get_score(importance_type="gain")
    importances = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    gfp_names = {"fan_out", "fan_in", "deg_out_src", "deg_in_src", "deg_out_dst",
                 "deg_in_dst", "scatter_gather", "gather_scatter", "temporal_cycle",
                 "cycle_length"}
    print("  Top 10 features:")
    for name, imp in importances[:10]:
        tag = " [GFP]" if name in gfp_names else ""
        print(f"    {name}: {imp:.1f}{tag}")

    gfp_imp = sum(v for k, v in importance.items() if k in gfp_names)
    total_imp = sum(importance.values())
    gfp_pct = gfp_imp / total_imp * 100 if total_imp else 0
    print(f"  GFP features contribute {gfp_pct:.1f}% of total gain")

    # --- Save ---
    config = {
        "experiment": "E5b_gfp_xgboost",
        "model": "XGBoost + real per-edge GFP features + Optuna",
        "dataset": "AMLworld HI-Small",
        "split": "60/20/20",
        "gfp_version": "v2 (per-edge exact pattern counting)",
        "optuna_n_trials": args.n_trials,
        "best_trial": best.number,
        "best_val_f1": best.value,
        "best_params": best.params,
        "seed": SEED,
        "feature_dim": len(feature_cols),
        "gfp_gain_pct": gfp_pct,
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({
        "trainval": tv_metrics, "test": test_metrics,
        "best_val_f1": best.value,
        "search_time_seconds": t_search_elapsed,
        "final_training_time_seconds": t_final_elapsed,
        "feature_importances": {k: float(v) for k, v in importances},
        "gfp_gain_pct": gfp_pct,
    }, indent=2), encoding="utf-8")

    pd.DataFrame({"true_label": y_test, "predicted_label": y_pred, "pred_prob": y_prob}
                 ).to_csv(args.out_dir / "predictions.csv", index=False)
    final_model.save_model(str(args.out_dir / "model.json"))

    if "trainval" in evals_result and "test" in evals_result:
        log_df = pd.DataFrame({
            "round": range(len(evals_result["trainval"]["aucpr"])),
            "trainval_aucpr": evals_result["trainval"]["aucpr"],
            "test_aucpr": evals_result["test"]["aucpr"],
        })
        log_df.to_csv(args.out_dir / "training_log.csv", index=False)

    write_environment(args.out_dir / "environment.txt")

    print(f"\nArtifacts written to {args.out_dir}/")
    print(f"\n*** E5b v3 — real GFP + Optuna + 60/20/20 ***")
    print(f"*** Test minority-F1 = {test_metrics['f1_minority']:.4f} ***")


if __name__ == "__main__":
    main()