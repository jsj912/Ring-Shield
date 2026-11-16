"""M1: over-generate at 0.2 % and verify (paper/PREREG_METHOD_2026-11-15.md + amendments 1 and 2).

Subcommands (all outputs under experiments/M1_verifier/ unless --out is given):

    refgen    --split val|test --seed S --k 0.1     reproduce REF (ring-folded full) with this generator
    discover  --iter N                              train generator with a recording embedding store;
                                                    writes embed/needed_iter<N>.parquet (edge_id, fold)
    export    --needed FILE [--folds K ...]         CrossScorer embed pass on the copied fold checkpoints
    check                                           recomputed vs stored embeddings (amendment 2 §6)
    candidates --split train|val|test --seed S      candidate rings at 0.2 % + per-ring features
    fit       --seed S                              LightGBM verifier (M1-V, M1-V-IS), val selection,
                                                    score-only filter, seed-1 gate; no test scoring

Test labels are never read here: test candidates are written as rings files for
evaluation/score_external.py only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

EXP = REPO_ROOT / "experiments"
OUT = EXP / "M1_verifier"
EMBED = OUT / "embed"
R1 = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"   # has checkpoints + embeddings for seeds 1-5 (REF used it)
R1_RUN_DIR = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"   # run_dir of the cross-score config
XS = EXP / "R3_ringfold" / "cross_scores"
POLICY = EXP / "R3_ringfold" / "expansion" / "policy_proposed"
AFFINITY = EXP / "R4_partition" / "affinity"
R3_CFG = EXP / "R3_ringfold" / "runs" / "proposed" / "seed{S}" / "config.yaml"
R4_CFG = EXP / "R4_partition_ringfold" / "average" / "seed{S}" / "config.yaml"
K_M1 = 0.20
T_GRID = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
Q_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8)
LGBM_PARAMS = dict(n_estimators=200, learning_rate=0.05, num_leaves=15, min_child_samples=20, subsample=0.8,
                   subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, deterministic=True, force_row_wise=True,
                   n_jobs=8, verbose=-1)
IS_FEATURES = ["exp_prob_mean", "exp_prob_min", "exp_prob_count", "confidence", "max_edge_prob"]   # amendment 1


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cells(S: int) -> tuple[dict, dict]:
    r3 = yaml.safe_load(Path(str(R3_CFG).format(S=S)).read_text(encoding="utf-8"))["chosen"]
    r4 = yaml.safe_load(Path(str(R4_CFG).format(S=S)).read_text(encoding="utf-8"))["chosen"]
    assert (int(r4["min_size"]), float(r4["p_min"]), float(r4["delta_t_h"])) == \
        (int(r3["min_size"]), float(r3["p_min"]), float(r3["delta_t_h"])), "R3/R4 cells disagree"
    return r3, r4


# ----------------------------------------------------------------------------------- generator
def generate(se, ctx, mask, r3, r4, policy, affinity, *, with_probs=True):
    """The evaluation/budget_sweep.py::run_detector route (expand -> components -> affinity ->
    partition -> rings), with only the inputs changed."""
    from ringshield.aggregators.expand import expand_all
    from ringshield.aggregators.full import (component_pairs, expansion_probs, included_from_trajectories,
                                             partition_labels, rings_from_edge_clusters)
    from ringshield.partition.pairs import components_of
    min_size, p_min, dt = int(r3["min_size"]), float(r3["p_min"]), float(r3["delta_t_h"])
    trajs = expand_all(se, mask, policy, ctx, delta_t_h=dt, p_floor=p_min)
    inc_pos, is_seed = included_from_trajectories(se, mask, trajs, p_min)
    comp = components_of(ctx.idx, inc_pos)
    P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=min_size,
                           **{x: r4[x] for x in ("cut", "threshold", "gap_h", "resolution") if x in r4})
    probs = expansion_probs(trajs, p_min) if with_probs else None
    rings = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, min_size, probs=probs)
    return rings, trajs


def load_eval_split(split: str, S: int):
    from contract.make_scored_edges import load_paths
    from ringshield.expand.context import build_context
    from ringshield.scored_edges import build_scored_edges
    pdir = load_paths()["processed_dir"]
    se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
    ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                        embeddings_parquet=R1 / f"embeddings_{split}_seed{S}.parquet",
                        checkpoint=R1 / f"model_best_seed{S}.pt")
    return se, ctx, pdir


def val_truth(pdir):
    from ringshield.truth import load_ground_truth, split_window
    return load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *split_window(pdir / "amlworld_val.parquet"),
                             "test_visible", verbose=False)


def val_f1(rings, truth, pat) -> dict:
    from evaluation.ring_metrics import evaluate_rings
    m = evaluate_rings([r.member_set for r in rings], truth, 0.5, pat)
    return {"ring_f1": float(m.ring_f1), "ring_precision": float(m.ring_precision), "ring_recall": float(m.ring_recall),
            "n_rings": len(rings), "n_accounts": int(len(set().union(*[r.member_set for r in rings])) if rings else 0)}


# ----------------------------------------------------------------------------------- train split
class RecordingStore:
    """EmbeddingStore stand-in: known rows from `base`, zeros for the rest, every missing id logged."""

    def __init__(self, base, dim: int):
        self.base, self._dim, self.missing = base, dim, set()

    @property
    def dim(self):
        return self._dim

    def get(self, edge_ids):
        e = np.asarray(edge_ids, dtype=np.int64)
        out = np.zeros((len(e), self._dim), np.float32)
        if self.base is not None and len(self.base.edge_ids):
            p = np.clip(np.searchsorted(self.base.edge_ids, e), 0, len(self.base.edge_ids) - 1)
            hit = self.base.edge_ids[p] == e
            out[hit] = self.base.matrix[p[hit]]
        else:
            hit = np.zeros(len(e), bool)
        self.missing.update(int(x) for x in e[~hit])
        return out


def exported_store():
    """Owner-fold embeddings exported so far (embed/embeddings_fold<k>.parquet), each edge from its own fold."""
    from ringshield.expand.features import EmbeddingStore
    owner = pd.read_parquet(XS / "cross_scores_train.parquet", columns=["edge_id", "fold"]).set_index("edge_id")["fold"]
    parts = []
    for k in range(5):
        p = EMBED / f"embeddings_fold{k}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df = df[owner.reindex(df["edge_id"]).to_numpy() == k]
            parts.append(df)
    if not parts:
        return None
    df = pd.concat(parts, ignore_index=True)
    cols = [c for c in df.columns if c.startswith("emb_")]
    return EmbeddingStore(df["edge_id"].to_numpy(np.int64), df[cols].to_numpy(np.float32))


def load_train(emb):
    from contract.make_scored_edges import load_paths
    from ringshield.expand.features import FeatureContext
    from ringshield.expand.index import SplitIndex, set_index
    from ringshield.expand.make_training_set import fold_seed_mask
    from ringshield.scored_edges import build_scored_edges
    pdir = load_paths()["processed_dir"]
    summary = json.loads((XS / "cross_scores.json").read_text(encoding="utf-8"))
    assert summary["assertion"]["passed"]
    cross = pd.read_parquet(XS / "cross_scores_train.parquet")
    rf = pd.read_parquet(XS / "ring_folds.parquet")
    assert int((cross.set_index("edge_id")["fold"].reindex(rf["edge_id"]).to_numpy() != rf["fold"].to_numpy()).sum()) == 0
    se = build_scored_edges(XS / "cross_scores_train.parquet", "train", model_id="gine_causal_xfold", seed=1,
                            processed_dir=pdir, keep_unscored=False)
    cross = cross.set_index("edge_id").reindex(se["edge_id"]).reset_index()
    mask, fold_rows = fold_seed_mask(cross, K_M1)
    se["is_seed"] = mask
    idx = SplitIndex.build(se)
    set_index(idx, ("train", len(se)))
    gfp = pd.read_parquet(pdir / "amlworld_gfp_features_train.parquet")
    gfp = gfp[gfp["EdgeID"].isin(se["edge_id"])]
    ctx = FeatureContext.build(se, score_quantile=cross.set_index("edge_id")["score_quantile"],
                               dead_region=cross.set_index("edge_id")["dead_region"], gfp=gfp, emb=emb, index=idx)
    return se, ctx, mask, fold_rows, cross, pdir


def train_cells() -> dict:
    """Distinct (R3, R4) cells over detector seeds 1-5 -> seeds sharing each."""
    out = {}
    for S in range(1, 6):
        r3, r4 = cells(S)
        key = json.dumps({"r3": {k: r3[k] for k in ("min_size", "p_min", "delta_t_h")},
                          "r4": {k: r4[k] for k in ("method", "cut") if k in r4}}, sort_keys=True)
        out.setdefault(key, []).append(S)
    return out


def cmd_discover(a):
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    base = exported_store()
    dim = base.dim if base is not None else int(len([c for c in pd.read_parquet(XS / "embeddings_fold0.parquet").columns
                                                     if c.startswith("emb_")]))
    store = RecordingStore(base, dim)
    se, ctx, mask, fold_rows, cross, _ = load_train(store)
    policy, affinity = Policy.load(POLICY), Affinity.load(AFFINITY)
    rec = {"iter": a.iter, "created_utc": now(), "fold_seed_rows": fold_rows, "cells": {}}
    for key, seeds in train_cells().items():
        r3, r4 = cells(seeds[0])
        t0 = time.time()
        rings, trajs = generate(se, ctx, mask, r3, r4, policy, affinity, with_probs=False)
        rec["cells"][key] = {"seeds": seeds, "n_rings": len(rings), "seconds": round(time.time() - t0, 1)}
        print(f"[discover] cell {key} seeds {seeds}: {len(rings)} rings, missing so far {len(store.missing):,}", flush=True)
    owner = cross.set_index("edge_id")["fold"]
    miss = np.array(sorted(store.missing), np.int64)
    need = pd.DataFrame({"edge_id": miss, "fold": owner.reindex(miss).to_numpy(np.int64)})
    if a.iter == 0:   # amendment 2 §6: include every stored owner-fold edge, for the reproduction check
        for k in range(5):
            st = pd.read_parquet(XS / f"embeddings_fold{k}.parquet", columns=["edge_id"])["edge_id"].to_numpy(np.int64)
            st = st[owner.reindex(st).to_numpy() == k]
            need = pd.concat([need, pd.DataFrame({"edge_id": st, "fold": k})], ignore_index=True)
        need = need.drop_duplicates("edge_id")
    rec["n_missing"] = int(len(miss))
    rec["need_per_fold"] = {int(k): int(v) for k, v in need["fold"].value_counts().sort_index().items()}
    EMBED.mkdir(parents=True, exist_ok=True)
    need.to_parquet(EMBED / f"needed_iter{a.iter}.parquet", index=False)
    (EMBED / f"discover_iter{a.iter}.json").write_text(json.dumps(rec, indent=1, default=float), encoding="utf-8")
    print(f"[discover] iter {a.iter}: {len(miss):,} missing edges; request per fold {rec['need_per_fold']}")


def cmd_export(a):
    import torch
    torch.set_num_threads(a.threads)
    from ringshield.expand.cross_score import CrossScorer
    need = pd.read_parquet(a.needed)
    if a.folds:
        need = need[need["fold"].isin(a.folds)]
    cs = CrossScorer.for_embedding(R1_RUN_DIR, EMBED, device=torch.device("cpu"))
    a_ = cs.args
    print(f"[export] batch {getattr(a_, 'batch_size', None)} neigh {getattr(a_, 'num_neighs', getattr(a_, 'num_neighbors', None))} "
          f"window {getattr(a_, 'window_s', None)} folds {cs.folds} device {cs.device} threads {torch.get_num_threads()}", flush=True)
    t0 = time.time()
    done = cs.embed(need)
    print(f"[export] {done} in {time.time() - t0:.0f}s")


def cmd_check(a):
    rows = []
    owner = pd.read_parquet(XS / "cross_scores_train.parquet", columns=["edge_id", "fold"]).set_index("edge_id")["fold"]
    for k in range(5):
        p = EMBED / f"embeddings_fold{k}.parquet"
        if not p.exists():
            continue
        new = pd.read_parquet(p).set_index("edge_id")
        old = pd.read_parquet(XS / f"embeddings_fold{k}.parquet").set_index("edge_id")
        old = old[owner.reindex(old.index).to_numpy() == k]
        ids = old.index.intersection(new.index)
        cols = [c for c in old.columns if c.startswith("emb_")]
        A, B = old.loc[ids, cols].to_numpy(np.float64), new.loc[ids, cols].to_numpy(np.float64)
        d = np.abs(A - B)
        cos = (A * B).sum(1) / (np.linalg.norm(A, axis=1) * np.linalg.norm(B, axis=1) + 1e-12)
        rows.append({"fold": k, "n_stored_owner": int(len(old)), "n_compared": int(len(ids)),
                     "max_abs_diff": float(d.max()), "median_abs_diff": float(np.median(d)),
                     "median_cosine": float(np.median(cos)), "min_cosine": float(cos.min()),
                     "pass": bool(np.median(cos) >= 0.999)})
        print(rows[-1])
    pd.DataFrame(rows).to_csv(EMBED / "check.csv", index=False)


# ----------------------------------------------------------------------------------- features
def ring_features(rings, se, ctx) -> pd.DataFrame:
    sq = pd.Series(ctx.score_quantile, index=ctx.idx.edge_id)
    raw = se.set_index("edge_id")["score_raw"]
    amt = pd.Series(np.asarray(ctx.idx.amount, float), index=ctx.idx.edge_id)
    rows = []
    for r in rings:
        me = np.asarray(r.member_edges, np.int64)
        q = sq.reindex(me).to_numpy(float)
        am = np.log1p(np.clip(amt.reindex(me).to_numpy(float), 0, None))
        pr = np.asarray([p for p in (r.expanded_edge_probs or []) if p == p], float)
        tp = list(r.topology_probs) if r.topology_probs is not None else [np.nan] * 8
        n_seed, n_exp = len(r.seed_edges), len(r.expanded_edges)
        rows.append({"n_members": r.n_members, "n_edges": r.n_edges, "density": r.density,
                     "n_seed": n_seed, "seed_share": n_seed / max(n_seed + n_exp, 1),
                     "q_mean": np.nanmean(q), "q_max": np.nanmax(q), "q_min": np.nanmin(q), "q_std": np.nanstd(q),
                     "duration_hours": r.duration_hours, "log_amt_mean": am.mean(), "log_amt_std": am.std(),
                     "log_amt_range": am.max() - am.min(), "conservation_closure": r.conservation_closure,
                     **{f"topo_{i}": v for i, v in enumerate(tp[:8])},
                     "n_source": len(r.source_accounts), "n_sink": len(r.sink_accounts), "n_mule": len(r.mule_accounts),
                     "n_currencies": getattr(r, "n_currencies", 0),
                     "exp_prob_mean": pr.mean() if len(pr) else 0.0, "exp_prob_min": pr.min() if len(pr) else 0.0,
                     "exp_prob_count": len(pr), "confidence": r.confidence, "max_edge_prob": r.max_edge_prob,
                     "mean_raw_score": float(np.nanmean(raw.reindex(me).to_numpy(float)))})
    return pd.DataFrame(rows)


FEATURES_ALL = None   # set in fit from the frame (every column but bookkeeping)
BOOK = {"label", "ring_index", "mean_raw_score"}


def cmd_candidates(a):
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    from ringshield.rings import write_rings_parquet
    policy, affinity = Policy.load(POLICY), Affinity.load(AFFINITY)
    r3, r4 = cells(a.seed)
    out = OUT / "candidates" / f"{a.split}{a.tag}" / f"seed{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    if a.split == "train":
        from evaluation.ring_metrics import match_rings
        from ringshield.truth import load_ground_truth, split_window
        store = exported_store()
        rec = RecordingStore(store, store.dim)
        se, ctx, mask, fold_rows, cross, pdir = load_train(rec)
        rings, trajs = generate(se, ctx, mask, r3, r4, policy, affinity)
        assert not rec.missing, f"{len(rec.missing)} train edges without an exported embedding: run another closure iteration"
        days = (se.set_index("edge_id")["timestamp"] - 10) // 86400
        assert all(int(days.loc[r.member_edges].max()) <= 5 for r in rings), "a train candidate has an edge after day 5"
        truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *split_window(pdir / "amlworld_train.parquet"),
                                     "test_visible", verbose=False)
        matches, _, _ = match_rings([r.member_set for r in rings], truth, 0.5)
        label = np.zeros(len(rings), np.int64)
        for m in matches:
            label[m.pred_idx] = 1
        owner = cross.set_index("edge_id")["fold"]
        n_cross = sum(1 for t in trajs if len({int(owner.loc[e]) for e, *_ in t["adds"]} |
                                                  {int(owner.loc[e]) for e in t.get("seeds", [])}) > 1)
        meta = {"n_truth_train": len(truth), "n_pos": int(label.sum()), "fold_seed_rows": fold_rows,
                "n_trajectories": len(trajs), "n_trajectories_crossing_folds": int(n_cross)}
    else:
        from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
        se, ctx, pdir = load_eval_split(a.split, a.seed)
        mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), a.k)
        rings, trajs = generate(se, ctx, mask, r3, r4, policy, affinity)
        label = None
        meta = {"n_seeds": int(mask.sum())}
        if a.split == "val":
            truth, pat = val_truth(pdir)
            meta["val_unfiltered"] = val_f1(rings, truth, pat)
    feats = ring_features(rings, se, ctx)
    feats.insert(0, "ring_index", np.arange(len(rings)))
    if label is not None:
        feats["label"] = label
    feats.to_parquet(out / "features.parquet", index=False)
    write_rings_parquet(rings, out / "rings.parquet")
    meta.update({"split": a.split, "seed": a.seed, "k_pct": a.k if a.split != "train" else K_M1, "n_rings": len(rings),
                 "r3_cell": r3, "r4_cell": r4, "seconds": round(time.time() - t0, 1), "created_utc": now()})
    (out / "meta.json").write_text(json.dumps(meta, indent=1, default=float), encoding="utf-8")
    print(f"[candidates] {a.split} seed {a.seed}: {len(rings)} rings ({meta['seconds']}s) {meta.get('val_unfiltered', '')}"
          + (f" positives {meta['n_pos']}" if a.split == "train" else ""))


def cmd_refgen(a):
    """Sanity: this generator at k on val/test reproduces REF's val grid row / test rings."""
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    from ringshield.rings import write_rings_parquet
    r3, r4 = cells(a.seed)
    se, ctx, pdir = load_eval_split(a.split, a.seed)
    mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), a.k)
    rings, _ = generate(se, ctx, mask, r3, r4, Policy.load(POLICY), Affinity.load(AFFINITY), with_probs=False)
    out = OUT / "refgen" / f"{a.split}_k{a.k:.2f}_seed{a.seed}"
    out.mkdir(parents=True, exist_ok=True)
    write_rings_parquet(rings, out / "rings.parquet")
    res = {"n_rings": len(rings)}
    if a.split == "val":
        truth, pat = val_truth(pdir)
        res.update(val_f1(rings, truth, pat))
        ref = yaml.safe_load(Path(str(R4_CFG).format(S=a.seed)).read_text(encoding="utf-8"))
        res["ref_val_ring_f1"] = ref["chosen"]["val_ring_f1"]
    (out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"[refgen] {a.split} k={a.k} seed {a.seed}: {res}")


