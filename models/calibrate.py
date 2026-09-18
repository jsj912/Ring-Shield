"""Score calibration (Step 3c / Step 4.3): isotonic regression fit on the validation split.

    python models/calibrate.py --scores-dir experiments/R2_b0/gfpxgb_scores --seeds 1 2 3 4 5
    python models/calibrate.py --scores-dir experiments/R1_gine_causal --seeds 1 2 3 4 5

For every seed: the calibrator is fit on the VAL scores against contract/out/labels_val.parquet
and applied to the TEST scores; the val scores themselves get cross-fitted values (K-fold on
val, default 5, so no val edge is calibrated by a model that saw its own label). The result
is written back as a `score_calibrated` column in scores_<split>_seed<S>.parquet (score_raw is
kept unchanged; rows and order unchanged), plus <scores-dir>/calibration.json with Brier score
and expected calibration error (15 equal-mass bins) before / after on val (cross-fitted) and
test, per seed and averaged. Isotonic regression is monotone, so quantile-based seed selection
is unchanged; what changes is the meaning of `confidence` across seeds and detectors.

Labels are internal (never joined into a shipped file); the calibrator only ever sees val
labels. --dry-run uses the *_dryrun score / label files.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss
from sklearn.model_selection import StratifiedKFold

REPO_ROOT = Path(__file__).resolve().parents[1]
LABELS_DIR = REPO_ROOT / "contract" / "out"
N_BINS = 15


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def ece(y: np.ndarray, p: np.ndarray, n_bins: int = N_BINS) -> float:
    """Expected calibration error with equal-mass bins (quantile edges of p)."""
    order = np.argsort(p, kind="stable")
    y, p = y[order], p[order]
    bins = np.array_split(np.arange(len(p)), n_bins)
    total = 0.0
    for b in bins:
        if len(b) == 0:
            continue
        total += len(b) / len(p) * abs(y[b].mean() - p[b].mean())
    return float(total)


def fit_isotonic(s: np.ndarray, y: np.ndarray) -> IsotonicRegression:
    iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    iso.fit(s, y)
    return iso


def calibrate_seed(scores_dir: Path, seed: int, labels_dir: Path, suffix: str, n_folds: int, rng_seed: int) -> dict:
    val = pd.read_parquet(scores_dir / f"scores_val_seed{seed}{suffix}.parquet")
    test = pd.read_parquet(scores_dir / f"scores_test_seed{seed}{suffix}.parquet")
    lab_val = pd.read_parquet(labels_dir / f"labels_val{suffix}.parquet").set_index("edge_id")["true_label"]
    lab_test = pd.read_parquet(labels_dir / f"labels_test{suffix}.parquet").set_index("edge_id")["true_label"]
    y_val = lab_val.reindex(val["edge_id"]).to_numpy(np.int64)
    y_test = lab_test.reindex(test["edge_id"]).to_numpy(np.int64)
    assert not np.isnan(y_val.astype(float)).any() and not np.isnan(y_test.astype(float)).any(), "label join failed"
    s_val, s_test = val["score_raw"].to_numpy(float), test["score_raw"].to_numpy(float)

    # cross-fitted val
    c_val = np.empty_like(s_val)
    skf = StratifiedKFold(n_splits=n_folds, shuffle=True, random_state=rng_seed)
    for tr, te in skf.split(s_val, y_val):
        c_val[te] = fit_isotonic(s_val[tr], y_val[tr]).predict(s_val[te])
    # full-val fit for test
    iso = fit_isotonic(s_val, y_val)
    c_test = iso.predict(s_test)

    val["score_calibrated"] = c_val
    test["score_calibrated"] = c_test
    val.to_parquet(scores_dir / f"scores_val_seed{seed}{suffix}.parquet", index=False)
    test.to_parquet(scores_dir / f"scores_test_seed{seed}{suffix}.parquet", index=False)

    rep = {"seed": seed, "n_folds": n_folds, "n_isotonic_knots": int(len(iso.X_thresholds_)),
           "val_cross_fitted": {"brier_raw": float(brier_score_loss(y_val, s_val)), "brier_cal": float(brier_score_loss(y_val, c_val)),
                                "ece_raw": ece(y_val, s_val), "ece_cal": ece(y_val, c_val)},
           "test": {"brier_raw": float(brier_score_loss(y_test, s_test)), "brier_cal": float(brier_score_loss(y_test, c_test)),
                    "ece_raw": ece(y_test, s_test), "ece_cal": ece(y_test, c_test)},
           "monotone_check": bool(np.all(np.diff(c_test[np.argsort(s_test, kind="stable")]) >= -1e-12)),
           "n_unique_raw_test": int(len(np.unique(s_test))), "n_unique_cal_test": int(len(np.unique(c_test)))}
    print(f"  seed {seed}: val(cv) Brier {rep['val_cross_fitted']['brier_raw']:.5f}->{rep['val_cross_fitted']['brier_cal']:.5f} "
          f"ECE {rep['val_cross_fitted']['ece_raw']:.4f}->{rep['val_cross_fitted']['ece_cal']:.4f} | test Brier "
          f"{rep['test']['brier_raw']:.5f}->{rep['test']['brier_cal']:.5f} ECE {rep['test']['ece_raw']:.4f}->{rep['test']['ece_cal']:.4f} "
          f"| knots {rep['n_isotonic_knots']} | unique test scores {rep['n_unique_raw_test']:,}->{rep['n_unique_cal_test']:,}")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores-dir", type=Path, required=True)
    ap.add_argument("--seeds", "--seed", dest="seeds", type=int, nargs="+", required=True)
    ap.add_argument("--labels-dir", type=Path, default=LABELS_DIR)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--rng-seed", type=int, default=0, help="fold shuffling")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    suffix = "_dryrun" if args.dry_run else ""
    reps = [calibrate_seed(args.scores_dir, s, args.labels_dir, suffix, args.folds, args.rng_seed) for s in args.seeds]
    mean = lambda k1, k2: float(np.mean([r[k1][k2] for r in reps]))
    out = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "scores_dir": str(args.scores_dir), "method": "isotonic (sklearn IsotonicRegression, clip out of bounds)",
           "fit_on": "val labels; val values cross-fitted (StratifiedKFold)", "labels_dir": str(args.labels_dir),
           "ece_bins": N_BINS, "per_seed": reps,
           "mean": {"val_cv": {k: mean("val_cross_fitted", k) for k in ("brier_raw", "brier_cal", "ece_raw", "ece_cal")},
                    "test": {k: mean("test", k) for k in ("brier_raw", "brier_cal", "ece_raw", "ece_cal")}}}
    (args.scores_dir / f"calibration{suffix}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"[calibrate] -> {args.scores_dir / f'calibration{suffix}.json'}")


if __name__ == "__main__":
    main()
