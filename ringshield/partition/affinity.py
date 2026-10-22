"""Pair affinity (LightGBM) and the clustering of included edges into attempts (Step 7.2).

    python ringshield/partition/affinity.py --pairs experiments/R4_partition/pairs_train.parquet \\
        --out experiments/R4_partition/affinity

Training as in Step 6 (ringshield/expand/policy.py): binary LightGBM, max_depth 6, lr 0.05,
min_child_samples 20, feature_fraction 0.8, early stopping on the held-out fold's AUC-PR,
grouped 5-fold CV by component, scale_pos_weight chosen by the same CV from {neg/pos, sqrt, 1}.

Clustering over the included edges of one component, weights w = logit(p) on the shared-account
pairs (non-adjacent pairs carry no weight):

    cluster_pivot    greedy pivot (Ailon-Charikar-Newman): pick an unclustered pivot (order fixed by
                     the seed), take every unclustered node joined to it by a path of positive pairs,
                     remove, repeat. On a sparse pair graph the ACN neighbourhood has to be taken
                     transitively -- a 5-edge stack has no pair (e1, e3), so the direct neighbourhood
                     would split every chain -- and with that the pivot order only fixes numbering.
    cluster_average  average-linkage agglomerative with distance 1 - p, averaged over the pairs that
                     join two clusters (clusters with no joining pair never merge); merge while the
                     smallest distance is below `cut` (chosen on val).

Both are deterministic for the same inputs. `reattach_small` is the post-step both use in the
'full' aggregator: a cluster whose edges span fewer than `min_members` accounts cannot become a
ring (min_size), so it is merged into the linked cluster with the highest mean affinity, smallest
first, until every cluster is large enough or has no link left. Without it a 2-edge component
cut in the middle turns into two 2-account fragments that both vanish (the first R4 pass lost 23
matches that way against 8 gained).
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

from ringshield.partition.pairs import FEATURE_GROUPS, PAIR_FEATURES  # noqa: E402
from ringshield.holdout import Holdout  # noqa: E402
from ringshield.holdout import add_argument as _add_holdout_argument  # noqa: E402

LGB_PARAMS = {"objective": "binary", "metric": "average_precision", "learning_rate": 0.05, "max_depth": 6,
              "num_leaves": 31, "min_child_samples": 20, "feature_fraction": 0.8, "bagging_fraction": 1.0,
              "lambda_l2": 1.0, "verbosity": -1, "num_threads": 0, "deterministic": True, "force_row_wise": True}
N_FOLDS, EARLY_STOP, MAX_ROUNDS = 5, 50, 2000


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


class Affinity:
    def __init__(self, features: list[str], booster=None, meta: dict | None = None):
        self.features, self.booster, self.meta = list(features), booster, meta or {}

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if len(X) == 0:
            return np.zeros(0)
        return self.booster.predict(X[self.features].to_numpy(np.float32), num_threads=0)

    def save(self, out_dir: Path) -> Path:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        doc = {"kind": "affinity", "features": self.features, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "git_commit": _git_commit(), **self.meta}
        (out_dir / "affinity.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        self.booster.save_model(str(out_dir / "affinity.txt"))
        return out_dir

    @classmethod
    def load(cls, d: Path) -> "Affinity":
        import lightgbm as lgb
        d = Path(d)
        doc = json.loads((d / "affinity.json").read_text(encoding="utf-8"))
        return cls(doc["features"], lgb.Booster(model_file=str(d / "affinity.txt")),
                   {k: v for k, v in doc.items() if k not in ("kind", "features")})


def train_affinity(P: pd.DataFrame, *, drop_groups=(), seed: int = 1, n_folds: int = N_FOLDS, verbose: bool = True) -> Affinity:
    import lightgbm as lgb
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import GroupKFold
    t0 = time.time()
    dropped = {c for g in drop_groups for c in FEATURE_GROUPS[g]}
    feats = [c for c in PAIR_FEATURES if c not in dropped]
    P = P.reset_index(drop=True)
    X, y, groups = P[feats].to_numpy(np.float32), P["label"].to_numpy(np.int64), P["component"].to_numpy()
    n_pos, n_neg = int(y.sum()), int((y == 0).sum())
    assert n_pos > 0 and n_neg > 0, (n_pos, n_neg)
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    perm = {g: i for i, g in enumerate(rng.permutation(uniq))}
    gk = np.array([perm[g] for g in groups])
    n_folds = min(n_folds, len(uniq))
    splits = list(GroupKFold(n_splits=n_folds).split(X, y, gk))
    sweep = {}
    for name, spw in (("neg_over_pos", n_neg / n_pos), ("sqrt_neg_over_pos", float(np.sqrt(n_neg / n_pos))), ("one", 1.0)):
        params = dict(LGB_PARAMS, scale_pos_weight=spw, seed=seed)
        folds, iters, oof = [], [], np.full(len(y), np.nan)
        for k, (tr_i, va_i) in enumerate(splits):
            dtr = lgb.Dataset(X[tr_i], y[tr_i], feature_name=feats, free_raw_data=False)
            dva = lgb.Dataset(X[va_i], y[va_i], reference=dtr, feature_name=feats, free_raw_data=False)
            b = lgb.train(params, dtr, num_boost_round=MAX_ROUNDS, valid_sets=[dva], callbacks=[lgb.early_stopping(EARLY_STOP, verbose=False)])
            p = b.predict(X[va_i], num_iteration=b.best_iteration)
            oof[va_i] = p
            ap = float(average_precision_score(y[va_i], p)) if 0 < y[va_i].sum() < len(va_i) else float("nan")
            folds.append({"fold": k, "n_rows": int(len(va_i)), "n_pos": int(y[va_i].sum()), "n_components": int(len(np.unique(gk[va_i]))),
                          "auc_pr": ap, "best_iteration": int(b.best_iteration)})
            iters.append(b.best_iteration)
        aps = np.array([f["auc_pr"] for f in folds if not np.isnan(f["auc_pr"])])
        sweep[name] = {"scale_pos_weight": spw, "cv_folds": folds, "cv_auc_pr_mean": float(aps.mean()),
                       "cv_auc_pr_std": float(aps.std(ddof=1)) if len(aps) > 1 else None,
                       "oof_auc_pr": float(average_precision_score(y, oof)), "best_iters": [int(i) for i in iters]}
        if verbose:
            print(f"  scale_pos_weight {name} ({spw:.2f}): CV AUC-PR {aps.mean():.4f} +/- {aps.std(ddof=1) if len(aps) > 1 else 0:.4f} "
                  f"folds {np.round(aps, 3).tolist()} iters {iters}")
    chosen = max(sweep, key=lambda k: sweep[k]["cv_auc_pr_mean"])
    params = dict(LGB_PARAMS, scale_pos_weight=sweep[chosen]["scale_pos_weight"], seed=seed)
    n_final = max(int(round(float(np.mean(sweep[chosen]["best_iters"])))), 1)
    booster = lgb.train(params, lgb.Dataset(X, y, feature_name=feats), num_boost_round=n_final)
    gain, split = booster.feature_importance("gain"), booster.feature_importance("split")
    tot = float(gain.sum()) or 1.0
    imp = sorted([{"feature": f, "gain": float(g), "gain_frac": float(g) / tot, "split": int(s)} for f, g, s in zip(feats, gain, split)],
                 key=lambda d: -d["gain"])
    group_gain = {g: float(sum(d["gain_frac"] for d in imp if d["feature"] in set(cols))) for g, cols in FEATURE_GROUPS.items() if g not in drop_groups}
    aps = np.array([f["auc_pr"] for f in sweep[chosen]["cv_folds"] if not np.isnan(f["auc_pr"])])
    report = {"n_rows": int(len(y)), "n_pos": n_pos, "n_neg": n_neg, "pos_rate": n_pos / len(y), "n_components": int(len(uniq)),
              "drop_groups": list(drop_groups), "n_features": len(feats), "params": params, "cv_folds": sweep[chosen]["cv_folds"],
              "cv_auc_pr_mean": float(aps.mean()), "cv_auc_pr_std": float(aps.std(ddof=1)) if len(aps) > 1 else None,
              "cv_auc_pr_min": float(aps.min()), "cv_auc_pr_max": float(aps.max()), "oof_auc_pr": sweep[chosen]["oof_auc_pr"],
              "scale_pos_weight_chosen": chosen, "scale_pos_weight_sweep": {k: {kk: vv for kk, vv in v.items() if kk != "cv_folds"} for k, v in sweep.items()},
              "final_num_boost_round": n_final, "importance": imp, "group_gain_frac": group_gain, "train_seed": seed,
              "seconds": round(time.time() - t0, 1)}
    if verbose:
        print(f"[affinity] CV AUC-PR {report['cv_auc_pr_mean']:.4f} +/- {report['cv_auc_pr_std'] or 0:.4f} (min {report['cv_auc_pr_min']:.4f}, "
              f"max {report['cv_auc_pr_max']:.4f}; pooled OOF {report['oof_auc_pr']:.4f}; base rate {report['pos_rate']:.3f}); "
              f"final {n_final} rounds; top: " + ", ".join(f"{d['feature']} {d['gain_frac']:.2f}" for d in imp[:8]))
    return Affinity(feats, booster, {"cv": report})


# ------------------------------------------------------------------------------ clustering
def cluster_pivot(n: int, ia: np.ndarray, ib: np.ndarray, p: np.ndarray, *, seed: int = 0, threshold: float = 0.5) -> np.ndarray:
    """Cluster labels (0..k-1) for n nodes; pairs (ia, ib) with affinity p; w = logit(p) > 0 <=> p > threshold."""
    labels = np.full(n, -1, dtype=np.int64)
    if n == 0:
        return labels
    pos = np.asarray(p) > threshold
    adj = [[] for _ in range(n)]
    for a, b in zip(np.asarray(ia)[pos].tolist(), np.asarray(ib)[pos].tolist()):
        adj[a].append(b)
        adj[b].append(a)
    order = np.random.default_rng(seed).permutation(n)
    k = 0
    for pivot in order.tolist():
        if labels[pivot] >= 0:
            continue
        stack, labels[pivot] = [pivot], k
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if labels[v] < 0:
                    labels[v] = k
                    stack.append(v)
        k += 1
    return labels


def cluster_average(n: int, ia: np.ndarray, ib: np.ndarray, p: np.ndarray, *, cut: float = 0.5) -> np.ndarray:
    """Average-linkage agglomerative clustering on sparse pair distances 1 - p; merge while the
    smallest cluster distance is < cut. Clusters without a joining pair never merge."""
    labels = np.arange(n, dtype=np.int64)
    if n == 0 or len(ia) == 0:
        return labels
    d = 1.0 - np.asarray(p, dtype=float)
    # (sum of distances, count) between clusters, keyed by ordered cluster pair
    link: dict[tuple[int, int], list[float]] = {}
    for a, b, dist in zip(np.asarray(ia).tolist(), np.asarray(ib).tolist(), d.tolist()):
        if a == b:
            continue
        key = (min(a, b), max(a, b))
        s = link.setdefault(key, [0.0, 0])
        s[0] += dist
        s[1] += 1
    members = {i: [i] for i in range(n)}
    while link:
        (ca, cb), best = min(link.items(), key=lambda kv: (kv[1][0] / kv[1][1], kv[0]))
        if best[0] / best[1] >= cut:
            break
        # merge cb into ca
        members[ca].extend(members.pop(cb))
        new_link: dict[tuple[int, int], list[float]] = {}
        for (x, y), s in link.items():
            if (x, y) == (ca, cb):
                continue
            x2 = ca if x == cb else x
            y2 = ca if y == cb else y
            key = (min(x2, y2), max(x2, y2))
            t = new_link.setdefault(key, [0.0, 0])
            t[0] += s[0]
            t[1] += s[1]
        link = new_link
    out = np.empty(n, dtype=np.int64)
    for k, (root, mem) in enumerate(sorted(members.items())):
        out[mem] = k
    return out


def reattach_small(labels: np.ndarray, ia: np.ndarray, ib: np.ndarray, p: np.ndarray, endpoints: np.ndarray,
                   min_members: int) -> np.ndarray:
    """Merge clusters spanning < min_members accounts into their best-linked neighbour (see module doc).
    `endpoints` is (n, 2) account ids per node."""
    labels = np.asarray(labels).copy()
    if len(ia) == 0:
        return labels
    ia, ib, p = np.asarray(ia), np.asarray(ib), np.asarray(p, dtype=float)
    while True:
        members = {}
        for i, l in enumerate(labels.tolist()):
            members.setdefault(l, set()).update(endpoints[i].tolist())
        small = sorted((l for l, m in members.items() if len(m) < min_members), key=lambda l: (len(members[l]), l))
        merged = False
        for l in small:
            la, lb = labels[ia], labels[ib]
            sel = (la == l) ^ (lb == l)
            if not sel.any():
                continue
            other = np.where(la[sel] == l, lb[sel], la[sel])
            df = pd.DataFrame({"o": other, "p": p[sel]}).groupby("o")["p"].mean()
            target = int(df.sort_values(ascending=False).index[0])
            labels[labels == l] = target
            merged = True
            break
        if not merged:
            break
    _, out = np.unique(labels, return_inverse=True)
    return out.astype(np.int64)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pairs", type=Path, default=REPO_ROOT / "experiments" / "R4_partition" / "pairs_train.parquet")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--drop-feature-group", choices=sorted(FEATURE_GROUPS), nargs="*", default=[])
    ap.add_argument("--seed", type=int, default=1)
    _add_holdout_argument(ap)
    args = ap.parse_args(argv)
    P = pd.read_parquet(args.pairs)
    _ho = Holdout.load(getattr(args, "hold_out_pattern", None))
    if _ho.is_active:
        _held = _ho.edge_ids(("train",))
        _bad = int(P["edge_a"].isin(_held).sum() + P["edge_b"].isin(_held).sum())
        assert _bad == 0, f"affinity pairs: {_bad} endpoints are held-out {_ho.pattern} edges"
    print(f"[affinity] {len(P):,} pairs, {int(P['label'].sum()):,} positive, {P['component'].nunique()} components; drop {args.drop_feature_group or 'nothing'}")
    aff = train_affinity(P, drop_groups=tuple(args.drop_feature_group), seed=args.seed)
    aff.meta.update({"pairs": str(args.pairs)})
    aff.save(args.out)
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