# ----------------------------------------------------------------------------------- fit / select
def select(rings_val, scores, grid, truth, pat, keep_ge=True):
    rows = []
    for g in grid:
        keep = [r for r, s in zip(rings_val, scores) if s >= g]
        rows.append({"cut": g, **val_f1(keep, truth, pat)})
    best = max(rows, key=lambda r: r["ring_f1"])          # max() keeps the first of ties = first in grid order
    return best, rows


def cmd_fit(a):
    import lightgbm as lgb
    from ringshield.rings import read_rings_parquet
    S = a.seed
    tr = pd.read_parquet(OUT / "candidates" / "train" / "seed1" / "features.parquet")   # one cell for seeds 1-5 -> one train set
    va = pd.read_parquet(OUT / "candidates" / "val" / f"seed{S}" / "features.parquet")
    rings_val = read_rings_parquet(OUT / "candidates" / "val" / f"seed{S}" / "rings.parquet")
    from contract.make_scored_edges import load_paths
    truth, pat = val_truth(load_paths()["processed_dir"])
    allf = [c for c in tr.columns if c not in BOOK]
    variants = {"M1-V": [c for c in allf if c not in IS_FEATURES], "M1-V-IS": allf}
    res = {"seed": S, "created_utc": now(), "lgbm_params": LGBM_PARAMS, "n_train": len(tr), "n_train_pos": int(tr["label"].sum()),
           "n_val_candidates": len(va), "val_unfiltered": val_f1(rings_val, truth, pat), "variants": {}}
    if res["n_train_pos"] < 50:
        print(f"[fit] STOP: only {res['n_train_pos']} positive training candidates (< 50)")
    for name, cols in variants.items():
        clf = lgb.LGBMClassifier(random_state=S, **LGBM_PARAMS).fit(tr[cols], tr["label"])
        p = clf.predict_proba(va[cols])[:, 1]
        best, grid = select(rings_val, p, T_GRID, truth, pat)
        res["variants"][name] = {"features": cols, "chosen_t": best["cut"], "val_at_chosen": best, "val_grid": grid}
        out = OUT / "fit" / f"seed{S}"
        out.mkdir(parents=True, exist_ok=True)
        clf.booster_.save_model(str(out / f"{name}.txt"))
        print(f"[fit] {name}: chosen t {best['cut']} val F1 {best['ring_f1']:.4f} (rings {best['n_rings']}, accounts {best['n_accounts']})")
    s = va["mean_raw_score"].to_numpy(float)
    cuts = [float(np.quantile(s, q)) for q in Q_GRID]
    best, grid = select(rings_val, s, cuts, truth, pat)
    best["q"] = Q_GRID[cuts.index(best["cut"])]
    res["variants"]["M1-S"] = {"chosen_q": best["q"], "chosen_c": best["cut"], "val_at_chosen": best, "val_grid": grid}
    print(f"[fit] M1-S: chosen q {best['q']} val F1 {best['ring_f1']:.4f}")
    ref = yaml.safe_load(Path(str(R4_CFG).format(S=S)).read_text(encoding="utf-8"))
    res["ref_val_ring_f1"] = float(ref["chosen"]["val_ring_f1"])
    res["gate_pass"] = bool(res["variants"]["M1-V"]["val_at_chosen"]["ring_f1"] > res["ref_val_ring_f1"])
    print(f"[fit] REF val F1 {res['ref_val_ring_f1']:.4f} -> gate {'PASS' if res['gate_pass'] else 'FAIL'}")
    (OUT / "fit" / f"seed{S}" / "fit.json").write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")


