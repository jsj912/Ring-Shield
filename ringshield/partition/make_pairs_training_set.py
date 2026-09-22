"""Labelled shared-account pairs from the train split's expanded components (Step 7.1 training data).

    python ringshield/partition/make_pairs_training_set.py --out experiments/R4_partition [--p-min 0.7]

Train-split "expanded components" are built the way the pipeline builds them at test time, minus
the greedy loop: seeds = the within-fold 0.1 % cut of the cross-scores (Step 6.3), expanded
edges = the Step 6.3 candidate rows whose OUT-OF-FOLD policy probability (grouped 5-fold CV by
ring, the proposed policy's parameters) is >= p_min (the val-chosen p_min of R3, 0.7), and a
component is a connected component of the account graph of seeds + expanded edges. Every two
included edges of a component that share an account form a pair (ringshield/partition/pairs.py);
label = both edges carry the same ring_id > 0 (train-visible rings, amendment c); pairs are
grouped by component for the CV.

Embeddings for a pair come from the fold model of the earlier edge, applied to both edges (one
model per pair; the earlier edge was never seen by it): the fold models' embeddings of every
included edge are exported with ringshield/expand/cross_score.py --embed-edges.

Outputs: <out>/pairs_train.parquet, pairs_train.json (sizes, class ratio, components with more
than one ring, role distribution), included_train.parquet, config.yaml, environment.txt.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.expand.features import EmbeddingStore, FEATURE_COLUMNS  # noqa: E402
from ringshield.expand.index import SplitIndex  # noqa: E402
from ringshield.expand.make_training_set import fold_seed_mask  # noqa: E402
from ringshield.expand.policy import LGB_PARAMS  # noqa: E402
from ringshield.partition.pairs import PAIR_FEATURES, components_of, pair_features  # noqa: E402
from ringshield.run_rings import _git_commit, write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402

CROSS = REPO_ROOT / "experiments" / "R3_cross_scores"
TS = REPO_ROOT / "experiments" / "R3_expansion" / "training_set.parquet"
POLICY = REPO_ROOT / "experiments" / "R3_expansion" / "policy_proposed" / "policy.json"
R3_RUN = REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed" / "seed1" / "config.yaml"


def oof_policy_probs(ts: pd.DataFrame, policy_json: Path, seed: int = 1) -> np.ndarray:
    """Out-of-fold probabilities of the proposed policy on its own training rows (same grouped
    folds, same parameters, no early stopping: the recorded final round count)."""
    import lightgbm as lgb
    from sklearn.model_selection import GroupKFold
    doc = json.loads(policy_json.read_text(encoding="utf-8"))
    feats, cv = doc["features"], doc["cv"]
    params = dict(LGB_PARAMS, scale_pos_weight=cv["params"]["scale_pos_weight"], seed=seed)
    X, y, groups = ts[feats].to_numpy(np.float32), ts["label"].to_numpy(np.int64), ts["ring_id"].to_numpy()
    rng = np.random.default_rng(seed)
    uniq = np.unique(groups)
    perm = {g: i for i, g in enumerate(rng.permutation(uniq))}
    gk = np.array([perm[g] for g in groups])
    oof = np.full(len(y), np.nan)
    for tr_i, va_i in GroupKFold(n_splits=5).split(X, y, gk):
        b = lgb.train(params, lgb.Dataset(X[tr_i], y[tr_i], feature_name=feats), num_boost_round=int(cv["final_num_boost_round"]))
        oof[va_i] = b.predict(X[va_i])
    assert not np.isnan(oof).any()
    return oof


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "experiments" / "R4_partition")
    ap.add_argument("--cross-scores", type=Path, default=CROSS)
    ap.add_argument("--training-set", type=Path, default=TS)
    ap.add_argument("--policy-json", type=Path, default=POLICY)
    ap.add_argument("--p-min", type=float, default=None, help="default: the R3 proposed seed-1 run's val-chosen p_min")
    ap.add_argument("--seed-frac-pct", type=float, default=0.1)
    ap.add_argument("--no-embed", action="store_true")
    args = ap.parse_args(argv)
    t_start = time.time()
    args.out.mkdir(parents=True, exist_ok=True)
    paths = load_paths()
    p_min = args.p_min if args.p_min is not None else float(yaml.safe_load(R3_RUN.read_text(encoding="utf-8"))["chosen"]["p_min"])

    # ---- train scored edges, seeds per fold ------------------------------------------------------
    xs = args.cross_scores / "cross_scores_train.parquet"
    se = build_scored_edges(xs, "train", model_id="gine_causal_xfold", seed=1, processed_dir=paths["processed_dir"], keep_unscored=False)
    cross = pd.read_parquet(xs).set_index("edge_id").reindex(se["edge_id"]).reset_index()
    seed_mask, fold_rows = fold_seed_mask(cross, args.seed_frac_pct)
    idx = SplitIndex.build(se)
    tr = pd.read_parquet(paths["processed_dir"] / "amlworld_train.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    gfp = pd.read_parquet(paths["processed_dir"] / "amlworld_gfp_features_train.parquet").set_index("EdgeID")
    gfp = gfp.reindex(idx.edge_id)[[c for c in gfp.columns]].to_numpy(np.float32)
    print(f"[pairs] train: {len(se):,} edges, seeds {int(seed_mask.sum()):,} (within-fold {args.seed_frac_pct} %)")

    # ---- expanded edges: out-of-fold policy probability >= p_min on the 6.3 candidate rows -----
    ts = pd.read_parquet(args.training_set)
    t0 = time.time()
    oof = oof_policy_probs(ts, args.policy_json)
    added_ids = np.unique(ts.loc[oof >= p_min, "candidate_edge_id"].to_numpy(np.int64))
    n_added_pos = int(ts.loc[oof >= p_min].drop_duplicates("candidate_edge_id")["label"].sum())
    print(f"[pairs] out-of-fold policy on {len(ts):,} rows ({time.time() - t0:.0f}s): {len(added_ids):,} edges added at p >= {p_min} "
          f"({n_added_pos} member edges); OOF AUC-PR check {float(__import__('sklearn.metrics', fromlist=['average_precision_score']).average_precision_score(ts['label'], oof)):.3f}")
    exp_mask = np.zeros(len(se), dtype=bool)
    exp_mask[idx.pos_of(added_ids)] = True
    exp_mask &= ~seed_mask
    inc_pos = np.flatnonzero(seed_mask | exp_mask)
    is_seed = seed_mask[inc_pos]
    comp = components_of(idx, inc_pos)
    ring_id = tr.reindex(idx.edge_id[inc_pos]).fillna(-1).to_numpy(np.int64)
    fold_of = cross["fold"].to_numpy()[inc_pos]
    inc = pd.DataFrame({"edge_id": idx.edge_id[inc_pos], "pos": inc_pos, "component": comp, "is_seed": is_seed, "ring_id": ring_id, "fold": fold_of})
    inc.to_parquet(args.out / "included_train.parquet", index=False)
    csize = inc.groupby("component").size()
    nrings = inc[inc["ring_id"] > 0].groupby("component")["ring_id"].nunique()
    print(f"[pairs] included {len(inc):,} edges ({int(is_seed.sum()):,} seeds + {int((~is_seed).sum()):,} expanded) in {csize.size:,} components; "
          f"largest {int(csize.max())}; components with > 1 ring: {int((nrings > 1).sum())}")

    # ---- embeddings: every included edge under every fold model ---------------------------------
    emb_of = None
    if not args.no_embed:
        need = pd.DataFrame({"edge_id": np.repeat(inc["edge_id"].to_numpy(), 5), "fold": np.tile(np.arange(5), len(inc))})
        need.to_parquet(args.out / "needed_embeddings_pairs.parquet", index=False)
        missing = {}
        for k in range(5):
            p = args.cross_scores / f"embeddings_fold{k}.parquet"
            have = set(pd.read_parquet(p, columns=["edge_id"])["edge_id"].tolist()) if p.exists() else set()
            missing[k] = int((~inc["edge_id"].isin(have)).sum())
        if any(missing.values()):
            print(f"[pairs] embedding pass needed: {missing} edges per fold")
            from ringshield.expand.cross_score import CrossScorer
            cs = CrossScorer(REPO_ROOT / "experiments" / "R1_gine_causal", args.cross_scores, epochs=0, dry_run=False)
            cs.embed(need)
        stores = {k: EmbeddingStore.from_parquet(args.cross_scores / f"embeddings_fold{k}.parquet", edge_ids=inc["edge_id"].to_numpy()) for k in range(5)}
        fold_by_pos = pd.Series(fold_of, index=inc_pos)

        def emb_of(pa, pb):
            A = np.full((len(pa), stores[0].dim), np.nan, np.float32)
            B = A.copy()
            fa = fold_by_pos.loc[pa].to_numpy()
            for k in range(5):
                m = fa == k
                if m.any():
                    A[m] = stores[k].get(idx.edge_id[pa[m]])
                    B[m] = stores[k].get(idx.edge_id[pb[m]])
            return A, B

    # ---- pairs ----------------------------------------------------------------------------------------
    t0 = time.time()
    P = pair_features(idx, gfp, inc_pos, is_seed, comp, emb_of=emb_of, ring_id=ring_id)
    P["fold_a"] = fold_by_pos.loc[idx.pos_of(P["edge_a"].to_numpy())].to_numpy() if not args.no_embed else -1
    P.to_parquet(args.out / "pairs_train.parquet", index=False)
    n, n_pos = len(P), int(P["label"].sum())
    comp_pairs = P.groupby("component")["label"].agg(["size", "sum", "mean"])
    roles = {r: int(P[f"role_{r}"].sum()) for r in ("source", "sink", "mule", "other")}
    stats = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
             "inputs": {"cross_scores": str(xs), "training_set": str(args.training_set), "policy_json": str(args.policy_json), "p_min": p_min,
                        "seed_frac_pct": args.seed_frac_pct, "seeds_per_fold": fold_rows},
             "included": {"n": int(len(inc)), "n_seeds": int(is_seed.sum()), "n_expanded": int((~is_seed).sum()), "n_expanded_member": n_added_pos,
                          "n_components": int(csize.size), "largest_component": int(csize.max()), "components_with_gt1_ring": int((nrings > 1).sum()),
                          "components_with_pairs": int(P["component"].nunique())},
             "pairs": {"n": n, "n_pos": n_pos, "n_neg": n - n_pos, "pos_rate": n_pos / n if n else None,
                       "by_kind": {k: {"n": int(P[f"kind_{k}"].sum()), "n_pos": int(P.loc[P[f"kind_{k}"] == 1, "label"].sum())} for k in ("seed_seed", "seed_exp", "exp_exp")},
                       "by_role": {r: {"n": int(P[f"role_{r}"].sum()), "n_pos": int(P.loc[P[f"role_{r}"] == 1, "label"].sum())} for r in ("source", "sink", "mule", "other")},
                       "components_all_positive": int((comp_pairs["mean"] == 1).sum()), "components_mixed": int(((comp_pairs["mean"] > 0) & (comp_pairs["mean"] < 1)).sum()),
                       "components_all_negative": int((comp_pairs["mean"] == 0).sum()), "cos_emb_nan": int(P["cos_emb"].isna().sum()),
                       "n_features": len(PAIR_FEATURES)},
             "seconds": round(time.time() - t_start, 1), "out": str(args.out / "pairs_train.parquet")}
    (args.out / "pairs_train.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    (args.out / "config.yaml").write_text(yaml.dump({"step": "7.1 pairs training set", **{k: str(v) for k, v in vars(args).items()},
                                                     "p_min_used": p_min, "created_utc": stats["created_utc"], "git_commit": stats["git_commit"]},
                                                    sort_keys=False), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    print(f"[pairs] {n:,} pairs ({n_pos:,} same-ring, {stats['pairs']['pos_rate']:.3f}); components all-positive {stats['pairs']['components_all_positive']}, "
          f"mixed {stats['pairs']['components_mixed']}, all-negative {stats['pairs']['components_all_negative']}; roles {roles}; {time.time() - t0:.0f}s -> {args.out}")
    return stats


if __name__ == "__main__":
    main()
