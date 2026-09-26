"""Cross-fitted TRAIN scores for the gfpxgb detector (Step 10.2, R6).

    python baselines/gfp_xgboost_crossfit.py --dry-run
    python baselines/gfp_xgboost_crossfit.py

The R6 swap retrains the expansion policy on each detector, and the policy's detector feature is
the within-split score quantile of an edge under a model that never saw it (Step 6 amendment a).
`experiments/R2_b0/gfpxgb_scores/` already holds the five-seed refit and its val / test scores;
what is missing is the train split, because a model fit on train scores its own training edges.
This script fills exactly that gap and nothing else -- it does not retrain, re-tune or re-score
anything that exists.

Same recipe as the refit (`baselines/gfp_xgboost_aml.py --refit-from`): E5b's Optuna parameters,
fixed `num_round` (no early stopping, for the reason recorded in that run's config), and its 17
causal features (7 transaction fields + the 10 trailing GFP columns; `day_index`, the
`sender_*` / `receiver_*` train-period aggregates and the bank ids stay excluded). The folds are
`ringshield/expand/cross_score.py`'s own day-aligned assignment, so a gfpxgb policy row and a
gine policy row are built over the same partition of the train days.

Output (`--out-dir`, default `experiments/R6_gfpxgb_cross/`): `cross_scores_train.parquet` in the
schema `cross_score.py` writes -- edge_id, timestamp, day, fold, score_raw, score_quantile,
dead_region, score_calibrated -- plus `cross_scores.json` with the fold table and the same
no-edge-scored-by-a-model-that-saw-its-day assertion. Two columns cannot carry over and say so in
the JSON: `dead_region` is always False (it is a property of the GNN head's constant outputs; a
gradient-boosted tree has no such region) and `score_calibrated` is NaN (the policy does not use
it). The policy variant trained on this file therefore drops both the `embedding` and the
`dead_region` feature groups, which is why the r6 table footnotes the gfpxgb column as
policy-variant rather than detector-only.
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
import xgboost as xgb
import yaml
from sklearn.metrics import average_precision_score, f1_score

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from baselines.gfp_xgboost_aml import load_split_for_refit  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.expand.cross_score import days_of, fold_assignment  # noqa: E402

REFIT_DIR = REPO_ROOT / "experiments" / "R2_b0" / "gfpxgb_scores"
FIXED = {"objective": "binary:logistic", "eval_metric": "aucpr", "tree_method": "hist", "device": "cpu"}


def git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def refit_params(config_yaml: Path) -> tuple[dict, int]:
    """The parameters the shipped gfpxgb seeds were fit with (R2_b0/gfpxgb_scores/config.yaml)."""
    used = dict(yaml.safe_load(config_yaml.read_text(encoding="utf-8"))["params_used"])
    num_round = int(used.pop("num_round"))
    used.pop("early_stopping", None)
    return used, num_round


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments" / "R6_gfpxgb_cross")
    ap.add_argument("--params-from", type=Path, default=REFIT_DIR / "config.yaml")
    ap.add_argument("--seed", type=int, default=1, help="the XGBoost seed the fold models use")
    ap.add_argument("--dry-run", action="store_true", help="20 rounds, one fold, nothing written")
    a = ap.parse_args(argv)
    t0 = time.time()
    params, num_round = refit_params(a.params_from)
    if a.dry_run:
        num_round = 20
    print(f"[crossfit] gfpxgb params from {a.params_from} ({num_round} rounds, seed {a.seed})")

    df, X, y, cols = load_split_for_refit(load_paths()["processed_dir"], "train")
    edge_id = df["EdgeID"].to_numpy(np.int64)
    ts = df["Timestamp"].to_numpy(np.int64)
    day = days_of(ts).astype(np.int64)
    counts = pd.Series(day).value_counts().to_dict()
    folds = fold_assignment({int(d): int(c) for d, c in counts.items()})
    print(f"[crossfit] {len(cols)} features, {len(y):,} train edges ({int(y.sum()):,} laundering); "
          f"folds {[list(map(int, f)) for f in folds]}")

    parts, info = [], []
    for k, held in enumerate(folds):
        t = time.time()
        te = np.isin(day, held)
        model = xgb.train({**FIXED, **params, "seed": a.seed},
                          xgb.DMatrix(X[~te], label=y[~te], feature_names=cols),
                          num_boost_round=num_round, verbose_eval=False)
        prob = model.predict(xgb.DMatrix(X[te], feature_names=cols)).astype(np.float64)
        part = pd.DataFrame({"edge_id": edge_id[te], "timestamp": ts[te], "day": day[te],
                             "fold": np.int64(k), "score_raw": prob})
        part["score_quantile"] = part["score_raw"].rank(method="average").to_numpy() / len(part)
        part["dead_region"] = False       # no head constants in a boosted tree; see the docstring
        part["score_calibrated"] = np.nan
        ap_k = float(average_precision_score(y[te], prob))
        f1_k = f1_score(y[te], (prob >= 0.5).astype(int), pos_label=1, zero_division=0)
        info.append({"fold": k, "held_out_days": [int(d) for d in held],
                     "train_days": sorted(int(d) for d in set(day.tolist()) - set(map(int, held))),
                     "n_held_out": int(te.sum()), "n_train": int((~te).sum()),
                     "held_out": {"average_precision": ap_k, "f1_at_0.5": f1_k},
                     "seconds": round(time.time() - t, 1)})
        print(f"    fold {k} held-out days {[int(d) for d in held]}: AP {ap_k:.4f} | F1@0.5 {f1_k:.4f} "
              f"| {int(te.sum()):,} edges | {info[-1]['seconds']:.0f}s", flush=True)
        parts.append(part)
        if a.dry_run:
            print(f"[crossfit] DRY RUN: one fold at {num_round} rounds took {info[-1]['seconds']:.0f}s -> about "
                  f"{info[-1]['seconds'] * (refit_params(a.params_from)[1] / num_round) * len(folds) / 60:.0f} min "
                  f"for all {len(folds)} folds at full length. Nothing written.")
            return info

    d = pd.concat(parts, ignore_index=True).sort_values("edge_id").reset_index(drop=True)
    assert d["edge_id"].is_unique and len(d) == len(edge_id), "one scored row per train edge"
    train_days = {i["fold"]: set(i["train_days"]) for i in info}
    viol = sum(int(dd in train_days[f]) for dd, f in zip(d["day"].tolist(), d["fold"].tolist()))
    assert viol == 0, f"{viol} edges scored by a model trained on their day"
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out = a.out_dir / "cross_scores_train.parquet"
    d.to_parquet(out, index=False)
    summary = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": git_commit(),
               "step": "10.2 (R6 detector swap)", "detector": "gfpxgb", "xgboost_seed": a.seed,
               "params": {**FIXED, **params}, "num_round": num_round, "features": cols,
               "n_rows": int(len(d)), "n_folds": len(folds),
               "assertion": {"rule": "day(edge) not in train_days[fold(edge)] for every row; one row per train edge",
                             "violations": viol, "passed": True},
               "folds": info,
               "fold_source": "ringshield/expand/cross_score.py::fold_assignment (the same day partition "
                              "the gine fold models used)",
               "columns_not_available": {
                   "dead_region": "always False -- the dead region is a property of the GNN head's constant "
                                  "outputs; the policy variant for this detector drops that feature group",
                   "score_calibrated": "NaN -- fold models are on their own scale and the policy does not use it "
                                       "(Step 6 amendment a)"},
               "val_test_scores": str(REFIT_DIR), "out": str(out), "seconds": round(time.time() - t0, 1)}
    (a.out_dir / "cross_scores.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    env = [f"python: {sys.version}", f"platform: {platform.platform()}", f"xgboost: {xgb.__version__}"]
    try:
        env.append("\n# pip freeze\n" + subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    except Exception:  # pragma: no cover
        pass
    (a.out_dir / "environment.txt").write_text("\n".join(env), encoding="utf-8")
    print(f"[crossfit] {len(d):,} rows -> {out} (assertion passed, {viol} violations) "
          f"in {summary['seconds']:.0f}s")


if __name__ == "__main__":
    main()