# ----------------------------------------------------------------------------------- test (once)
CHOSEN = OUT / "chosen_cells.json"
ARMS = ("M1-V", "M1-V-IS", "M1-S", "full020")
TEST = OUT / "test"
SEEDS = (1, 2, 3, 4, 5)


def cmd_chosen(a):
    """Per-seed validation choices (prereg §2: 'Chosen per seed'), frozen before any test scoring."""
    assert not CHOSEN.exists(), f"{CHOSEN} exists: chosen cells are written once"
    out = {"created_utc": now(), "rule": "threshold chosen per seed on validation ring-F1 (prereg §2); grid t 0.1..0.9 frozen",
           "seeds": {}}
    for S in SEEDS:
        r = json.loads((OUT / "fit" / f"seed{S}" / "fit.json").read_text(encoding="utf-8"))
        out["seeds"][S] = {"M1-V_t": r["variants"]["M1-V"]["chosen_t"], "M1-V-IS_t": r["variants"]["M1-V-IS"]["chosen_t"],
                           "M1-S_q": r["variants"]["M1-S"]["chosen_q"], "M1-S_c": r["variants"]["M1-S"]["chosen_c"],
                           "val": {v: r["variants"][v]["val_at_chosen"] for v in ("M1-V", "M1-V-IS", "M1-S")},
                           "val_unfiltered_020": r["val_unfiltered"], "ref_val_ring_f1": r["ref_val_ring_f1"],
                           "gate_pass": r["gate_pass"]}
    CHOSEN.write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    print(json.dumps({S: {k: v for k, v in d.items() if k.endswith(("_t", "_q"))} for S, d in out["seeds"].items()}))


