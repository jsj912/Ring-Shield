"""Diagnosis only (author item 2, 2026-11-17): why Proposed = B0 on HI-Medium transfer seed 1 (primary, global rule).

    RINGSHIELD_PATHS=experiments/R18_hm_transfer/paths_hm_transfer.yaml \
    .venv312/Scripts/python.exe -u evaluation/hm_proposed_diag.py --seed 1

Rebuilds the close-out's primary/global inputs exactly (hm_closeout.topk_mask over days 6-14, context without
embeddings as hm_transfer_closeout), runs the registered policy's expansion at its own p_floor (p_min 0.9), and records
every probability the policy produced (Policy.predict is wrapped, nothing else changes) plus the NaN share of each
feature column it was fed. Writes results/tables/hm_transfer_proposed_diag_seed<S>.json. Nothing is retuned.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np

R = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(R))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--policy", type=Path, default=R / "experiments_hi_medium/R3_expansion/policy_no_detector")
    ap.add_argument("--tag", default="", help="suffix for the output json (default: none, the original file)")
    a = ap.parse_args()
    import evaluation.hm_closeout as hc
    from preprocessing.account_bank import load_paths
    from ringshield.aggregators.cc import SELECT_COL
    from ringshield.aggregators.expand import expand_all
    from ringshield.aggregators.full import included_from_trajectories
    from ringshield.expand.policy import Policy
    from ringshield.scored_edges import build_scored_edges
    from ringshield.windows import Window, load_windows

    S = a.seed
    pdir = load_paths()["processed_dir"]
    r1 = R / "experiments/R18_hm_transfer/closeout_input/R1_gine_causal_c1prime"
    pol = Policy.load(a.policy)
    rec = {"p": [], "nan": {}, "rows": 0}
    orig = pol.predict

    def wrapped(X):
        p = orig(X)
        rec["p"].append(np.asarray(p, float))
        rec["rows"] += len(X)
        for c in pol.features:
            if c in X:
                rec["nan"][c] = rec["nan"].get(c, 0) + int(X[c].isna().sum())
            else:
                rec["nan"][c] = rec["nan"].get(c, 0) + len(X)
        return p
    pol.predict = wrapped

    se = build_scored_edges(r1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
    P0 = load_windows()["primary"]
    W = Window("primary", "test", 6, 14, P0.day_zero, P0.seconds_per_day)
    ctx = hc.build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet", embeddings_parquet=None,
                           checkpoint=r1 / f"model_best_seed{S}.pt")
    sc, ts, eid = se[SELECT_COL].to_numpy(float), se["timestamp"].to_numpy(np.int64), se["edge_id"].to_numpy(np.int64)
    in_w = W.mask(ts)
    mask = np.zeros(len(sc), dtype=bool)
    mask[in_w] = hc.topk_mask(sc[in_w], eid[in_w])
    trajs = expand_all(se, mask, pol, ctx, delta_t_h=hc.DT, p_floor=hc.PMIN)
    inc_pos, is_seed = included_from_trajectories(se, mask, trajs, hc.PMIN)
    p = np.concatenate(rec["p"]) if rec["p"] else np.array([])
    stops = {}
    for t in trajs:
        stops[t["stop"]] = stops.get(t["stop"], 0) + 1
    q = [0.5, 0.9, 0.99, 0.999, 1.0]
    out = {"seed": S, "p_min": hc.PMIN, "delta_t_h": hc.DT, "n_seeds": int(mask.sum()), "n_seed_components": len(trajs),
           "n_added_edges": int((~is_seed).sum()), "stops": stops, "n_scored_candidates": int(len(p)),
           "p_quantiles": dict(zip(map(str, q), np.quantile(p, q).round(6).tolist())) if len(p) else None,
           "p_max": float(p.max()) if len(p) else None, "n_p_ge_pmin": int((p >= hc.PMIN).sum()),
           "n_p_ge_0.5": int((p >= 0.5).sum()), "n_distinct_p": int(len(np.unique(p.round(9)))),
           "nan_share": {c: round(v / max(rec["rows"], 1), 4) for c, v in rec["nan"].items() if v},
           "ctx_meta": ctx.meta, "policy": str(a.policy)}
    o = R / f"results/tables/hm_transfer_proposed_diag_seed{S}{a.tag}.json"
    o.write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
