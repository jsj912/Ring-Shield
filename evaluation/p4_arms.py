# -*- coding: utf-8 -*-
"""P4 `full` and `full-structural` arms. CONTROLLED DIAGNOSTIC WITH LABEL-DERIVED SEEDS.

    RINGSHIELD_PATHS=configs/paths_hi_medium.yaml python evaluation/p4_arms.py \
        --dataset HI-Medium --stage full --eval-window configs/eval_window_hi_medium.yaml \
        --r1-dir experiments_hi_medium/R1_gine_causal_c1prime \
        --policy-dir experiments_hi_medium/R3_expansion/policy_proposed \
        --affinity-dir experiments_hi_medium/R4_partition/affinity \
        --delta-t-h 48 --p-min 0.7 --cut 0.3 --min-size 3

**Every number here carries the seed-quality sentence** (Amendment 10): P4's synthetic seeds are
0.93 precise, against 0.29 for HI-Medium's real training seeds, so P4 measures containment at
matched, HI-Small-quality seeds and forecasts neither dataset's real pipeline.

**And `full` matches seed quality but not detector quality** (Amendment 10 item 1): the policy's
features include `score_quantile`, `dead_region`, `cos_anchor` and `cos_mean_included`, all derived
from each dataset's own detector, so `full` is biased against HI-Medium, whose detector is weaker.
`--stage full-structural` is the arm that removes that confound, by using policy and affinity
re-trained without the detector and embedding feature groups.

The seed draws are **bit-identical to the B0 arm's**: they are drawn on the same window-restricted
frame, in the same row order, from the same `default_rng(--rng + draw)`, by the same `draw_seeds`
from `evaluation.p4_matched_seeds`. The drawn EdgeIDs are then mapped into the whole-split frame
that the expansion needs, so the only thing that differs between arms is the aggregator.

`--draw-first/--draw-last` run a slice of the draws, so a long arm can be executed in chunks and
the per-draw CSVs concatenated; the reported CI is always taken over the full set of draws present.
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

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.p4_matched_seeds import PRECISION, RECALL, boot_ci, draw_seeds, window_frame  # noqa: E402
from evaluation.ring_metrics import evaluate_rings, match_rings  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import aggregate_cc  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

STRATA = [("2", 2, 2), ("3-5", 3, 5), ("6-10", 6, 10), (">10", 11, 10 ** 9)]
SEED_QUALITY_NOTE = (
    "CONTROLLED DIAGNOSTIC WITH LABEL-DERIVED SEEDS. P4's synthetic seeds are 0.93 precise; "
    "HI-Medium's real training seeds are 0.29 precise (per-fold 0.1 % cut of the C1' cross-scores, "
    "precision 0.2903 / recall 0.3195). P4 measures containment at matched, HI-Small-quality seeds "
    "and does not forecast the real pipeline on either dataset.")


def strata_of(truth: dict) -> dict:
    """ring_id -> stratum label, by visible-member count (Amendment 9)."""
    out = {}
    for r, members in truth.items():
        n = len(members)
        for name, lo, hi in STRATA:
            if lo <= n <= hi:
                out[r] = name
                break
    return out


def metrics_for(member_sets, truth, pat, strat, rings, df_win, W, n_truth):
    """Pooled metrics plus the per-stratum matched share, over the same matching."""
    m = evaluate_rings(member_sets, truth, 0.5, pat)
    matched = {x.truth_id for x in match_rings(member_sets, truth, 0.5)[0]}
    big = {t for t, v in truth.items() if len(v) >= 3}
    kl = classify(rings, df_win.rename(columns={"is_laundering": "y"}), truth, pat, W)
    row = {"n_rings": len(member_sets), "ring_precision": m.ring_precision,
           "ring_recall": m.ring_recall, "ring_f1": m.ring_f1,
           "ring_recall_ge3": len(matched & big) / len(big) if big else np.nan,
           "under_covered": int((kl["klass"] == "c_under_covered").sum()),
           "under_covered_share": int((kl["klass"] == "c_under_covered").sum()) / n_truth,
           "class_b": int((kl["klass"] == "b_untouched").sum()),
           "class_b_share": int((kl["klass"] == "b_untouched").sum()) / n_truth,
           "n_truth_rings": n_truth}
    for name, _, _ in STRATA:
        ids = {t for t, s in strat.items() if s == name}
        row[f"recall_{name}"] = (len(matched & ids) / len(ids)) if ids else np.nan
        row[f"n_truth_{name}"] = len(ids)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--stage", choices=["b0", "full", "full-structural"], required=True)
    ap.add_argument("--eval-window", type=Path, required=True)
    ap.add_argument("--min-size", type=int, required=True, help="the dataset's VAL-CHOSEN value")
    ap.add_argument("--r1-dir", type=Path, required=True)
    ap.add_argument("--policy-dir", type=Path, default=None)
    ap.add_argument("--affinity-dir", type=Path, default=None)
    ap.add_argument("--delta-t-h", type=float, default=None)
    ap.add_argument("--p-min", type=float, default=None)
    ap.add_argument("--cut", type=float, default=None)
    ap.add_argument("--cluster-method", default="average")
    ap.add_argument("--cluster-seed", type=int, default=0)
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--model-id", default="gine_causal")
    ap.add_argument("--seed", type=int, default=1, help="detector seed")
    ap.add_argument("--draws", type=int, default=10)
    ap.add_argument("--draw-first", type=int, default=0)
    ap.add_argument("--draw-last", type=int, default=None)
    ap.add_argument("--rng", type=int, default=20261003)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables")
    a = ap.parse_args(argv)
    if a.stage != "b0":
        for need in ("policy_dir", "affinity_dir", "delta_t_h", "p_min", "cut"):
            assert getattr(a, need) is not None, f"--{need.replace('_', '-')} is required for {a.stage}"
    t_start = time.time()
    pdir = load_paths()["processed_dir"]
    S = a.seed

    # ---- the window frame the B0 arm uses: the draws are made here, unchanged -------------------
    df_win, truth, pat, W = window_frame(pdir, a.eval_window)
    strat = strata_of(truth)
    n_truth = len(truth)
    print(f"[p4:{a.stage}] {a.dataset}: primary days {W.day_lo}-{W.day_hi}, {len(df_win):,} window "
          f"edges, {int(df_win['is_laundering'].sum()):,} illicit, {n_truth} in-scope rings, "
          f"min_size={a.min_size} (val-chosen)")
    print(f"[p4:{a.stage}] strata: " + ", ".join(
        f"{n} {sum(1 for v in strat.values() if v == n)}" for n, _, _ in STRATA))

    # ---- the whole-split frame the expansion needs ----------------------------------------------
    se = ctx = None
    policy = affinity = None
    if a.stage != "b0":
        sp = a.r1_dir / f"scores_test_seed{S}.parquet"
        assert sp.exists(), f"{sp} missing -- score the test split first"
        se = build_scored_edges(sp, "test", model_id=a.model_id, seed=S, processed_dir=pdir)
        emb = a.r1_dir / f"embeddings_test_seed{S}.parquet"
        assert emb.exists(), (f"{emb} missing -- the {a.stage} arm needs embeddings; "
                              "running without them would silently drop the policy's "
                              "largest feature group")
        ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_test.parquet",
                            embeddings_parquet=emb, checkpoint=a.r1_dir / f"model_best_seed{S}.pt")
        policy = Policy.load(a.policy_dir)
        affinity = Affinity.load(a.affinity_dir)
        # Affinity stores `features`, not `drop_groups`, so the dropped groups are derived from
        # which of its feature groups are absent.
        from ringshield.partition.pairs import FEATURE_GROUPS as PAIR_GROUPS
        aff_have = set(affinity.features)
        aff_dropped = sorted(g for g, cols in PAIR_GROUPS.items() if not (set(cols) & aff_have))
        print(f"[p4:{a.stage}] test split {len(se):,} edges, embeddings yes, "
              f"policy drop_groups={list(policy.drop_groups)}, "
              f"affinity dropped groups={aff_dropped}")
        if a.stage == "full-structural":
            want = {"detector", "embedding"}
            assert want <= set(policy.drop_groups), \
                f"full-structural needs a policy trained without {sorted(want)}, got {policy.drop_groups}"
            assert "embedding" in set(aff_dropped), \
                f"full-structural needs an affinity trained without embedding, got dropped={aff_dropped}"
        # position of each window edge within the whole-split frame, by edge_id
        pos_of = pd.Series(np.arange(len(se)), index=se["edge_id"].to_numpy())
        win_pos = pos_of.reindex(df_win["edge_id"].to_numpy()).to_numpy()
        assert not np.isnan(win_pos).any(), "a window edge is absent from the scored test split"
        win_pos = win_pos.astype(np.int64)

    last = a.draws - 1 if a.draw_last is None else a.draw_last
    rows = []
    for d in range(a.draw_first, last + 1):
        t0 = time.time()
        rng = np.random.default_rng(a.rng + d)
        mask_win, n_pos, n_neg, n_ill, pool = draw_seeds(df_win, rng)
        if a.stage == "b0":
            from ringshield.aggregators.cc import rings_from_masks
            rings = rings_from_masks(df_win, mask_win, None, a.min_size, None, conf_col="score_raw")
            member_sets = [r.member_set for r in rings]
        else:
            mask = np.zeros(len(se), dtype=bool)
            mask[win_pos[mask_win]] = True
            assert int(mask.sum()) == int(mask_win.sum()), "seed mask lost edges in the mapping"
            trajs = expand_all(se, mask, policy, ctx, delta_t_h=a.delta_t_h, p_floor=a.p_min)
            inc_pos, is_seed = included_from_trajectories(se, mask, trajs, a.p_min)
            comp = components_of(ctx.idx, inc_pos)
            P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
            lab = partition_labels(ctx, inc_pos, is_seed, comp, method=a.cluster_method, pairs=P,
                                   cut=a.cut, seed=a.cluster_seed, min_members=a.min_size)
            rings = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, a.min_size)
            member_sets = [r.member_set for r in rings]
        r = metrics_for(member_sets, truth, pat, strat, rings, df_win, W, n_truth)
        r.update({"dataset": a.dataset, "stage": a.stage, "draw": d, "min_size": a.min_size,
                  "n_seeds": int(mask_win.sum()), "n_seed_illicit": n_pos, "n_seed_licit": n_neg,
                  "seed_precision": n_pos / (n_pos + n_neg), "seed_recall": n_pos / n_ill,
                  "seconds": round(time.time() - t0, 1)})
        rows.append(r)
        print(f"  draw {d}: seeds {r['n_seeds']:,} (P {r['seed_precision']:.3f} R {r['seed_recall']:.3f})"
              f" -> rings {r['n_rings']:,} | recall {r['ring_recall']:.4f} | R>=3 "
              f"{r['ring_recall_ge3']:.4f} | under-cov {r['under_covered_share']:.4f} "
              f"| {r['seconds']:.0f}s", flush=True)

    g = pd.DataFrame(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    # "arm_" prefix: the b0 stage here is a REPRODUCTION of evaluation/p4_matched_seeds.py's table
    # (verified bit-identical on HI-Small draws 0-2), and must not overwrite that original.
    tag = f"arm_{a.stage}_{a.dataset}"
    suffix = "" if (a.draw_first == 0 and a.draw_last is None) else f"_d{a.draw_first}-{last}"
    p = a.out / f"v33_p4_{tag}{suffix}.csv"
    g.to_csv(p, index=False)

    print(f"\n== {a.dataset} {a.stage}, draws {a.draw_first}-{last} ==")
    print(f"   {SEED_QUALITY_NOTE}")
    for k in ("ring_recall", "ring_recall_ge3", "under_covered_share", "class_b_share",
              "ring_precision", "ring_f1"):
        m, lo, hi = boot_ci(g[k])
        print(f"  {k:22s} {m:.4f}  [{lo:.4f}, {hi:.4f}]")
    print("  -- stratified by visible members (Amendment 9) --")
    for name, _, _ in STRATA:
        m, lo, hi = boot_ci(g[f"recall_{name}"])
        print(f"  recall {name:5s} (n={int(g[f'n_truth_{name}'].iloc[0]):5d})  {m:.4f}  [{lo:.4f}, {hi:.4f}]")
    (a.out / f"v33_p4_{tag}{suffix}.json").write_text(json.dumps(
        {"dataset": a.dataset, "stage": a.stage, "draws": [a.draw_first, last],
         "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "seed_quality_note": SEED_QUALITY_NOTE,
         "params": {"min_size": a.min_size, "delta_t_h": a.delta_t_h, "p_min": a.p_min,
                    "cut": a.cut, "method": a.cluster_method, "scope": a.scope,
                    "recall_target": RECALL, "precision_target": PRECISION},
         "sources": {"r1_dir": str(a.r1_dir), "policy_dir": str(a.policy_dir),
                     "affinity_dir": str(a.affinity_dir)},
         "seconds": round(time.time() - t_start, 1)}, indent=2), encoding="utf-8")
    print(f"-> {p}")
    return g


if __name__ == "__main__":
    main()