def verifier_probs(S, feats, name="M1-V", model_dir=None):
    import lightgbm as lgb
    b = lgb.Booster(model_file=str((model_dir or OUT / "fit" / f"seed{S}") / f"{name}.txt"))
    return b.predict(feats[b.feature_name()])


def cmd_apply(a):
    ch = json.loads(CHOSEN.read_text(encoding="utf-8"))["seeds"]
    for S in SEEDS:
        c = ch[str(S)]
        d = OUT / "candidates" / "test" / f"seed{S}"
        feats, rings = pd.read_parquet(d / "features.parquet"), pd.read_parquet(d / "rings.parquet")
        assert len(feats) == len(rings) and (feats["ring_index"].to_numpy() == np.arange(len(rings))).all()
        keep = {"M1-V": verifier_probs(S, feats, "M1-V") >= c["M1-V_t"],
                "M1-V-IS": verifier_probs(S, feats, "M1-V-IS") >= c["M1-V-IS_t"],
                "M1-S": feats["mean_raw_score"].to_numpy(float) >= c["M1-S_c"],
                "full020": np.ones(len(rings), bool)}
        for arm, k in keep.items():
            o = TEST / arm / f"seed{S}"
            o.mkdir(parents=True, exist_ok=True)
            rings.iloc[np.flatnonzero(k)].to_parquet(o / "rings.parquet", index=False)
            print(f"[apply] seed {S} {arm}: {int(k.sum())}/{len(rings)} rings kept")


