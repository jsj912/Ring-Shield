"""Expansion-policy training set from the cross-scored train split (Step 6.3).

    python ringshield/expand/make_training_set.py --cross-scores experiments/R3_cross_scores \\
        --out experiments/R3_expansion [--delta-t-h 72] [--max-hops 2] [--seed-frac-pct 0.1]
    python ringshield/expand/make_training_set.py ... --dry-run --no-embed

Requires `cross_scores_train.parquet` (ringshield/expand/cross_score.py; the assertion that no
edge was scored by a model trained on its day is re-checked here from the fold records).

For every train-visible ring (membership = the test_visible definition applied to the train
split: the ring's transactions inside the split, i.e. the split parquet's `ring_id` column,
asserted equal to ringshield.truth.load_ground_truth on the train window -- amendment c):

    seeds      = its member edges with score_raw > q_fold, q_fold = the (100 - k*) percentile of the
                 cross-scores WITHIN THE EDGE'S FOLD (fold models are on different scales), strict
                 cut, k* = the validation-chosen seed fraction of R2 B0 (0.1 %)
    candidates = ringshield.expand.candidates(train scored edges, seeds, delta_t, max_hops)
    label      = 1 if the candidate is a member edge of the same ring, else 0
    features   = ringshield.expand.features.compute_features at the candidate's timestamp; the
                 detector feature is the within-fold score quantile, dead_region from the fold
                 model's head constants (amendments a, d); embeddings are the fold-k model's for
                 candidates of fold k AND for the ring's included edges (one model per row)

Rows whose candidate lies on day 0 are dropped (amendment b, docs/FEATURE_CAUSALITY.md section
7); seeds on day 0 still anchor. Rings with zero seeds contribute no rows and are counted in the
ceiling. Output:

    <out>/training_set.parquet      ring_id, pattern_type, fold, day, label + feature rows
    <out>/candidates.parquet        every candidate row before the day-0 drop (ring_id, label, ...)
    <out>/training_set.json         sizes, class ratio (overall / per hop / per fold / per pattern),
                                    seeds per fold (q, count, boundary ties), rings with zero
                                    seeds, the quiet-member ceiling
    <out>/config.yaml, environment.txt
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
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from ringshield.aggregators.cc import threshold_for_pct  # noqa: E402
from ringshield.expand.candidates import candidates  # noqa: E402
from ringshield.expand.features import FEATURE_COLUMNS, GFP_COLS, KEY_COLUMNS, EmbeddingStore, FeatureContext, compute_features  # noqa: E402
from ringshield.expand.index import SplitIndex, set_index  # noqa: E402
from ringshield.run_rings import write_environment  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth, split_window  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

DEFAULT_CROSS = REPO_ROOT / "experiments" / "R3_cross_scores"
DEFAULT_OUT = REPO_ROOT / "experiments" / "R3_expansion"
K_SOURCE = REPO_ROOT / "experiments" / "R2_b0" / "gine_causal" / "seed1" / "config.yaml"
META_COLUMNS = ["ring_id", "pattern_type", "fold", "day", "label", "shared_account", "via_edge_id", "gap_via_s", "is_member_edge"]


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def chosen_k(path: Path = K_SOURCE) -> float:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return float(cfg["chosen"]["seed_frac_pct"])


def fold_seed_mask(cross: pd.DataFrame, k_pct: float) -> tuple[np.ndarray, list[dict]]:
    """Strict quantile cut of score_raw within each fold (the same rule as B0, per fold)."""
    mask = np.zeros(len(cross), dtype=bool)
    rows = []
    for k, g in cross.groupby("fold"):
        s = g["score_raw"].to_numpy(float)
        q = threshold_for_pct(s, k_pct)
        m = s > q
        mask[g.index.to_numpy()] = m
        rows.append({"fold": int(k), "n_edges": int(len(g)), "q": q, "n_seeds": int(m.sum()),
                     "n_on_boundary": int((s == q).sum()), "seed_frac_pct_realised": float(m.mean() * 100)})
    return mask, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cross-scores", type=Path, default=DEFAULT_CROSS)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--delta-t-h", type=float, default=72.0)
    ap.add_argument("--max-hops", type=int, default=2)
    ap.add_argument("--seed-frac-pct", type=float, default=None, help=f"default: chosen cell of {K_SOURCE.relative_to(REPO_ROOT)}")
    ap.add_argument("--ring-gt", type=Path, default=None)
    ap.add_argument("--no-embed", action="store_true", help="skip the embedding pass (cosine features NaN)")
    ap.add_argument("--dry-run", action="store_true", help="use the *_dryrun cross-scores (1 %% of train)")
    args = ap.parse_args(argv)
    t_start = time.time()
    tag = "_dryrun" if args.dry_run else ""
    paths = load_paths()
    args.out.mkdir(parents=True, exist_ok=True)
    k_pct = args.seed_frac_pct if args.seed_frac_pct is not None else chosen_k()
    k_src = "--seed-frac-pct" if args.seed_frac_pct is not None else f"{K_SOURCE.relative_to(REPO_ROOT)} (chosen on val)"

    # ---- cross-scores and their assertion ------------------------------------------------
    xs_path = args.cross_scores / f"cross_scores_train{tag}.parquet"
    summary = json.loads((args.cross_scores / f"cross_scores{tag}.json").read_text(encoding="utf-8"))
    assert summary["assertion"]["passed"], summary["assertion"]
    cross = pd.read_parquet(xs_path)
    train_days = {f["fold"]: set(f["train_days"]) for f in summary["folds"]}
    viol = int(sum(d in train_days[f] for d, f in zip(cross["day"].tolist(), cross["fold"].tolist())))
    assert viol == 0, f"{viol} cross-scored edges come from a model trained on their day"
    print(f"[training_set] cross-scores {xs_path.name}: {len(cross):,} rows, {cross['fold'].nunique()} folds, "
          f"assertion re-checked (0 violations)")

    # ---- train scored edges, membership, seeds ------------------------------------------
    se = build_scored_edges(xs_path, "train", model_id="gine_causal_xfold", seed=1, processed_dir=paths["processed_dir"],
                            keep_unscored=False)
    tr = pd.read_parquet(paths["processed_dir"] / "amlworld_train.parquet",
                         columns=["EdgeID", "ring_id", "pattern_type", "Is Laundering", "Timestamp"])
    tr = tr[tr["EdgeID"].isin(se["edge_id"])].reset_index(drop=True)
    win = split_window(paths["processed_dir"] / "amlworld_train.parquet")
    days = load_windows()["val"].days_of(se["timestamp"].to_numpy())
    ring_of = tr.set_index("EdgeID")["ring_id"]
    members = tr[tr["ring_id"] > 0].groupby("ring_id")
    pattern_of = members["pattern_type"].first().to_dict()
    member_edges = members["EdgeID"].apply(lambda s: sorted(int(x) for x in s)).to_dict()
    if not args.dry_run:                                     # amendment c: the parquet column IS the test_visible truth
        ring_gt = args.ring_gt or paths["processed_dir"] / "amlworld_ring_ground_truth.parquet"
        truth, _ = load_ground_truth(ring_gt, *win, "test_visible", verbose=False)
        full = pd.read_parquet(paths["processed_dir"] / "amlworld_train.parquet", columns=["ring_id", "from_id", "to_id"])
        acc = {rid: set(g["from_id"]) | set(g["to_id"]) for rid, g in full[full["ring_id"] > 0].groupby("ring_id")}
        assert set(acc) == set(truth), (len(acc), len(truth))
        assert all(acc[r] == truth[r] for r in truth), "train parquet ring_id != test_visible ground truth on the train window"
        print(f"[training_set] membership check: {len(truth)} train-visible rings, parquet ring_id == test_visible truth")
    cross = cross.set_index("edge_id").reindex(se["edge_id"]).reset_index()
    seed_mask, fold_rows = fold_seed_mask(cross, k_pct)
    se["is_seed"] = seed_mask
    seed_ids = set(se.loc[seed_mask, "edge_id"].tolist())
    dry_seed_note = None
    if args.dry_run:
        # 1 % sample: (almost) no ring edge clears the cut and a seed's accounts keep ~1 % of their
        # edges, so every sampled ring edge anchors -- a pipeline check only, recorded in training_set.json
        seed_ids = {e for es in member_edges.values() for e in es}
        dry_seed_note = "dry run: every sampled ring member edge used as a seed (pipeline check only)"
        print(f"[training_set] {dry_seed_note}")
    for r in fold_rows:
        print(f"  fold {r['fold']}: {r['n_edges']:,} edges, q {r['q']:.6f}, seeds {r['n_seeds']:,} "
              f"({r['seed_frac_pct_realised']:.3f} %), {r['n_on_boundary']} tied on the boundary")
    idx = SplitIndex.build(se)
    set_index(idx, ("train", len(se)))

    # ---- candidates per ring -----------------------------------------------------------------
    t0 = time.time()
    parts, ring_rows, n_trunc = [], [], 0
    for rid, edges in member_edges.items():
        seeds = [e for e in edges if e in seed_ids]
        quiet = [e for e in edges if e not in seed_ids]
        row = {"ring_id": int(rid), "pattern_type": pattern_of[rid], "n_member_edges": len(edges), "n_seeds": len(seeds),
               "n_quiet": len(quiet), "n_candidates": 0, "n_positive": 0, "n_quiet_reached": 0}
        if seeds:
            c = candidates(se, seeds, args.delta_t_h, args.max_hops, index=idx)
            n_trunc += c.attrs.get("n_truncated", 0)
            c.insert(0, "ring_id", int(rid))
            c["label"] = (ring_of.reindex(c["candidate_edge_id"].to_numpy()).fillna(-1).to_numpy() == rid).astype(np.int64)
            c["is_member_edge"] = (ring_of.reindex(c["candidate_edge_id"].to_numpy()).fillna(-1).to_numpy() > 0).astype(np.int64)
            row.update(n_candidates=int(len(c)), n_positive=int(c["label"].sum()), n_quiet_reached=int(c["label"].sum()))
            parts.append(c)
        ring_rows.append(row)
    rings_df = pd.DataFrame(ring_rows)
    cand = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    assert len(cand), "no candidates at all" + (" (dry run: the 1 % sample can be too sparse; try --delta-t-h 720)" if args.dry_run else "")
    pos_of = pd.Series(np.arange(len(se)), index=se["edge_id"].to_numpy())
    cpos = pos_of.reindex(cand["candidate_edge_id"].to_numpy()).to_numpy()
    cand["fold"] = cross["fold"].to_numpy()[cpos]
    cand["day"] = days[cpos].astype(np.int64)
    cand.to_parquet(args.out / f"candidates{tag}.parquet", index=False)
    print(f"[training_set] candidates: {len(cand):,} rows over {int((rings_df['n_seeds'] > 0).sum())} rings with seeds "
          f"({int((rings_df['n_seeds'] == 0).sum())} rings with zero seeds), positives {int(cand['label'].sum()):,}, "
          f"{time.time() - t0:.0f}s, {n_trunc} truncated queries")

    # ---- embeddings: fold-k model for fold-k candidates and their rings' seeds -------------------
    stores: dict[int, EmbeddingStore | None] = {}
    if not args.no_embed:
        need = []
        seeds_of = {int(r): [e for e in member_edges[r] if e in seed_ids] for r in member_edges}
        for (rid, k), g in cand.groupby(["ring_id", "fold"]):
            ids = np.concatenate([g["candidate_edge_id"].to_numpy(np.int64), np.asarray(seeds_of[int(rid)], np.int64)])
            need.append(pd.DataFrame({"edge_id": ids, "fold": int(k)}))
        need = pd.concat(need, ignore_index=True).drop_duplicates()
        need_path = args.out / f"needed_embeddings{tag}.parquet"
        need.to_parquet(need_path, index=False)
        missing = {}
        for k, g in need.groupby("fold"):
            p = args.cross_scores / f"embeddings_fold{int(k)}{tag}.parquet"
            have = set(pd.read_parquet(p, columns=["edge_id"])["edge_id"].tolist()) if p.exists() else set()
            missing[int(k)] = int((~g["edge_id"].isin(have)).sum())
        if any(missing.values()):
            print(f"[training_set] embedding pass needed: {missing} edges per fold -> cross_score.py --embed-edges")
            from ringshield.expand.cross_score import CrossScorer
            cs = CrossScorer(REPO_ROOT / "experiments" / "R1_gine_causal", args.cross_scores, epochs=0, dry_run=args.dry_run)
            cs.embed(need)
        for k in sorted(need["fold"].unique()):
            p = args.cross_scores / f"embeddings_fold{int(k)}{tag}.parquet"
            stores[int(k)] = EmbeddingStore.from_parquet(p, edge_ids=need.loc[need["fold"] == k, "edge_id"].to_numpy())
        print(f"[training_set] embeddings: " + ", ".join(f"fold {k} {len(s.edge_ids):,}" for k, s in stores.items()))

    # ---- features per (ring, fold) --------------------------------------------------------------
    t0 = time.time()
    gfp = pd.read_parquet(paths["processed_dir"] / "amlworld_gfp_features_train.parquet")
    gfp = gfp[gfp["EdgeID"].isin(se["edge_id"])]
    base = FeatureContext.build(se, score_quantile=cross.set_index("edge_id")["score_quantile"],
                                dead_region=cross.set_index("edge_id")["dead_region"], gfp=gfp, index=idx)
    feats = []
    for (rid, k), g in cand.groupby(["ring_id", "fold"], sort=True):
        ctx = FeatureContext(idx=base.idx, score_quantile=base.score_quantile, dead_region=base.dead_region, gfp=base.gfp,
                             emb=stores.get(int(k)))
        seeds = [e for e in member_edges[int(rid)] if e in seed_ids]
        X = compute_features(ctx, g.reset_index(drop=True), seeds, args.delta_t_h)
        for c in META_COLUMNS:
            X[c] = g[c].to_numpy() if c in g.columns else pattern_of[int(rid)]
        feats.append(X)
    X = pd.concat(feats, ignore_index=True)
    assert len(X) == len(cand) and (X["max_ts_used"] <= X["candidate_ts"]).all()
    assert X["candidate_ts"].between(*win).all() and X["max_included_ts"].between(*win).all()
    print(f"[training_set] features: {len(X):,} rows x {len(FEATURE_COLUMNS)} features, {time.time() - t0:.0f}s")

    # ---- day-0 drop, write --------------------------------------------------------------------------
    day0 = X["day"] == 0
    n_day0, n_day0_pos = int(day0.sum()), int(X.loc[day0, "label"].sum())
    X = X[~day0].reset_index(drop=True)
    X = X[META_COLUMNS + KEY_COLUMNS + FEATURE_COLUMNS]
    out_path = args.out / f"training_set{tag}.parquet"
    X.to_parquet(out_path, index=False)

    n, n_pos = len(X), int(X["label"].sum())
    by = lambda col: {str(k): {"n": int(len(g)), "n_pos": int(g["label"].sum()),   # noqa: E731
                               "pos_rate": float(g["label"].mean()) if len(g) else None} for k, g in X.groupby(col)}
    with_seeds = rings_df[rings_df["n_seeds"] > 0]
    stats = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(), "dry_run": args.dry_run,
        "inputs": {"cross_scores": str(xs_path), "cross_scores_assertion": summary["assertion"], "train_split": "amlworld_train.parquet",
                   "gfp": "amlworld_gfp_features_train.parquet", "embeddings": None if args.no_embed else
                   {int(k): str(args.cross_scores / f"embeddings_fold{int(k)}{tag}.parquet") for k in stores}},
        "params": {"delta_t_h": args.delta_t_h, "max_hops": args.max_hops, "seed_frac_pct": k_pct, "seed_frac_source": k_src,
                   "cut": "strict, quantile within the edge's fold", "membership": "train parquet ring_id == test_visible on the train window"},
        "seeds_per_fold": fold_rows, "n_seed_edges_total": int(seed_mask.sum()), "dry_run_seed_note": dry_seed_note,
        "rings": {"train_visible": int(len(rings_df)), "with_seeds": int(len(with_seeds)), "zero_seeds": int((rings_df["n_seeds"] == 0).sum()),
                  "member_edges_total": int(rings_df["n_member_edges"].sum()), "seed_member_edges": int(rings_df["n_seeds"].sum()),
                  "quiet_member_edges": int(rings_df["n_quiet"].sum()),
                  "quiet_member_edges_in_rings_with_seeds": int(with_seeds["n_quiet"].sum()),
                  "quiet_reached_as_candidates": int(with_seeds["n_quiet_reached"].sum()),
                  "zero_seed_rings_by_pattern": rings_df[rings_df["n_seeds"] == 0]["pattern_type"].value_counts().to_dict()},
        "candidates_before_day0_drop": {"n": int(len(cand)), "n_pos": int(cand["label"].sum()), "n_truncated_queries": n_trunc,
                                        "by_hop": {str(h): {"n": int(len(g)), "n_pos": int(g["label"].sum())} for h, g in cand.groupby("hop")}},
        "day0_dropped": {"n": n_day0, "n_pos": n_day0_pos},
        "training_set": {"n_rows": n, "n_pos": n_pos, "n_neg": n - n_pos, "pos_rate": n_pos / n if n else None,
                         "neg_per_pos": (n - n_pos) / n_pos if n_pos else None,
                         "n_rings": int(X["ring_id"].nunique()), "n_rings_with_positive": int(X.loc[X["label"] == 1, "ring_id"].nunique()),
                         "by_hop": by("hop"), "by_fold": by("fold"), "by_pattern": by("pattern_type"), "by_day": by("day"),
                         "n_dead_region_rows": int(X["dead_region"].sum()), "n_features": len(FEATURE_COLUMNS),
                         "cosine_nan_rows": int(X["cos_anchor"].isna().sum())},
        "quiet_ceiling_note": "quiet members = member edges below the seed cut; the policy can only recover the ones "
                              "that appear as candidates (quiet_reached_as_candidates); rings with zero seeds contribute nothing",
        "out": str(out_path), "seconds": round(time.time() - t_start, 1),
    }
    (args.out / f"training_set{tag}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    rings_df.to_csv(args.out / f"rings{tag}.csv", index=False)
    cfg = {"experiment": args.out.name, "step": "6.3 expansion training set", "created_utc": stats["created_utc"],
           "git_commit": stats["git_commit"], **{k: (str(v) if isinstance(v, Path) else v) for k, v in vars(args).items()},
           "params": stats["params"], "feature_columns": FEATURE_COLUMNS, "gfp_cols": GFP_COLS}
    (args.out / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
    write_environment(args.out / "environment.txt")
    r = stats["rings"]
    ratio = stats["training_set"]["neg_per_pos"]
    print(f"[training_set] {n:,} rows ({n_pos:,} positive, 1 : {ratio if ratio is None else round(ratio)}); day-0 dropped "
          f"{n_day0:,} ({n_day0_pos} positive); rings {r['train_visible']} visible / {r['with_seeds']} with seeds / "
          f"{r['zero_seeds']} zero seeds; quiet member edges {r['quiet_member_edges']} of {r['member_edges_total']}, "
          f"{r['quiet_reached_as_candidates']} reachable -> {out_path}")
    return stats


if __name__ == "__main__":
    main()
