"""
Logistic Regression baseline — E5a (RingShield Phase 5).
Transaction-level binary classification on AMLworld HI-Small.

Usage:
    python baselines/logistic_regression_aml.py \
        --data-dir data/processed \
        --out-dir experiments/E5a_logistic_regression
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
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, average_precision_score
from sklearn.preprocessing import StandardScaler
import joblib

SEED = 42
FEATURE_COLS = None  # auto-detected


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
    lines = [f"python: {sys.version}", f"platform: {platform.platform()}"]
    try:
        freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
        lines.append("\n# pip freeze\n" + freeze)
    except Exception:
        pass
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--out-dir", type=Path, default=Path("experiments/E5a_logistic_regression"))
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading AMLworld data...")
    X_train, y_train, X_test, y_test, feature_cols = load_data(args.data_dir)
    print(f"  Train: {len(y_train)} ({y_train.sum()} laundering)")
    print(f"  Test:  {len(y_test)} ({y_test.sum()} laundering)")
    print(f"  Features: {len(feature_cols)}")

    print("Scaling features...")
    scaler = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test = scaler.transform(X_test)

    print("Training Logistic Regression (class_weight='balanced')...")
    start = time.time()
    model = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        solver="lbfgs",
        random_state=SEED,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)
    elapsed = time.time() - start
    print(f"  Training done in {elapsed:.1f}s")

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    test_metrics = compute_metrics(y_test, y_pred, y_prob)

    y_pred_train = model.predict(X_train)
    train_metrics = compute_metrics(y_train, y_pred_train)

    print(f"  Train minority-F1: {train_metrics['f1_minority']:.4f}")
    print(f"  Test  minority-F1: {test_metrics['f1_minority']:.4f}")
    print(f"  Test  AP:          {test_metrics['average_precision']:.4f}")

    # Save artifacts
    config = {
        "experiment": "E5a_logistic_regression",
        "model": "LogisticRegression",
        "dataset": "AMLworld HI-Small",
        "class_weight": "balanced",
        "solver": "lbfgs",
        "max_iter": 1000,
        "seed": SEED,
        "feature_dim": len(feature_cols),
        "features": feature_cols,
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({
        "train": train_metrics, "test": test_metrics,
        "training_time_seconds": elapsed,
    }, indent=2), encoding="utf-8")

    pd.DataFrame({"true_label": y_test, "predicted_label": y_pred, "pred_prob": y_prob}
                 ).to_csv(args.out_dir / "predictions.csv", index=False)
    joblib.dump(model, args.out_dir / "model.pkl")
    pd.DataFrame([{"training_time_seconds": elapsed}]).to_csv(
        args.out_dir / "training_log.csv", index=False)
    write_environment(args.out_dir / "environment.txt")

    print(f"\nArtifacts written to {args.out_dir}/")


if __name__ == "__main__":
    main()