def arm_stats(rings, se, W, truth, ring_id_of, mask_own, mask_ref, b0):
    from evaluation.ring_stats import metrics_from_evidence, ring_evidence
    from ringshield.evaluate import restrict_rings
    from ringshield.expand.run_expand import expansion_vs_truth
    rs = restrict_rings(rings, se, W)
    in_win = set(se.loc[W.mask(se["timestamp"].to_numpy()), "edge_id"].tolist())
    rid = ring_id_of
    touched = {int(rid.get(e, -1)) for r in rings for e in r.member_edges if e in in_win} & set(truth)
    ev = expansion_vs_truth(rings, b0, se, ring_id_of, truth, W)
    q_own = metrics_from_evidence(ring_evidence(rings, se, truth, W, method="m", seed=0, seed_mask=mask_own, causal=True))
    q_ref = metrics_from_evidence(ring_evidence(rings, se, truth, W, method="m", seed=0, seed_mask=mask_ref, causal=True))
    return {"n_rings": len(rings), "n_rings_in_window": len(rs),
            "n_accounts": len(set().union(*[set(r.members) for r in rings])) if rings else 0,
            "n_accounts_in_window": len(set().union(*rs)) if rs else 0, "rings_touched": len(touched),
            "amp": ev["expanded_member_precision"], "n_added_edges": ev["n_expanded_edges_in_window"],
            "quiet_found_own": q_own["n_quiet_found"], "quiet_total_own": q_own["n_quiet"],
            "quiet_found_ref": q_ref["n_quiet_found"], "quiet_total_ref": q_ref["n_quiet"]}


