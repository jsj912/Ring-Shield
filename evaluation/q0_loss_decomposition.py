"""Q0: where the truth rings are lost (descriptive; tunes nothing).

    CUDA_VISIBLE_DEVICES="" python -m evaluation.q0_loss_decomposition

Shipped full pipeline (experiments/R4_partition/runs/average/seed1..5), HI-Small primary window
(test days 8-9), scope test_visible, Jaccard >= 0.5 one-to-one, min_size 3, seed budget 0.1 %
global quantile (the shipped seed mask, rebuilt from experiments/R1_gine_causal scores).

Each of the 174 truth rings goes to exactly one bucket, checked in this order:

  a   no in-window connected piece of >= 3 accounts (evaluation.component_scope.component_truth,
      min_members=3). Structural; identical for every seed. Rings in (a) that a seed still matches
      are counted separately as `a_matched` (min_size applies to the unrestricted prediction,
      FINDINGS B7/B9), but stay in (a).
  d   matched (scorer matching: restrict_rings + match_rings at 0.5).
  b   no in-window seed edge (shipped 0.1 % mask) has an endpoint among the ring's visible members
      (every member is quiet in the sense of evaluation.ring_stats.quiet_accounts).
  c   seed-touched and unmatched. With O = the window-restricted predictions that share >= 1
      account with the ring's visible members V, and P* = the member of O with the highest Jaccard
      (ties: larger intersection, then lower index):
        c1  O is empty (sub-flag c1_no_prediction), or none of the rules below applies;
        c2  J(P*) >= 0.5 but P* was taken by another truth ring in the one-to-one matching
            (sub-flag c2_one_to_one); or rule c3 does not apply and P* holds more outsiders
            than V has missing members: |P* - V| > |V - P*|;
        c3  at least two predictions in O each hold >= 2 members of V, and together they hold
            >= half of V (|union of their V-members| >= |V| / 2).
      Order inside c: c1 (O empty) -> c2 (one-to-one) -> c3 -> c2 (outsiders > missing) -> c1.
      c2 is further flagged `c2_other_ring` when P*'s outsiders include a visible member of
      another truth ring of the window (merged with a ring) vs only non-ring accounts (noise).

Outputs results/tables/q0_buckets_per_ring.csv (seed x ring), q0_buckets.csv (counts per seed and
mean), q0_buckets_by_pattern.csv, q0_buckets.json (definitions, input sha256, checks).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

CKPT = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"  # read-only; not in this checkout
BUCKETS = ["a", "b", "c1", "c2", "c3", "d"]


# ----------------------------------------------------------------------------- pure rules
def classify_c(V: set, preds: list[set], matched_preds: set[int], other_ring_accounts: set) -> dict:
    """Sub-bucket of a seed-touched, unmatched ring with visible members V.

    preds: window-restricted predictions (account sets); matched_preds: indices of predictions
    used by the one-to-one matching. Returns {"bucket", flags...}."""
    O = [i for i, P in enumerate(preds) if P & V]
    out = {"c1_no_prediction": False, "c2_one_to_one": False, "c2_other_ring": False,
           "best_jaccard": 0.0, "best_coverage": 0.0, "best_purity": 0.0, "n_overlapping": len(O)}
    if not O:
        out.update(bucket="c1", c1_no_prediction=True)
        return out

    def key(i):
        P = preds[i]
        inter = len(P & V)
        return (inter / len(P | V), inter, -i)

    best = max(O, key=key)
    P = preds[best]
    inter = len(P & V)
    out.update(best_jaccard=inter / len(P | V), best_coverage=inter / len(V), best_purity=inter / len(P))
    outsiders = P - V
    out["c2_other_ring"] = bool(outsiders & other_ring_accounts)
    if out["best_jaccard"] >= 0.5 and best in matched_preds:
        out.update(bucket="c2", c2_one_to_one=True)
        return out
    frag = [i for i in O if len(preds[i] & V) >= 2]
    if len(frag) >= 2 and 2 * len(set().union(*(preds[i] & V for i in frag))) >= len(V):
        out["bucket"] = "c3"
        return out
    out["bucket"] = "c2" if len(outsiders) > len(V - P) else "c1"
    return out


def assign(V: set, has_ge3_piece: bool, matched: bool, seed_touched: bool, preds, matched_preds,
           other_ring_accounts) -> dict:
    """Bucket for one truth ring (order a -> d -> b -> c)."""
    if not has_ge3_piece:
        return {"bucket": "a", "a_matched": matched}
    if matched:
        return {"bucket": "d"}
    if not seed_touched:
        return {"bucket": "b"}
    return classify_c(V, preds, matched_preds, other_ring_accounts)


# ----------------------------------------------------------------------------- driver
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def build_full_rings(S: int, split: str, pdir: Path):
    """Shipped full-pipeline rings for one detector seed and split, rebuilt by the exact route of
    evaluation/unmatched_rings.py (R1 scores, R3 proposed policy and chosen cell, R4 affinity and
    chosen cut). Used for the validation window, for which no rings file is shipped."""
    import yaml
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.aggregators.expand import expand_all
    from ringshield.aggregators.full import component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters
    from ringshield.expand.context import build_context
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    from ringshield.partition.pairs import components_of
    from ringshield.scored_edges import build_scored_edges
    R1, R3, R4 = (REPO_ROOT / "experiments" / d for d in ("R1_gine_causal", "R3_expansion", "R4_partition"))
    r3 = yaml.safe_load((R3 / "runs/proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    r4 = yaml.safe_load((R4 / "runs/average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    k_pct, min_size = float(r3["seed_frac_pct"]), int(r3["min_size"])
    se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
    emb = R1 / f"embeddings_{split}_seed{S}.parquet"
    if not emb.exists():                       # only seed 1 is in this checkout; RS-e2e copy is read-only
        emb = CKPT / f"embeddings_{split}_seed{S}.parquet"
    assert emb.exists(), emb
    ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet",
                        embeddings_parquet=emb if emb.exists() else None, checkpoint=CKPT / f"model_best_seed{S}.pt")
    mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct)
    trajs = expand_all(se, mask, Policy.load(R3 / "policy_proposed"), ctx, delta_t_h=float(r3["delta_t_h"]), p_floor=float(r3["p_min"]))
    inc_pos, is_seed = included_from_trajectories(se, mask, trajs, float(r3["p_min"]))
    comp = components_of(ctx.idx, inc_pos)
    P = component_pairs(ctx, inc_pos, is_seed, comp, Affinity.load(R4 / "affinity"))
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=min_size,
                           **{k: r4[k] for k in ("cut", "threshold", "gap_h", "resolution") if k in r4})
    return rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, min_size), se, mask


def a_detail(V, tid, comp1, preds, rings_kept, matches_by_truth, W_in_edges):
    """How a bucket-a ring looks and, if matched, how it matched."""
    pieces = [len(v) for k, v in comp1.items() if k[0] == tid]
    d = {"a_n_pieces": len(pieces), "a_max_piece": max(pieces) if pieces else 0}
    m = matches_by_truth.get(tid)
    if m is None:
        return d
    P = preds[m.pred_idx]
    r = rings_kept[m.pred_idx]
    d.update(a_pred_inwin_size=len(P), a_pred_full_size=len(set(r.members)), a_jaccard=len(P & V) / len(P | V))
    if len(P) < 3:
        d["a_how"] = "in-window prediction < 3 accounts; min_size met by out-of-window members"
    elif d["a_n_pieces"] >= 2 and sum(1 for k, v in comp1.items() if k[0] == tid and v & P) >= 2:
        d["a_how"] = "prediction >= 3 accounts spanning several < 3 pieces"
    else:
        d["a_how"] = "prediction >= 3 accounts, other"
    return d


def main(argv=None):
    from evaluation.component_scope import component_truth
    from evaluation.ring_metrics import match_rings
    from evaluation.ring_stats import quiet_accounts
    from evaluation.step9_tables import read_rings_any
    from preprocessing.account_bank import load_paths
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.evaluate import restrict_rings
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--runs", type=Path, default=REPO_ROOT / "experiments/R4_partition/runs/average")
    ap.add_argument("--scores", type=Path, default=REPO_ROOT / "experiments/R1_gine_causal")
    ap.add_argument("--k-pct", type=float, default=0.1)
    ap.add_argument("--split", choices=["test", "val"], default="test")
    ap.add_argument("--rebuild", action="store_true", help="rebuild rings by the shipped route instead of reading --runs")
    ap.add_argument("--out-prefix", type=Path, default=REPO_ROOT / "results/tables/q0_buckets")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    pdir = load_paths()["processed_dir"]
    gt_path = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()["primary" if a.split == "test" else "val"]
    truth, patterns = load_ground_truth(gt_path, *W.bounds, "test_visible", verbose=False)
    gt = pd.read_parquet(gt_path)
    comp3, _, _ = component_truth(truth, patterns, gt, W, min_members=3)
    comp1, _, _ = component_truth(truth, patterns, gt, W, min_members=1)
    ge3 = {k[0] for k in comp3}
    print(f"truth rings {len(truth)}; no >=3 piece {len(truth) - len(ge3)}", flush=True)
    inputs = {"ground_truth": {"path": str(gt_path), "sha256": sha256(gt_path)}}

    rows = []
    for s in a.seeds:
        sp = a.scores / f"scores_{a.split}_seed{s}.parquet"
        inputs[f"seed{s}"] = {"scores": str(sp), "scores_sha256": sha256(sp)}
        if a.rebuild or a.split == "val":
            rings, se, mask = build_full_rings(s, a.split, pdir)
            inputs[f"seed{s}"]["rings"] = "rebuilt (shipped route)"
        else:
            rp = a.runs / f"seed{s}" / "rings.parquet"
            inputs[f"seed{s}"].update(rings=str(rp), rings_sha256=sha256(rp))
            se = build_scored_edges(sp, "test", model_id="gine_causal", seed=s, processed_dir=pdir)
            mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), a.k_pct)
            rings = read_rings_any(rp)
        quiet = quiet_accounts(truth, se, mask, W)
        rings = [r for r in rings if len(set(r.members)) >= 3]
        preds = restrict_rings(rings, se, W)
        matches, _, _ = match_rings(preds, truth, 0.5)
        mt = {m.truth_id for m in matches}
        mp = {m.pred_idx for m in matches}
        mbt = {m.truth_id: m for m in matches}
        ts = se.set_index("edge_id")["timestamp"]
        in_win = set(ts.index[W.mask(ts.values)].tolist())
        kept = [r for r in rings if any(e in in_win for e in r.member_edges)]
        assert len(kept) == len(preds)
        for tid, V in truth.items():
            others = set().union(*(truth[o] for o in truth if o != tid)) - V
            r = assign(V, tid in ge3, tid in mt, len(quiet[tid]) < len(V), preds, mp, others)
            rows.append({"seed": s, "ring_id": tid, "pattern_type": patterns.get(tid, "?"), "n_visible": len(V),
                         "n_quiet": len(quiet[tid]), **r,
                         **(a_detail(V, tid, comp1, preds, kept, mbt, in_win) if r["bucket"] == "a" else {})})
        c = Counter(x["bucket"] for x in rows if x["seed"] == s)
        print(f"seed {s}: matched {len(mt)} | " + " ".join(f"{b} {c[b]}" for b in BUCKETS), flush=True)

    df = pd.DataFrame(rows)
    for col in ("a_matched", "c1_no_prediction", "c2_one_to_one", "c2_other_ring"):
        df[col] = df[col].fillna(False).astype(bool) if col in df else False
    pre = a.out_prefix
    pre.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(f"{pre}_per_ring.csv", index=False)

    def summarise(g, n_seeds=len(a.seeds)):
        out = {}
        for b in BUCKETS:
            x = g[g["bucket"] == b]
            out[b] = len(x) / n_seeds
            out[f"{b}_quiet_share"] = x["n_quiet"].sum() / x["n_visible"].sum() if len(x) else np.nan
        out["a_matched"] = g["a_matched"].sum() / n_seeds
        out["a_unmatched"] = out["a"] - out["a_matched"]
        out["c1_no_prediction"] = g["c1_no_prediction"].sum() / n_seeds
        out["c2_one_to_one"] = g["c2_one_to_one"].sum() / n_seeds
        out["c2_other_ring"] = g["c2_other_ring"].sum() / n_seeds
        out["matched_total"] = out["d"] + out["a_matched"]
        return pd.Series(out)

    per_seed = df.groupby("seed").apply(summarise, n_seeds=1)
    per_seed.loc["mean"] = per_seed.mean()
    per_seed.loc["sd"] = per_seed.drop(index="mean").std(ddof=1)
    per_seed.to_csv(f"{pre}.csv")
    by_pat = df.groupby("pattern_type").apply(summarise)
    by_pat.insert(0, "n_rings", df.groupby("pattern_type")["ring_id"].nunique())
    by_pat.to_csv(f"{pre}_by_pattern.csv")
    Path(f"{pre}.json").write_text(json.dumps({
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "definitions": __doc__, "seeds": a.seeds, "k_pct": a.k_pct, "inputs": inputs,
        "checks": {"n_truth": len(truth), "n_no_ge3_piece": len(truth) - len(ge3)},
        "mean": per_seed.loc["mean"].to_dict()}, indent=2, default=float), encoding="utf-8")
    A = df[df["bucket"] == "a"].copy()
    A["visible"] = A["n_visible"].clip(upper=3).map({1: "1", 2: "2", 3: ">=3"})
    av = A.groupby("visible").agg(rings=("ring_id", "nunique"), matched_per_seed=("a_matched", lambda x: x.sum() / len(a.seeds)))
    av.to_csv(f"{pre}_a_by_visible.csv")
    ah = A[A["a_matched"]].groupby(["visible", "a_how"]).agg(per_seed=("ring_id", lambda x: len(x) / len(a.seeds)),
                                                          median_jaccard=("a_jaccard", "median"),
                                                          median_inwin=("a_pred_inwin_size", "median"),
                                                          median_full=("a_pred_full_size", "median"))
    ah.to_csv(f"{pre}_a_how.csv")
    print(av.to_string()); print(ah.to_string())
    print(per_seed.round(3).to_string())
    print(by_pat.round(2).to_string())


if __name__ == "__main__":
    main()
