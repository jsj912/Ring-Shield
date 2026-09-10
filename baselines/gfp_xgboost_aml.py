"""
GFP XGBoost with real per-edge pattern features + Optuna tuning — E5b v3.

Uses per-transaction GFP features (fan-in/out, scatter-gather, temporal cycles)
computed by graph/motif_features.py v2, instead of the per-node proxy features.

Usage:
    python baselines/gfp_xgboost_aml.py \
        --data-dir data/processed \
        --out-dir experiments/E5b_gfp_xgboost \
        --n-trials 50
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
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

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