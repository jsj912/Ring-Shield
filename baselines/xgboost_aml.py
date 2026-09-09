"""
XGBoost baseline — E5a (RingShield Phase 5).
Transaction-level binary classification on AMLworld HI-Small.
Uses GPU acceleration (tree_method='gpu_hist') on the RTX A5000.

Usage:
    python baselines/xgboost_aml.py \
        --data-dir data/processed \
        --out-dir experiments/E5a_xgboost
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
from sklearn.metrics import f1_score, precision_score, recall_score, average_precision_score

SEED = 42


def load_data(data_dir: Path):
    train = pd.read_parquet(data_dir / "amlworld_train.parquet")
    test = pd.read_parquet(data_dir / "amlworld_test.parquet")

    meta_cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering",
                 "ring_id", "pattern_type"]
    feature_cols = [c for c in train.columns if c not in meta_cols]

    X_train = train[feature_cols].values
    y_train = train["Is Laundering"].values
    X_test = test[feature_cols].values
    y_test = test["Is Laundering"].values

    return X_train, y_train, X_test, y_test, feature_cols


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
             f"xgboost: {xgb.__version__}"]
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/E5a_xgboost"))
    parser.add_argument("--n-rounds", type=int, default=500)
    parser.add_argument("--early-stopping", type=int, default=30)
    parser.add_argument("--max-depth", type=int, default=8)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--no-gpu", action="store_true", help="Force CPU even if GPU available")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading AMLworld data...")
    X_train, y_train, X_test, y_test, feature_cols = load_data(args.data_dir)
    print(f"  Train: {len(y_train)} ({y_train.sum()} laundering)")
    print(f"  Test:  {len(y_test)} ({y_test.sum()} laundering)")
    print(f"  Features: {len(feature_cols)}")

    # Compute scale_pos_weight for class imbalance
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    scale_pos_weight = n_neg / n_pos
    print(f"  scale_pos_weight: {scale_pos_weight:.1f} (1 illicit per {scale_pos_weight:.0f} licit)")

    # Choose device — XGBoost 2.0+ uses device='cuda' with tree_method='hist'
    # (gpu_hist was removed in 2.0)
    device = "cpu" if args.no_gpu else "cuda"
    print(f"  Using device: {device}")

    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_cols)
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=feature_cols)

    params = {
        "objective": "binary:logistic",
        "eval_metric": "aucpr",
        "tree_method": "hist",
        "device": device,
        "max_depth": args.max_depth,
        "learning_rate": args.lr,
        "scale_pos_weight": scale_pos_weight,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "seed": SEED,
    }

    print(f"Training XGBoost (max {args.n_rounds} rounds, early_stopping={args.early_stopping})...")
    start = time.time()
    evals_result = {}
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=args.n_rounds,
        evals=[(dtrain, "train"), (dtest, "test")],
        evals_result=evals_result,
        early_stopping_rounds=args.early_stopping,
        verbose_eval=50,
    )
    elapsed = time.time() - start
    best_round = model.best_iteration
    print(f"  Training done in {elapsed:.1f}s (best round: {best_round})")

    # Predictions
    y_prob = model.predict(dtest)
    y_pred = (y_prob >= 0.5).astype(int)
    test_metrics = compute_metrics(y_test, y_pred, y_prob)

    y_prob_train = model.predict(dtrain)
    y_pred_train = (y_prob_train >= 0.5).astype(int)
    train_metrics = compute_metrics(y_train, y_pred_train, y_prob_train)

    print(f"  Train minority-F1: {train_metrics['f1_minority']:.4f}")
    print(f"  Test  minority-F1: {test_metrics['f1_minority']:.4f}")
    print(f"  Test  AP:          {test_metrics['average_precision']:.4f}")

    # Feature importances
    importance = model.get_score(importance_type="gain")
    importances = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    print("  Top 5 features:")
    for name, imp in importances[:5]:
        print(f"    {name}: {imp:.1f}")

    # Save artifacts
    config = {
        "experiment": "E5a_xgboost",
        "model": "XGBoost",
        "dataset": "AMLworld HI-Small",
        "n_rounds": args.n_rounds,
        "best_round": best_round,
        "early_stopping": args.early_stopping,
        "max_depth": args.max_depth,
        "lr": args.lr,
        "scale_pos_weight": float(scale_pos_weight),
        "tree_method": "hist",
        "device": device,
        "seed": SEED,
        "feature_dim": len(feature_cols),
        "features": feature_cols,
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({
        "train": train_metrics, "test": test_metrics,
        "training_time_seconds": elapsed, "best_round": best_round,
        "feature_importances": {k: float(v) for k, v in importances},
    }, indent=2), encoding="utf-8")

    pd.DataFrame({"true_label": y_test, "predicted_label": y_pred, "pred_prob": y_prob}
                 ).to_csv(args.out_dir / "predictions.csv", index=False)
    model.save_model(str(args.out_dir / "model.pkl"))

    # Training log from evals_result
    log_df = pd.DataFrame({
        "round": range(len(evals_result["train"]["aucpr"])),
        "train_aucpr": evals_result["train"]["aucpr"],
        "test_aucpr": evals_result["test"]["aucpr"],
    })
    log_df.to_csv(args.out_dir / "training_log.csv", index=False)
    write_environment(args.out_dir / "environment.txt")

    print(f"\nArtifacts written to {args.out_dir}/")


if __name__ == "__main__":
    main()