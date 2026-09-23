"""The 8-way topology head (Step 8.3).

    python ringshield/typing/head.py --out experiments/R5_typing/head

LightGBM multiclass over `ringshield.typing.features.RING_FEATURES`, trained on the
**train-visible ground-truth rings with >= 3 visible members** (amendment d) plus, when
`--with-recovered` is given, the train-period rings the pipeline recovers, each matched to the
truth ring it overlaps most and carrying that ring's label (the same shape seen through the
aggregator's eyes). Grouped 5-fold CV by ring id; accuracy, macro-F1 and the 8x8 confusion matrix
of the out-of-fold predictions are reported next to the rule scorer's on the same rows.

`TypingHead.predict_probs(features)` returns the 8 probabilities in `TOPOLOGY_TYPES` order;
`topology_type` is their argmax. `ringshield.aggregators.full` attaches it to every ring it
builds, and `ringshield/typing/head.py --out` writes head.txt / head.json for the model dir.
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

from contract.schema import TOPOLOGY_TYPES  # noqa: E402
from ringshield.typing.features import RING_FEATURES  # noqa: E402
from ringshield.typing.rules import rule_type  # noqa: E402
from ringshield.typing.truth_rings import truth_ring_rows  # noqa: E402

LGB_PARAMS = {"objective": "multiclass", "num_class": len(TOPOLOGY_TYPES), "metric": "multi_logloss",
              "learning_rate": 0.05, "max_depth": 6, "num_leaves": 31, "min_child_samples": 5,
              "feature_fraction": 0.8, "lambda_l2": 1.0, "verbosity": -1, "num_threads": 0,
              "deterministic": True, "force_row_wise": True}
N_FOLDS, EARLY_STOP, MAX_ROUNDS = 5, 50, 1000


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


class TypingHead:
    def __init__(self, features: list[str], booster=None, meta: dict | None = None):
        self.features, self.booster, self.meta = list(features), booster, meta or {}

    def predict_probs(self, rows) -> np.ndarray:
        """(n, 8) probabilities in TOPOLOGY_TYPES order; `rows` is a dict, a list of dicts or a frame."""
        if isinstance(rows, dict):
            rows = [rows]
        X = (rows[self.features] if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))[self.features]).to_numpy(np.float32)
        p = self.booster.predict(X, num_threads=0)
        return np.atleast_2d(p)

    def predict_type(self, rows) -> list[str]:
        return [TOPOLOGY_TYPES[i] for i in self.predict_probs(rows).argmax(axis=1)]

    def save(self, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "head.json").write_text(json.dumps({"kind": "typing_head", "features": self.features, "classes": TOPOLOGY_TYPES,
                                                       "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                                       "git_commit": _git_commit(), **self.meta}, indent=2), encoding="utf-8")
        self.booster.save_model(str(out_dir / "head.txt"))
        return out_dir

    @classmethod
    def load(cls, d: Path) -> "TypingHead":
        import lightgbm as lgb
        d = Path(d)
        doc = json.loads((d / "head.json").read_text(encoding="utf-8"))
        assert doc["classes"] == TOPOLOGY_TYPES, doc["classes"]
        return cls(doc["features"], lgb.Booster(model_file=str(d / "head.txt")),
                   {k: v for k, v in doc.items() if k not in ("kind", "features", "classes")})


def confusion(y_true: list[str], y_pred: list[str]) -> pd.DataFrame:
    m = pd.DataFrame(0, index=TOPOLOGY_TYPES, columns=TOPOLOGY_TYPES, dtype=int)
    for t, p in zip(y_true, y_pred):
        m.loc[t, p] += 1
    return m


def train_head(rows: pd.DataFrame, *, seed: int = 1, n_folds: int = N_FOLDS, verbose: bool = True) -> TypingHead:
    import lightgbm as lgb
    from sklearn.metrics import f1_score
    from sklearn.model_selection import StratifiedGroupKFold
    t0 = time.time()
    rows = rows.reset_index(drop=True)
    X = rows[RING_FEATURES].to_numpy(np.float32)
    y = np.array([TOPOLOGY_TYPES.index(t) for t in rows["pattern_type"]], dtype=np.int64)
    groups = rows["ring_id"].to_numpy()
    params = dict(LGB_PARAMS, seed=seed)
    oof = np.full((len(y), len(TOPOLOGY_TYPES)), np.nan)
    iters, folds = [], []
    skf = StratifiedGroupKFold(n_splits=n_folds, shuffle=True, random_state=seed)
    for k, (tr_i, va_i) in enumerate(skf.split(X, y, groups)):
        dtr = lgb.Dataset(X[tr_i], y[tr_i], feature_name=RING_FEATURES)
        dva = lgb.Dataset(X[va_i], y[va_i], reference=dtr, feature_name=RING_FEATURES)
        b = lgb.train(params, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[dva], callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
        oof[va_i] = b.predict(X[va_i], num_iteration=b.best_iteration)
        iters.append(b.best_iteration)
        acc = float((oof[va_i].argmax(1) == y[va_i]).mean())
        folds.append({"fold": k, "n_rows": int(len(va_i)), "accuracy": acc, "best_iteration": int(b.best_iteration)})
        if verbose:
            print(f"  cv fold {k}: {len(va_i)} rings, accuracy {acc:.3f}, best iter {b.best_iteration}")
    pred = [TOPOLOGY_TYPES[i] for i in oof.argmax(1)]
    true = list(rows["pattern_type"])
    rule = [rule_type(r) for r in rows[RING_FEATURES].to_dict("records")]
    n_final = max(int(round(float(np.mean(iters)))), 1)
    booster = lgb.train(params, lgb.Dataset(X, y, feature_name=RING_FEATURES), num_boost_round=n_final)
    gain = booster.feature_importance("gain")
    tot = float(gain.sum()) or 1.0
    imp = sorted([{"feature": f, "gain_frac": float(g) / tot} for f, g in zip(RING_FEATURES, gain)], key=lambda d: -d["gain_frac"])
    report = {"n_rings": int(len(rows)), "class_counts": rows["pattern_type"].value_counts().to_dict(),
              "cv_folds": folds, "cv_accuracy": float(np.mean([f["accuracy"] for f in folds])),
              "cv_accuracy_std": float(np.std([f["accuracy"] for f in folds], ddof=1)) if len(folds) > 1 else None,
              "oof_accuracy": float(np.mean([p == t for p, t in zip(pred, true)])),
              "oof_macro_f1": float(f1_score(true, pred, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
              "rule_accuracy": float(np.mean([r == t for r, t in zip(rule, true)])),
              "rule_macro_f1": float(f1_score(true, rule, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
              "oof_confusion": json.loads(confusion(true, pred).to_json(orient="split")),
              "rule_confusion": json.loads(confusion(true, rule).to_json(orient="split")),
              "per_class_oof": {t: {"n": int(sum(1 for x in true if x == t)),
                                    "recall": float(np.mean([p == t for p, x in zip(pred, true) if x == t])) if any(x == t for x in true) else None}
                                for t in TOPOLOGY_TYPES},
              "final_num_boost_round": n_final, "importance": imp, "params": params, "train_seed": seed,
              "seconds": round(time.time() - t0, 1)}
    if verbose:
        print(f"[head] out-of-fold accuracy {report['oof_accuracy']:.3f} (macro-F1 {report['oof_macro_f1']:.3f}) vs rule "
              f"{report['rule_accuracy']:.3f} ({report['rule_macro_f1']:.3f}) on {len(rows)} train-visible rings; "
              f"final {n_final} rounds; top: " + ", ".join(f"{d['feature']} {d['gain_frac']:.2f}" for d in imp[:6]))
    return TypingHead(RING_FEATURES, booster, {"cv": report})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "experiments" / "R5_typing" / "head")
    ap.add_argument("--min-members", type=int, default=3)
    ap.add_argument("--window-days", type=int, default=None,
                    help="slice the train split into windows this wide before building the rings (the "
                         "fragment length the head will face at inference; chosen on val, see docs/TYPING.md)")
    ap.add_argument("--recovered", type=Path, default=None,
                    help="optional parquet of recovered train rings (ring_id, pattern_type + RING_FEATURES) to add")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)
    rows = truth_ring_rows("train", min_members=args.min_members, window_days=args.window_days)
    rows["source"] = "truth"
    if args.recovered and Path(args.recovered).exists():
        rec = pd.read_parquet(args.recovered)
        rec["source"] = "recovered"
        rows = pd.concat([rows, rec], ignore_index=True)
    print(f"[head] {len(rows)} training rings ({rows['source'].value_counts().to_dict()}), "
          f"{rows['pattern_type'].nunique()} classes: {rows['pattern_type'].value_counts().to_dict()}")
    head = train_head(rows, seed=args.seed)
    head.meta.update({"min_members": args.min_members, "window_days": args.window_days,
                      "recovered": str(args.recovered) if args.recovered else None,
                      "sources": rows["source"].value_counts().to_dict()})
    head.save(args.out)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
