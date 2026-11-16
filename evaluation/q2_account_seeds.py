"""Q2: account-level seeding at the shipped seed count (paper/PREREG_Q_2026-11-15.md, section Q2).

    CUDA_VISIBLE_DEVICES="" python -m evaluation.q2_account_seeds --split val --variants max top3
    CUDA_VISIBLE_DEVICES="" python -m evaluation.q2_account_seeds --split test --variants <chosen>

Account score a(v) from the raw scores of v's incident edges in the split: `max`, or `top3` = mean of
the three highest (all, if fewer than three). Accounts are ranked by a(v) descending, ties by account id
ascending. Walking the ranking, each account contributes its not-yet-chosen incident edges in
descending score_raw (ties: edge_id ascending), at most three, until exactly N edges are chosen, where
N = #(score_raw > q), the shipped global strict 0.1 % seed count for that seed and split.

Only the seed mask changes. Expansion, policy features, partition and the R3/R4 cells read the
original gine_causal scored edges, as in evaluation/realloc_full.py (11c / 11b under full). Writes
seed-only (cc on the mask, evaluation.window_budget.cc_rings_from_mask) and full rings to
experiments/Q2_account_seeds/<split>/<variant>/{b0,full}/seed<S>/rings.parquet (minimal schema).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

E2E = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R1_gine_causal"
OUT = REPO_ROOT / "experiments" / "Q2_account_seeds"


def account_seed_mask(edge_id, from_id, to_id, score, variant: str, N: int) -> np.ndarray:
    """Boolean mask (positional) of exactly N seed edges under the Q2 rule."""
    n = len(score)
    pos = np.arange(n)
    long = pd.DataFrame({"acc": np.concatenate([from_id, to_id]), "pos": np.concatenate([pos, pos]),
                         "s": np.concatenate([score, score]), "e": np.concatenate([edge_id, edge_id])})
    long = long[~np.isnan(long["s"])]
    long = long.sort_values(["acc", "s", "e"], ascending=[True, False, True])
    g = long.groupby("acc", sort=False)["s"]
    agg = g.max() if variant == "max" else long.assign(r=g.cumcount()).query("r < 3").groupby("acc")["s"].mean()
    order = sorted(agg.index, key=lambda a: (-agg[a], a))
    edges_of = {a: grp["pos"].to_numpy() for a, grp in long.groupby("acc", sort=False)}
    chosen = np.zeros(n, dtype=bool)
    k = 0
    for a in order:
        if k >= N:
            break
        took = 0
        for p in edges_of[a]:
            if took == 3 or k >= N:
                break
            if not chosen[p]:
                chosen[p] = True
                took += 1
                k += 1
    assert k == N, (k, N)
    return chosen


def run(S: int, split: str, variants: list[str]):
    import yaml
    from preprocessing.account_bank import load_paths
    from evaluation.window_budget import cc_rings_from_mask
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.aggregators.expand import expand_all
    from ringshield.aggregators.full import component_pairs, included_from_trajectories, partition_labels, rings_from_edge_clusters
    from ringshield.expand.context import build_context
    from ringshield.expand.policy import Policy
    from ringshield.partition.affinity import Affinity
    from ringshield.partition.pairs import components_of
    from ringshield.scored_edges import build_scored_edges
    pdir = load_paths()["processed_dir"]
    R1, R3, R4 = (REPO_ROOT / "experiments" / d for d in ("R1_gine_causal", "R3_expansion", "R4_partition"))
    r3 = yaml.safe_load((R3 / "runs/proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    r4 = yaml.safe_load((R4 / "runs/average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    se = build_scored_edges(R1 / f"scores_{split}_seed{S}.parquet", split, model_id="gine_causal", seed=S, processed_dir=pdir)
    emb = R1 / f"embeddings_{split}_seed{S}.parquet"
    emb = emb if emb.exists() else E2E / f"embeddings_{split}_seed{S}.parquet"
    ctx = build_context(se, gfp_parquet=pdir / f"amlworld_gfp_features_{split}.parquet", embeddings_parquet=emb,
                        checkpoint=E2E / f"model_best_seed{S}.pt")
    policy, aff = Policy.load(R3 / "policy_proposed"), Affinity.load(R4 / "affinity")
    sc = se[SELECT_COL].to_numpy(float)
    N = int(seed_mask_for_pct(sc, 0.1).sum())
    stats = {}
    for v in variants:
        mask = account_seed_mask(se["edge_id"].to_numpy(), se["from_id"].to_numpy(), se["to_id"].to_numpy(), sc, v, N)
        shipped = seed_mask_for_pct(sc, 0.1)
        trajs = expand_all(se, mask, policy, ctx, delta_t_h=float(r3["delta_t_h"]), p_floor=float(r3["p_min"]))
        inc_pos, is_seed = included_from_trajectories(se, mask, trajs, float(r3["p_min"]))
        comp = components_of(ctx.idx, inc_pos)
        P = component_pairs(ctx, inc_pos, is_seed, comp, aff)
        lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=3,
                               **{k: r4[k] for k in ("cut", "threshold", "gap_h", "resolution") if k in r4})
        for name, rings in (("b0", cc_rings_from_mask(se, mask, 3)),
                            ("full", rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, 3))):
            d = OUT / split / v / name / f"seed{S}"
            d.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"ring_id": np.arange(len(rings)),
                          "members": [sorted(int(a) for a in r.members) for r in rings],
                          "member_edges": [[int(e) for e in r.member_edges] for r in rings]}).to_parquet(d / "rings.parquet", index=False)
        stats[v] = {"N": N, "seed_jaccard_vs_shipped": float((mask & shipped).sum() / (mask | shipped).sum()),
                    "n_seed_accounts": int(len(set(se["from_id"].to_numpy()[mask]) | set(se["to_id"].to_numpy()[mask])))}
        print(f"  seed {S} {split} {v}: N {N}, seed Jaccard vs shipped {stats[v]['seed_jaccard_vs_shipped']:.3f}", flush=True)
    (OUT / split / f"stats_seed{S}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")


def secondary(arms: dict, out: Path):
    """Added-member precision, quiet-member recall, rings touched, accounts output (test, primary window).
    arms: name -> (rings dir template with {S}, seed-mask fn(se) -> bool array)."""
    from preprocessing.account_bank import load_paths
    from evaluation.ring_stats import quiet_accounts
    from evaluation.ring_metrics import match_rings
    from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct
    from ringshield.evaluate import restrict_rings
    from ringshield.scored_edges import build_scored_edges
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    truth, _ = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    rid = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows = []
    for S in range(1, 6):
        se = build_scored_edges(REPO_ROOT / "experiments/R1_gine_causal" / f"scores_test_seed{S}.parquet", "test",
                                model_id="gine_causal", seed=S, processed_dir=pdir)
        sc = se[SELECT_COL].to_numpy(float)
        N = int(seed_mask_for_pct(sc, 0.1).sum())
        in_win = W.mask(se["timestamp"].to_numpy())
        r_of = rid.reindex(se["edge_id"].to_numpy()).fillna(0).to_numpy()
        for name, (tmpl, mk) in arms.items():
            mask = mk(se, sc, N)
            seed_ids = set(se["edge_id"].to_numpy()[mask].tolist())
            df = pd.read_parquet(str(tmpl).format(S=S), columns=["members", "member_edges"])
            win_ids = set(se["edge_id"].to_numpy()[in_win].tolist())
            members = [set(m) for m in df["members"]]
            medges = [set(e) for e in df["member_edges"]]
            keep = [i for i in range(len(df)) if len(members[i]) >= 3]
            exp = set().union(*(medges[i] for i in keep)) - seed_ids if keep else set()
            exp_win = [e for e in exp if e in win_ids]
            ring_e = dict(zip(se["edge_id"].to_numpy(), r_of))
            amp = (sum(1 for e in exp_win if ring_e.get(e, 0) > 0) / len(exp_win)) if exp_win else float("nan")
            frm, to = se.set_index("edge_id")["from_id"], se.set_index("edge_id")["to_id"]
            pred = []
            for i in keep:
                ew = [e for e in medges[i] if e in win_ids]
                if ew:
                    pred.append(set(frm.loc[ew].tolist()) | set(to.loc[ew].tolist()))
            matches, _, _ = match_rings(pred, truth, 0.5)
            q = quiet_accounts(truth, se, mask, W)
            q_tot = sum(len(v) for v in q.values())
            q_found = sum(len(q[m.truth_id] & pred[m.pred_idx]) for m in matches)
            touched = {int(r) for r in r_of[mask & in_win] if r > 0} & set(truth)
            rows.append({"seed": S, "arm": name, "added_member_precision": amp, "n_expanded_in_window": len(exp_win),
                         "quiet_member_recall": q_found / q_tot if q_tot else float("nan"), "rings_touched": len(touched),
                         "rings_output": len(keep), "accounts_output_unrestricted": len(set().union(*(members[i] for i in keep))),
                         "rings_output_in_window": len(pred), "accounts_output_in_window": len(set().union(*pred)) if pred else 0,
                         "n_matched_check": len(matches)})
            print(rows[-1], flush=True)
    d = pd.DataFrame(rows)
    d.to_csv(out.with_name(out.stem + "_per_seed.csv"), index=False)
    m = d.groupby("arm").mean(numeric_only=True).drop(columns="seed")
    m.to_csv(out)
    print(m.round(4).to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["val", "test"], default=None)
    ap.add_argument("--secondary", action="store_true", help="secondary columns for top3 full / B0 vs shipped (test)")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--variants", nargs="+", choices=["max", "top3"], default=["max", "top3"])
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if a.secondary:
        from ringshield.aggregators.cc import seed_mask_for_pct
        glob = lambda se, sc, N: seed_mask_for_pct(sc, 0.1)
        acc = lambda se, sc, N: account_seed_mask(se["edge_id"].to_numpy(), se["from_id"].to_numpy(), se["to_id"].to_numpy(), sc, "top3", N)
        e2e = REPO_ROOT.parent / "RS-e2e" / "experiments" / "R2_b0" / "gine_causal"
        secondary({"shipped_full": (REPO_ROOT / "experiments/R4_partition/runs/average/seed{S}/rings.parquet", glob),
                   "q2top3_full": (OUT / "test/top3/full/seed{S}/rings.parquet", acc),
                   "shipped_b0": (e2e / "seed{S}/rings.parquet", glob),
                   "q2top3_b0": (OUT / "test/top3/b0/seed{S}/rings.parquet", acc)},
                  REPO_ROOT / "results/tables/q2_secondary.csv")
        return
    assert a.split, "--split required"
    for S in a.seeds:
        run(S, a.split, a.variants)


if __name__ == "__main__":
    main()
