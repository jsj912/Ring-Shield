"""deep-analysis #11 (registered 2026-11-12): mixed-ring fidelity, a mix retuned on expanded recall, and
abstention on topology_prob.

    python -m explainability.mixed_ring_eval --test-root ../RS-e2e --val-rings-root ../RS-ccy-valrings

Leave-one-out is computed exactly as explainability.edge_weights (non-degraded reruns); every grid triple
then orders each matched ring's evidence edges by w_total. Validation chooses the triple (objective:
expanded recall@5) and the abstention threshold; test reports them against the shipped mix, score-only and
random. Statistics over truth rings with seeds averaged, 1,000 bootstrap resamples.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from explainability.contract_io import REPO_ROOT, load_config, read_rings, read_scored_edges
from explainability.edge_weights import (conversion_mask, edge_weight_table, evidence_edge_ids, load_fx,
                                         load_loo_inputs, rank_by_score, w_loo)
from explainability.evaluate import fidelity_at_k, mixing_grid, random_fidelity
from explainability.match import in_window_edge_ids, match_in_window, matching_rule, truth_edge_sets, window_from_config

K = 5
SHIPPED = (0.6, 0.0, 0.4)
T_GRID = [round(0.30 + 0.05 * i, 2) for i in range(14)]


def collect(cfg, split, seeds, scored_tpl, rings_tpl, split_parquet, window_name):
    """Per matched ring-instance: evidence/expanded/truth sets and the per-triple orders' metrics."""
    ev = cfg["evaluation"]
    cfg_w = {**cfg, "evaluation": {**ev, "window": window_name}}
    W = window_from_config(cfg_w)
    thr, scope = matching_rule(cfg)
    fx = load_fx(cfg)
    grid = mixing_grid(float(cfg["edge_weights"]["grid_step"]))
    ew = cfg["edge_weights"]
    rows = []
    for s in seeds:
        sp, rp = scored_tpl.format(seed=s), rings_tpl.format(seed=s)
        se = read_scored_edges(sp)
        rings = read_rings(rp, scored_edges=se)
        res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=cfg["inputs"]["truth"])
        T = truth_edge_sets(split_parquet, W, ring_ids=res.matches["truth_ring_id"])
        by_id = rings.set_index("ring_id")
        inc_of = lambda r: sorted(set(map(int, r.seed_edges)) | set(map(int, r.expanded_edges)))
        ids = [e for rid in res.matches["ring_id"] for e in inc_of(by_id.loc[rid])]
        loo_in = load_loo_inputs(cfg, s, "full", rp, ids, split=split)
        sei = se.set_index("edge_id")
        conv = conversion_mask(se)
        in_win = in_window_edge_ids(se, W)
        for i, m in enumerate(res.matches.itertuples(index=False)):
            r = by_id.loc[m.ring_id]
            member = sei.loc[sorted(map(int, r.member_edges))].reset_index()
            loo = w_loo(sei.loc[inc_of(r)].reset_index(), loo_in.rerunner, lambda_split=float(ew["lambda_split"]),
                        nan_policy=ew["loo_nan_policy"])
            evid, _ = evidence_edge_ids([e for e in r.member_edges if e in in_win], conv, "converted")
            X, _ = evidence_edge_ids([int(e) for e in r.expanded_edges if e in in_win], conv, "converted")
            Tm = T.edges[int(m.truth_ring_id)]
            keep, XT = set(evid), set(X) & Tm
            mixed = 0 < len(keep & Tm) < len(keep)
            fid, exp = [], []
            for a, b, g in grid:
                table = edge_weight_table(member, loo, {"alpha": a, "beta": b, "gamma": g},
                                          tol=float(ew["mixing_sum_tolerance"]), policy="converted", fx=fx)
                order = [e for e in table["edge_id"] if e in keep]
                fid.append(fidelity_at_k(order, Tm, K) if keep & Tm else np.nan)
                exp.append(fidelity_at_k(order, XT, K) if XT else np.nan)
            so = rank_by_score(sei.loc[sorted(keep)].reset_index()) if keep else []
            salt = [int(ev["random_seed"]), int(s), i, 11]
            rows.append({"split": split, "seed": s, "ring_id": m.ring_id, "truth_ring_id": int(m.truth_ring_id),
                         "topology_type": r.topology_type,
                         "topology_prob": float(np.max(r.topology_probs)) if r.topology_probs is not None and len(r.topology_probs) else np.nan,
                         "n_evidence": len(keep), "n_true_evidence": len(keep & Tm), "mixed": mixed, "n_XT": len(XT),
                         "fid": fid, "exp": exp,
                         "fid_score": fidelity_at_k(so, Tm, K) if keep & Tm else np.nan,
                         "exp_score": fidelity_at_k(so, XT, K) if XT else np.nan,
                         "fid_random": random_fidelity(sorted(keep), Tm, [K], int(ev["random_shuffles"]), salt)[K] if keep & Tm else np.nan,
                         "exp_random": random_fidelity(sorted(keep), XT, [K], int(ev["random_shuffles"]), salt + [1])[K] if XT else np.nan})
        print(f"  {split} seed {s}: {res.n_matched} matched, {sum(r['mixed'] for r in rows if r['seed'] == s and r['split'] == split)} mixed",
              flush=True)
    return pd.DataFrame(rows), grid