def cmd_report(a, arms_dirs=None, out_name="m1_test_arms"):
    """Workload, rings touched, added-member precision and quiet-member recall per arm and seed (test, primary)."""
    from contract.make_scored_edges import load_paths
    from evaluation.window_budget import cc_rings_from_mask
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.rings import read_rings_parquet
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    arms_dirs = arms_dirs or {"REF": (EXP / "R4_partition_ringfold" / "average", 0.10),
                              **{arm: (TEST / arm, K_M1) for arm in ARMS}}
    rows = []
    for S in SEEDS:
        se = build_scored_edges(R1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
        sc = se[SELECT_COL].to_numpy(float)
        masks = {k: seed_mask_for_pct(sc, k) for k in (0.10, K_M1)}
        b0 = {k: cc_rings_from_mask(se, m, 3) for k, m in masks.items()}
        for arm, (root, k) in arms_dirs.items():
            rings = read_rings_parquet(root / f"seed{S}" / "rings.parquet")
            rows.append({"arm": arm, "seed": S, "k_pct": k,
                         **arm_stats(rings, se, W, truth, ring_id_of, masks[k], masks[0.10], b0[k])})
            print({k_: v for k_, v in rows[-1].items() if not k_.startswith("quiet")}, flush=True)
    df = pd.DataFrame(rows)
    g = df.groupby("arm")
    summ = {}
    for arm, d in g:
        summ[arm] = {"n_rings": d["n_rings"].mean(), "n_rings_in_window": d["n_rings_in_window"].mean(),
                     "n_accounts": d["n_accounts"].mean(), "n_accounts_in_window": d["n_accounts_in_window"].mean(),
                     "rings_touched": d["rings_touched"].mean(),
                     "amp_pooled": float((d["amp"].fillna(0) * d["n_added_edges"]).sum() / max(d["n_added_edges"].sum(), 1)),
                     "n_added_edges": d["n_added_edges"].mean(),
                     "quiet_member_recall_own_seeds": float(d["quiet_found_own"].sum() / d["quiet_total_own"].sum()),
                     "quiet_member_recall_ref_seeds": float(d["quiet_found_ref"].sum() / d["quiet_total_ref"].sum())}
    tab = REPO_ROOT / "results" / "tables"
    df.to_csv(tab / f"{out_name}_per_seed.csv", index=False)
    (tab / f"{out_name}.json").write_text(json.dumps({"created_utc": now(), "window": "primary", "scope": "test_visible",
        "amp_definition": "expansion_vs_truth vs B0 of the same seed set (0.2 % for M1 arms, 0.1 % for REF), pooled over seeds",
        "quiet_definition": "r9 ring_evidence; own = the arm's own seed set, ref = the 0.1 % seed set",
        "touched_definition": "truth rings with >= 1 in-window member edge in the arm's output rings",
        "summary": summ}, indent=1, default=float), encoding="utf-8")
    print(pd.DataFrame(summ).T.round(4).to_string())


POSTHOC = OUT / "posthoc"


def _fit_variant(S, tr, cols, model_dir):
    import lightgbm as lgb
    model_dir.mkdir(parents=True, exist_ok=True)
    clf = lgb.LGBMClassifier(random_state=S, **LGBM_PARAMS).fit(tr[cols], tr["label"])
    clf.booster_.save_model(str(model_dir / "M1-V.txt"))


def cmd_posthoc(a):
    """POST HOC (author request after the primary result was written; outside the Holm family).
    a: the seed-specific M1-V verifier on the 0.1 % REF candidates, t chosen on val from T_GRID.
    b: M1-V at fixed t in {0.02, 0.05} (sensitivity below the frozen grid's edge), val and test.
    c: M1-V refit without train candidates that mix owner folds (seed + expanded edges in >1 fold),
       t chosen on val from T_GRID."""
    assert (REPO_ROOT / "results" / "tables" / "m1_primary.json").exists(), "primary result not on disk"
    from contract.make_scored_edges import load_paths
    from ringshield.rings import read_rings_parquet
    truth, pat = val_truth(load_paths()["processed_dir"])
    tab = REPO_ROOT / "results" / "tables"
    rows, arms = [], {}
    if a.part == "c":
        tr = pd.read_parquet(OUT / "candidates" / "train" / "seed1" / "features.parquet")
        rings_tr = read_rings_parquet(OUT / "candidates" / "train" / "seed1" / "rings.parquet")
        owner = pd.read_parquet(XS / "cross_scores_train.parquet", columns=["edge_id", "fold"]).set_index("edge_id")["fold"]
        mixed = np.array([owner.reindex(list(r.seed_edges) + list(r.expanded_edges)).nunique() > 1 for r in rings_tr])
        tr_c = tr[~mixed].reset_index(drop=True)
        cols = json.loads((OUT / "fit" / "seed1" / "fit.json").read_text(encoding="utf-8"))["variants"]["M1-V"]["features"]
        info = {"n_train": len(tr), "n_dropped_mixed_fold": int(mixed.sum()), "n_pos_dropped": int(tr["label"][mixed].sum()),
                "n_train_kept": len(tr_c), "n_pos_kept": int(tr_c["label"].sum()),
                "rule": "drop a train candidate if its seed and expanded edges have more than one owner fold"}
        print(f"[posthoc c] {info}")
    for S in SEEDS:
        if a.part == "a":
            vd, td = OUT / "candidates" / "val_k010" / f"seed{S}", OUT / "candidates" / "test_k010" / f"seed{S}"
            model_dir, grid = OUT / "fit" / f"seed{S}", T_GRID
        elif a.part == "b":
            vd, td = OUT / "candidates" / "val" / f"seed{S}", OUT / "candidates" / "test" / f"seed{S}"
            model_dir, grid = OUT / "fit" / f"seed{S}", (0.02, 0.05)
        else:
            vd, td = OUT / "candidates" / "val" / f"seed{S}", OUT / "candidates" / "test" / f"seed{S}"
            model_dir, grid = POSTHOC / "c" / "fit" / f"seed{S}", T_GRID
            _fit_variant(S, tr_c, cols, model_dir)
        fv, ft = pd.read_parquet(vd / "features.parquet"), pd.read_parquet(td / "features.parquet")
        rv = read_rings_parquet(vd / "rings.parquet")
        rt = pd.read_parquet(td / "rings.parquet")
        pv, pt = verifier_probs(S, fv, "M1-V", model_dir), verifier_probs(S, ft, "M1-V", model_dir)
        if a.part == "b":
            for t in grid:
                rows.append({"seed": S, "t": t, **{f"val_{k}": v for k, v in val_f1([r for r, x in zip(rv, pv) if x >= t], truth, pat).items()}})
                o = POSTHOC / "b" / f"t{t:.2f}" / f"seed{S}"; o.mkdir(parents=True, exist_ok=True)
                rt.iloc[np.flatnonzero(pt >= t)].to_parquet(o / "rings.parquet", index=False)
                arms[f"t{t:.2f}"] = POSTHOC / "b" / f"t{t:.2f}"
        else:
            best, g = select(rv, pv, grid, truth, pat)
            rows.append({"seed": S, "chosen_t": best["cut"], **{f"val_{k}": v for k, v in best.items() if k != "cut"},
                         "val_unfiltered_f1": val_f1(rv, truth, pat)["ring_f1"]})
            o = POSTHOC / a.part / "rings" / f"seed{S}"; o.mkdir(parents=True, exist_ok=True)
            rt.iloc[np.flatnonzero(pt >= best["cut"])].to_parquet(o / "rings.parquet", index=False)
            arms[a.part] = POSTHOC / a.part / "rings"
    df = pd.DataFrame(rows)
    df.to_csv(tab / f"m1_posthoc_{a.part}_val.csv", index=False)
    meta = {"label": "POST HOC, outside the Holm family", "part": a.part, "created_utc": now(), "arms": {k: str(v) for k, v in arms.items()}}
    if a.part == "c":
        meta["train"] = info
    (POSTHOC / a.part).mkdir(parents=True, exist_ok=True)
    (POSTHOC / a.part / "meta.json").write_text(json.dumps(meta, indent=1, default=float), encoding="utf-8")
    print(df.round(4).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refgen"); p.add_argument("--split", choices=["val", "test"], required=True)
    p.add_argument("--seed", type=int, required=True); p.add_argument("--k", type=float, default=0.1)
    p = sub.add_parser("discover"); p.add_argument("--iter", type=int, required=True)
    p = sub.add_parser("export"); p.add_argument("--needed", type=Path, required=True)
    p.add_argument("--folds", type=int, nargs="*"); p.add_argument("--threads", type=int, default=16)
    sub.add_parser("check")
    p = sub.add_parser("candidates"); p.add_argument("--split", choices=["train", "val", "test"], required=True)
    p.add_argument("--seed", type=int, required=True); p.add_argument("--k", type=float, default=K_M1)
    p.add_argument("--tag", default="", help="output dir suffix (post hoc: _k010)")
    sub.add_parser("chosen"); sub.add_parser("apply"); sub.add_parser("report")
    p = sub.add_parser("posthoc"); p.add_argument("--part", choices=["a", "b", "c"], required=True)
    p = sub.add_parser("fit"); p.add_argument("--seed", type=int, required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    {"refgen": cmd_refgen, "discover": cmd_discover, "export": cmd_export, "check": cmd_check,
     "candidates": cmd_candidates, "fit": cmd_fit, "chosen": cmd_chosen,
     "apply": cmd_apply, "report": cmd_report, "posthoc": cmd_posthoc}[a.cmd](a)


if __name__ == "__main__":
    main()
