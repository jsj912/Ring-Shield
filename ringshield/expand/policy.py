"""The expansion policy (Step 6.4): a LightGBM classifier over candidate feature rows, or a rule.

    python ringshield/expand/policy.py --training-set experiments/R3_expansion/training_set.parquet \\
        --out experiments/R3_expansion/policy_proposed [--drop-feature-group detector|account_state|embedding] \\
        [--hop1-only]

Training: grouped 5-fold cross-validation by ring_id (sklearn GroupKFold), binary objective,
max_depth 6, learning rate 0.05, min_child_samples 20, feature_fraction 0.8, early stopping
(50 rounds) on the held-out fold's average precision. `scale_pos_weight` is chosen by the same
grouped CV from {negatives / positives, sqrt of that, 1}: at 1 : 1,000 the full ratio wrecks the
fit (CV AUC-PR 0.11 vs 0.83 at weight 1 on the 6.3 set -- the hop-2 negatives get swamped),
so the sweep is part of training and every candidate's CV result is recorded. Reported: AUC-PR
per fold and mean +/- std for the chosen weight, the best iteration per fold, gain and split
importances of the final model. The final model is fit on every row with the mean best
iteration. With 244 positives the fold spread is the number to read, not the mean alone.

Rules (the baselines of Step 6.4), same interface:
    rule     B1  -- every hop-1 candidate (shares an endpoint with a seed within delta_t)
    rule_q   B1b -- every hop-1 candidate whose within-split score quantile exceeds Q_MIN (0.99)

A policy directory holds policy.json (kind, feature columns, dropped groups, hop1_only, CV
report) and, for a model, policy.txt (the LightGBM booster).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from ringshield.expand.features import FEATURE_COLUMNS, FEATURE_GROUPS  # noqa: E402

KINDS = ("model", "rule", "rule_q")
Q_MIN = 0.99
LGB_PARAMS = {"objective": "binary", "metric": "average_precision", "learning_rate": 0.05, "max_depth": 6,
              "num_leaves": 31, "min_child_samples": 20, "feature_fraction": 0.8, "bagging_fraction": 1.0,
              "lambda_l2": 1.0, "verbosity": -1, "num_threads": 0, "deterministic": True, "force_row_wise": True}
N_FOLDS, EARLY_STOP, MAX_ROUNDS = 5, 50, 2000


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def feature_columns(drop_groups=()) -> list[str]:
    bad = set(drop_groups) - set(FEATURE_GROUPS)
    assert not bad, f"unknown feature groups {sorted(bad)}; choose from {sorted(FEATURE_GROUPS)}"
    dropped = {c for g in drop_groups for c in FEATURE_GROUPS[g]}
    return [c for c in FEATURE_COLUMNS if c not in dropped]


class Policy:
    """p(candidate is a member) for feature rows; `kind` model | rule | rule_q."""

    def __init__(self, kind: str, features: list[str], booster=None, hop1_only: bool = False,
                 drop_groups: tuple[str, ...] = (), q_min: float = Q_MIN, meta: dict | None = None):
        assert kind in KINDS, kind
        self.kind, self.features, self.booster = kind, list(features), booster
        self.hop1_only, self.drop_groups, self.q_min = bool(hop1_only), tuple(drop_groups), float(q_min)
        self.meta = meta or {}

    @classmethod
    def rule(cls, kind: str = "rule") -> "Policy":
        return cls(kind, ["hop", "score_quantile"], hop1_only=True)

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if len(X) == 0:
            return np.zeros(0)
        hop = X["hop"].to_numpy()
        if self.kind == "rule":
            return (hop == 1).astype(float)
        if self.kind == "rule_q":
            return ((hop == 1) & (X["score_quantile"].to_numpy() > self.q_min)).astype(float)
        p = self.booster.predict(X[self.features].to_numpy(np.float32), num_threads=0)
        if self.hop1_only:
            p = np.where(hop == 1, p, 0.0)
        return p

    def save(self, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = {"kind": self.kind, "features": self.features, "hop1_only": self.hop1_only, "drop_groups": list(self.drop_groups),
               "q_min": self.q_min, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "git_commit": _git_commit(), **self.meta}
        (out_dir / "policy.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        if self.booster is not None:
            self.booster.save_model(str(out_dir / "policy.txt"))
        return out_dir

    @classmethod
    def load(cls, policy_dir: Path) -> "Policy":
        policy_dir = Path(policy_dir)
        doc = json.loads((policy_dir / "policy.json").read_text(encoding="utf-8"))
        booster = None
        if doc["kind"] == "model":
            import lightgbm as lgb
            booster = lgb.Booster(model_file=str(policy_dir / "policy.txt"))
        meta = {k: v for k, v in doc.items() if k not in ("kind", "features", "hop1_only", "drop_groups", "q_min")}
        return cls(doc["kind"], doc["features"], booster, doc.get("hop1_only", False), tuple(doc.get("drop_groups", [])),
                   doc.get("q_min", Q_MIN), meta)


def train_policy(ts: pd.DataFrame, *, drop_groups=(), hop1_only: bool = False, seed: int = 1,
                 n_folds: int = N_FOLDS, verbose: bool = True) -> Policy:
    import lightgbm as lgb
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import GroupKFold
    t0 = time.time()
    if hop1_only:
        ts = ts[ts["hop"] == 1]
    ts = ts.reset_index(drop=True)
    feats = feature_columns(drop_groups)
    X = ts[feats].to_numpy(np.float32)
    y = ts["label"].to_numpy(np.int64)
    groups = ts["ring_id"].to_numpy()
    n_pos, n_neg = int(y.sum()), int((y == 0).sum())
    assert n_pos > 0, "no positives"
    # GroupKFold is deterministic given the group order; shuffle groups once with the seed
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    perm = {g: i for i, g in enumerate(rng.permutation(uniq))}
    gk = np.array([perm[g] for g in groups])
    splits = list(GroupKFold(n_splits=n_folds).split(X, y, gk))
    sweep = {}
    for name, spw in (("neg_over_pos", n_neg / n_pos), ("sqrt_neg_over_pos", float(np.sqrt(n_neg / n_pos))), ("one", 1.0)):
        params = dict(LGB_PARAMS, scale_pos_weight=spw, seed=seed)
        folds, best_iters, oof = [], [], np.full(len(y), np.nan)
        for k, (tr_i, va_i) in enumerate(splits):
            dtr = lgb.Dataset(X[tr_i], y[tr_i], feature_name=feats, free_raw_data=False)
            dva = lgb.Dataset(X[va_i], y[va_i], reference=dtr, feature_name=feats, free_raw_data=False)
            b = lgb.train(params, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[dva],
                          callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
            p = b.predict(X[va_i], num_iteration=b.best_iteration)
            oof[va_i] = p
            ap = float(average_precision_score(y[va_i], p)) if y[va_i].sum() else float("nan")
            folds.append({"fold": k, "n_rows": int(len(va_i)), "n_pos": int(y[va_i].sum()), "n_rings": int(len(np.unique(gk[va_i]))),
                          "auc_pr": ap, "best_iteration": int(b.best_iteration)})
            best_iters.append(b.best_iteration)
        aps = np.array([f["auc_pr"] for f in folds if not np.isnan(f["auc_pr"])])
        sweep[name] = {"scale_pos_weight": spw, "cv_folds": folds, "cv_auc_pr_mean": float(aps.mean()),
                       "cv_auc_pr_std": float(aps.std(ddof=1)) if len(aps) > 1 else None,
                       "oof_auc_pr": float(average_precision_score(y, oof)), "best_iters": [int(i) for i in best_iters]}
        if verbose:
            print(f"  scale_pos_weight {name} ({spw:.1f}): CV AUC-PR {aps.mean():.4f} +/- {aps.std(ddof=1) if len(aps) > 1 else 0:.4f} "
                  f"folds {np.round(aps, 3).tolist()} iters {best_iters}")
    chosen = max(sweep, key=lambda k: sweep[k]["cv_auc_pr_mean"])
    params = dict(LGB_PARAMS, scale_pos_weight=sweep[chosen]["scale_pos_weight"], seed=seed)
    folds, best_iters = sweep[chosen]["cv_folds"], sweep[chosen]["best_iters"]
    aps = np.array([f["auc_pr"] for f in folds if not np.isnan(f["auc_pr"])])
    n_final = max(int(round(float(np.mean(best_iters)))), 1)
    booster = lgb.train(params, lgb.Dataset(X, y, feature_name=feats), num_boost_round=n_final)
    gain = booster.feature_importance("gain")
    split = booster.feature_importance("split")
    imp = sorted([{"feature": f, "gain": float(g), "split": int(s)} for f, g, s in zip(feats, gain, split)],
                 key=lambda d: -d["gain"])
    tot = sum(d["gain"] for d in imp) or 1.0
    for d in imp:
        d["gain_frac"] = d["gain"] / tot
    group_gain = {g: float(sum(d["gain_frac"] for d in imp if d["feature"] in set(cols))) for g, cols in FEATURE_GROUPS.items()
                  if g not in drop_groups}
    report = {"n_rows": int(len(y)), "n_pos": n_pos, "n_neg": n_neg, "n_rings": int(len(uniq)), "hop1_only": hop1_only,
              "drop_groups": list(drop_groups), "n_features": len(feats), "params": params, "cv_folds": folds,
              "cv_auc_pr_mean": float(aps.mean()) if len(aps) else None, "cv_auc_pr_std": float(aps.std(ddof=1)) if len(aps) > 1 else None,
              "cv_auc_pr_min": float(aps.min()) if len(aps) else None, "cv_auc_pr_max": float(aps.max()) if len(aps) else None,
              "oof_auc_pr": sweep[chosen]["oof_auc_pr"], "final_num_boost_round": n_final,
              "scale_pos_weight_chosen": chosen, "scale_pos_weight_sweep": {k: {kk: vv for kk, vv in v.items() if kk != "cv_folds"}
                                                                            for k, v in sweep.items()},
              "importance": imp, "group_gain_frac": group_gain, "train_seed": seed, "seconds": round(time.time() - t0, 1)}
    if verbose:
        print(f"[policy] CV AUC-PR {report['cv_auc_pr_mean']:.4f} +/- {report['cv_auc_pr_std'] or 0:.4f} "
              f"(min {report['cv_auc_pr_min']:.4f}, max {report['cv_auc_pr_max']:.4f}; out-of-fold pooled {report['oof_auc_pr']:.4f}); "
              f"final {n_final} rounds; top features: " + ", ".join(f"{d['feature']} {d['gain_frac']:.2f}" for d in imp[:8]))
    return Policy("model", feats, booster, hop1_only=hop1_only, drop_groups=tuple(drop_groups), meta={"cv": report})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--training-set", type=Path, default=REPO_ROOT / "experiments" / "R3_expansion" / "training_set.parquet")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--drop-feature-group", choices=sorted(FEATURE_GROUPS), nargs="*", default=[])
    ap.add_argument("--hop1-only", action="store_true")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="5 %% of the rows (all positives kept); pipeline check")
    args = ap.parse_args(argv)
    ts = pd.read_parquet(args.training_set)
    if args.dry_run:
        ts = pd.concat([ts[ts["label"] == 1], ts[ts["label"] == 0].sample(frac=0.05, random_state=args.seed)])
    print(f"[policy] {len(ts):,} rows, {int(ts['label'].sum())} positives, {ts['ring_id'].nunique()} rings; "
          f"drop {args.drop_feature_group or 'nothing'}; hop1_only={args.hop1_only}")
    pol = train_policy(ts, drop_groups=tuple(args.drop_feature_group), hop1_only=args.hop1_only, seed=args.seed)
    pol.meta.update({"training_set": str(args.training_set), "dry_run": args.dry_run})
    pol.save(args.out)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