def per_truth(df, col):
    """Mean over seeds per truth ring -> Series indexed by truth_ring_id."""
    return df.groupby("truth_ring_id")[col].mean().dropna()


def boot_ci(v: np.ndarray, n=1000, seed=20260921):
    rng = np.random.default_rng(seed)
    d = v[rng.integers(0, len(v), (n, len(v)))].mean(1)
    return [float(v.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test-root", type=Path, required=True)
    ap.add_argument("--val-rings-root", type=Path, required=True)
    ap.add_argument("--emb-root", type=Path, required=True, help="checkout holding experiments/R1_gine_causal embeddings")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "xai" / "mixed_ring_eval.json")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    tr = a.test_root.resolve()
    cfg["research_inputs"] = {**cfg["research_inputs"],
                              "embeddings": str(a.emb_root.resolve() / "experiments/R1_gine_causal/embeddings_test_seed{seed}.parquet"),
                              "embeddings_val": str(a.emb_root.resolve() / "experiments/R1_gine_causal/embeddings_val_seed{seed}.parquet")}
    val, grid = collect(cfg, "val", a.seeds, str(tr / "contract/out/scored_edges_gine_causal_{seed}_val.parquet"),
                        str(a.val_rings_root.resolve() / "experiments_valrings/average/seed{seed}/rings_val.parquet"),
                        cfg["val_inputs"]["split_parquet"], cfg["val_inputs"]["window"])
    test, _ = collect(cfg, "test", a.seeds, str(tr / "contract/out/scored_edges_gine_causal_{seed}.parquet"),
                      str(tr / "contract/out/rings_full_gine_causal_{seed}.parquet"),
                      cfg["inputs"]["split_parquet"], cfg["evaluation"]["window"])
    shipped_i = grid.index(SHIPPED)

    # ---- choose the triple on validation
    E = np.array(val["exp"].tolist(), dtype=float)
    F = np.array(val[val["mixed"]]["fid"].tolist(), dtype=float)
    obj = np.nanmean(E, axis=0)
    fobj = np.nanmean(F, axis=0) if len(F) else np.zeros(len(grid))
    dist = [float(np.linalg.norm(np.array(t) - np.array(SHIPPED))) for t in grid]
    best = sorted(range(len(grid)), key=lambda i: (-round(obj[i], 12), -round(fobj[i], 12), dist[i]))[0]
    chosen = grid[best]
    print(f"val: chosen {chosen} expanded recall@5 {obj[best]:.4f} (shipped {obj[shipped_i]:.4f}); "
          f"val mixed fid@5 {fobj[best]:.4f} (shipped {fobj[shipped_i]:.4f}); n val mixed {len(F)}")

    # ---- abstention threshold on validation (true type from the matched truth ring's pattern)
    from contract.make_scored_edges import load_paths
    from ringshield.truth import load_ground_truth
    from ringshield.windows import load_windows
    gt = load_paths()["processed_dir"] / "amlworld_ring_ground_truth.parquet"
    Ws = load_windows()
    pats = {}
    for name in ("val", "primary"):
        _, p = load_ground_truth(gt, *Ws[name].bounds, "test_visible", verbose=False)
        pats.update(p)
    for d in (val, test):
        d["true_type"] = d["truth_ring_id"].map(pats)
        d["type_ok"] = (d["topology_type"] == d["true_type"]).astype(float)
    t_choice, t_table = None, []
    for t in T_GRID:
        st = val[val["topology_prob"] >= t]
        acc = float(st["type_ok"].mean()) if len(st) else np.nan
        cov = len(st) / len(val)
        t_table.append({"t": t, "val_accuracy": acc, "val_coverage": cov})
        if t_choice is None and acc == acc and acc >= 0.80:
            t_choice = t
    if t_choice is None:
        ok = [r for r in t_table if r["val_coverage"] >= 0.2 and r["val_accuracy"] == r["val_accuracy"]]
        t_choice = max(ok, key=lambda r: r["val_accuracy"])["t"] if ok else T_GRID[0]

    # ---- test
    test["exp_chosen"] = [r[best] for r in test["exp"]]
    test["exp_shipped"] = [r[shipped_i] for r in test["exp"]]
    test["fid_chosen"] = [r[best] for r in test["fid"]]
    test["fid_shipped"] = [r[shipped_i] for r in test["fid"]]
    out = {"chosen_triple": dict(zip(("alpha", "beta", "gamma"), chosen)), "shipped_triple": dict(zip(("alpha", "beta", "gamma"), SHIPPED)),
           "val": {"n_matched": int(len(val)), "n_mixed": int(val["mixed"].sum()), "n_with_true_expanded": int((val["n_XT"] > 0).sum()),
                   "expanded_recall5_chosen": float(obj[best]), "expanded_recall5_shipped": float(obj[shipped_i]),
                   "mixed_fid5_chosen": float(fobj[best]), "mixed_fid5_shipped": float(fobj[shipped_i]),
                   "top5_triples": [{"triple": grid[i], "exp5": float(obj[i]), "mixed_fid5": float(fobj[i])}
                                    for i in np.argsort(-obj)[:5]]},
           "test": {"n_matched": int(len(test)), "n_mixed": int(test["mixed"].sum()), "n_with_true_expanded": int((test["n_XT"] > 0).sum()),
                    "n_saturating": int(((test["n_true_evidence"] == test["n_evidence"]) & (test["n_evidence"] > 0)).sum())}}
    E_ = test[test["n_XT"] > 0]
    for col in ("exp_chosen", "exp_shipped", "exp_score", "exp_random"):
        out["test"][col] = boot_ci(per_truth(E_, col).to_numpy())
    M = test[test["mixed"]]
    for col in ("fid_chosen", "fid_shipped", "fid_score", "fid_random"):
        out["test"][col] = boot_ci(per_truth(M, col).to_numpy()) if len(M) else None
    pa = per_truth(E_, "exp_chosen") - per_truth(E_, "exp_random")
    pf = (per_truth(M, "fid_chosen") - per_truth(M, "fid_shipped")).dropna()
    out["test"]["exp_chosen_minus_random"] = boot_ci(pa.dropna().to_numpy())
    out["test"]["mixed_fid_chosen_minus_shipped"] = boot_ci(pf.to_numpy()) if len(pf) else None
    out["test"]["mixed_fid_score_minus_shipped"] = boot_ci((per_truth(M, "fid_score") - per_truth(M, "fid_shipped")).dropna().to_numpy()) if len(M) else None
    succ = (out["test"]["exp_chosen"][0] >= out["test"]["exp_random"][0]) and (pf.empty or out["test"]["mixed_fid_chosen_minus_shipped"][2] >= 0)
    out["success"] = bool(succ)
    st = test[test["topology_prob"] >= t_choice]
    out["abstention"] = {"t_chosen_on_val": t_choice, "val_table": t_table,
                         "test_accuracy_stated": float(st["type_ok"].mean()) if len(st) else None,
                         "test_coverage": len(st) / len(test), "test_accuracy_no_abstention": float(test["type_ok"].mean())}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2, default=float), encoding="utf-8")
    test.drop(columns=["fid", "exp"]).to_csv(str(a.out).replace(".json", "_test_rows.csv"), index=False)
    print(json.dumps({k: out[k] for k in ("chosen_triple", "val", "test", "success", "abstention")}, indent=1, default=float)[:6000])


if __name__ == "__main__":
    main()
