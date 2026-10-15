"""Explanation fidelity (spec section 6.1-6.2, minimal Week 1 version: XR-22 point estimates, XR-24 controls).

    python -m explainability.evaluate                       # all seeds in config.yaml, primary window
    python -m explainability.evaluate --seeds 1 --rings contract/out/rings_stub_cc.parquet \
        --name fidelity_week1_stub_cc_seed{seed}.json

For every predicted ring that matched a true ring (match.py, i.e. the research side's matching):
    edges  = the ring's member_edges inside the evaluation window
    T      = the true ring's transactions inside the same window
    ranked = edges ordered by a ranking (Week 1: detector score only)
    fidelity@k = |first k of ranked  intersect  T| / min(k, |T|)

Reported per ranking as the mean over matched rings, for k in config (3, 5, 10):
    score_only -- rank_by_score (edge_weights.py)
    random     -- the control: the same edges in random order, averaged over `random_shuffles`
                  shuffles with a fixed seed per ring, so it reproduces exactly
A ranking is any function `edges DataFrame -> list of edge ids`; Weeks 2-4 add w_total to RANKINGS.

Output: one JSON per detector seed (no timestamps inside, keys sorted), so two runs on the same inputs
are byte-identical.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from explainability.contract_io import REPO_ROOT, load_config, provenance, read_rings, read_scored_edges, repo_path
from explainability.edge_weights import conversion_mask, evidence_edge_ids, rank_by_score
from explainability.match import (in_window_edge_ids, match_in_window, matching_rule, truth_edge_sets,
                                  window_from_config)

RANKINGS = {"score_only": rank_by_score}


# ----------------------------------------------------------------------------- the metric
def fidelity_at_k(ranked: list[int], truth: set[int], k: int) -> float:
    """|top-k of ranked & truth| / min(k, |truth|). If the ring has fewer than k edges, top-k is all of them."""
    if not truth:
        raise ValueError("fidelity is undefined for an empty true edge set")
    return len(set(ranked[:k]) & truth) / min(k, len(truth))


def random_fidelity(edge_ids: list[int], truth: set[int], ks: list[int], n_shuffles: int, rng_seed) -> dict[int, float]:
    """Mean fidelity@k over `n_shuffles` random orders of the same edges. `rng_seed` fixes the shuffles."""
    rng = np.random.default_rng(rng_seed)
    base = np.array(sorted(edge_ids), dtype=np.int64)       # sorted first, so input order cannot matter
    sums = {k: 0.0 for k in ks}
    for _ in range(n_shuffles):
        order = rng.permutation(base).tolist()
        for k in ks:
            sums[k] += fidelity_at_k(order, truth, k)
    return {k: sums[k] / n_shuffles for k in ks}


# ----------------------------------------------------------------------------- one seed
def _rel(p) -> str:
    p = repo_path(p)
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def evaluate_frames(scored_edges: pd.DataFrame, rings: pd.DataFrame, match_result, truth_edges, window, cfg: dict,
                    detector_seed: int, *, policy: str | None = None,
                    precomputed: dict[str, dict[str, list[int]]] | None = None) -> tuple[pd.DataFrame, dict]:
    """Per-ring fidelity rows and the summary (mean over matched rings) for every ranking.

    The edges ranked are the ring's member_edges inside the window -- minus currency conversions under
    policy `converted` (they can never be laundering), all of them under `raw` (reproduces Week 1).
    `precomputed` adds rankings given as a fixed edge order per ring (e.g. w_total from an explanations
    file): {name: {ring_id: [edge ids, best first]}}; the order is restricted to the ranked edges."""
    ev = cfg["evaluation"]
    policy = policy or cfg["amounts"]["currency_policy"]
    ks = [int(k) for k in ev["k"]]
    in_win = in_window_edge_ids(scored_edges, window)
    conv = conversion_mask(scored_edges)
    se = scored_edges.set_index("edge_id")
    ring_by_id = rings.set_index("ring_id")
    rows = []
    for i, m in enumerate(match_result.matches.itertuples(index=False)):     # sorted by ring_id
        in_window = [int(e) for e in ring_by_id.at[m.ring_id, "member_edges"] if e in in_win]
        member, n_conv = evidence_edge_ids(in_window, conv, policy)
        edges = se.loc[sorted(member)].reset_index()
        T = truth_edges.edges[int(m.truth_ring_id)]
        row = {"ring_id": m.ring_id, "truth_ring_id": int(m.truth_ring_id), "pattern_type": m.pattern_type,
               "jaccard": float(m.jaccard), "n_edges_ranked": len(member), "n_true_edges": len(T),
               "n_true_among_ranked": len(set(member) & T), "n_conversions_dropped": n_conv}
        for name, rank in RANKINGS.items():
            ranked = rank(edges)
            for k in ks:
                row[f"{name}@{k}"] = fidelity_at_k(ranked, T, k)
        for name, orders in (precomputed or {}).items():
            keep = set(member)
            ranked = [e for e in orders[m.ring_id] if e in keep]
            for k in ks:
                row[f"{name}@{k}"] = fidelity_at_k(ranked, T, k)
        rnd = random_fidelity(member, T, ks, int(ev["random_shuffles"]), [int(ev["random_seed"]), int(detector_seed), i])
        for k in ks:
            row[f"random@{k}"] = rnd[k]
        rows.append(row)
    per_ring = pd.DataFrame(rows)
    names = list(RANKINGS) + list(precomputed or {}) + ["random"]
    summary = {name: {str(k): (float(per_ring[f"{name}@{k}"].mean()) if len(per_ring) else None) for k in ks}
               for name in names}
    return per_ring, summary


def evaluate_seed(cfg: dict, seed: int, *, scores: str, rings_path: str, truth: str, split_parquet: str,
                  policy: str | None = None, precomputed: dict | None = None) -> dict:
    policy = policy or cfg["amounts"]["currency_policy"]
    se = read_scored_edges(scores)
    rings = read_rings(rings_path, scored_edges=se)
    prov = provenance(se, rings)
    W = window_from_config(cfg)
    thr, scope = matching_rule(cfg)
    res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=truth)
    T = truth_edge_sets(split_parquet, W, ring_ids=res.matches["truth_ring_id"])
    per_ring, summary = evaluate_frames(se, rings, res, T, W, cfg, prov["seed"], policy=policy, precomputed=precomputed)
    ev = cfg["evaluation"]
    ranked_desc = ("ring member_edges inside the window" if policy == "raw" else
                   "ring member_edges inside the window, currency conversions removed")
    return {
        "experiment_id": cfg["experiment_id"], "explainer_version": cfg["explainer_version"],
        "what": "fidelity@k of the score-only ranking and a random control, on matched rings",
        "inputs": {"scored_edges": _rel(scores), "rings": _rel(rings_path), "truth": _rel(truth),
                   "split_parquet": _rel(split_parquet)},
        "provenance": prov, "policy": policy,
        "evaluation": {"window": res.window, "scope": scope, "match_threshold": thr, "k": [int(k) for k in ev["k"]],
                       "random_shuffles": int(ev["random_shuffles"]), "random_seed": int(ev["random_seed"]),
                       "edges_ranked": ranked_desc,
                       "true_edges": "truth ring transactions inside the window (split parquet ring_id)"},
        "counts": {"n_pred_total": res.n_pred_total, "n_pred_in_window": res.n_pred_in_window,
                   "n_truth_in_scope": res.n_truth, "n_matched": res.n_matched, "n_rings_scored": len(per_ring),
                   "n_conversions_dropped": int(per_ring["n_conversions_dropped"].sum()) if len(per_ring) else 0},
        "fidelity": summary,
        "per_ring": per_ring.to_dict("records"),
    }


def write_json(obj: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


# ----------------------------------------------------------------------------- policy comparison (migration report)
def compare_policies(cfg: dict, seeds, out_dir) -> dict:
    """Week 2 as shipped (v1 rings, policy raw) against the migrated run (v2 rings, policy converted), from the
    files both runs wrote. Reports role counts and changes, top-k evidence edges, how many top-ranked edges
    were currency conversions before the filter, fidelity@k under both policies, and how many matched rings
    can tell two rankings apart at all (a ring whose ranked edges are ALL true scores 1 under any ordering)."""
    import pyarrow.parquet as pq
    out_dir = repo_path(out_dir)
    ks = [int(k) for k in cfg["evaluation"]["k"]]
    report = {"what": "Week 2 (v1 rings, raw) vs migrated (v2 rings, converted)", "seeds": {}, "pooled": {}}
    pooled = {"role_transitions": {}, "roles_raw": {}, "roles_converted": {}, "topk_conversions_raw": {k: 0 for k in ks},
              "topk_same_set": {k: 0 for k in ks}, "n_rings": 0, "fidelity": {"raw": [], "converted": []},
              "saturation": {"raw": [0, 0, 0], "converted": [0, 0, 0]}}
    for s in seeds:
        se = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=s))
        conv = conversion_mask(se)
        old = {r["ring_id"]: r for r in pq.read_table(out_dir / cfg["explanations_name"].format(seed=s)).to_pylist()}
        new = {r["ring_id"]: r for r in pq.read_table(out_dir / cfg["explanations_name_converted"].format(seed=s)).to_pylist()}
        assert set(old) == set(new), f"seed {s}: the two runs explain different rings"
        trans, topk_conv, topk_same = {}, {k: 0 for k in ks}, {k: 0 for k in ks}
        for rid in sorted(old):
            ro = {a["account_id"]: a["role"] for a in old[rid]["account_weights"]}
            rn = {a["account_id"]: a["role"] for a in new[rid]["account_weights"]}
            for a in ro:
                key = f"{ro[a]} -> {rn.get(a)}"
                trans[key] = trans.get(key, 0) + 1
            order_old = [e["edge_id"] for e in old[rid]["edge_weights"]]
            order_new = [e["edge_id"] for e in new[rid]["edge_weights"]]
            for k in ks:
                topk_conv[k] += int(conv.reindex(order_old[:k]).sum())
                topk_same[k] += int(set(order_old[:k]) == set(order_new[:k]))
        fid = {}
        for pol, name in (("raw", cfg["output_name"]), ("converted", cfg["output_name_converted"])):
            d = json.loads((out_dir / name.format(seed=s)).read_text(encoding="utf-8"))
            fid[pol] = d["fidelity"]
            for r in d["per_ring"]:
                sat = pooled["saturation"][pol]
                sat[0] += 1
                sat[1] += int(r["n_true_among_ranked"] == r["n_edges_ranked"])
                sat[2] += int(0 < r["n_true_among_ranked"] < r["n_edges_ranked"])
            pooled["fidelity"][pol].append(d["fidelity"])
        roles_old = {k.split(" -> ")[0]: 0 for k in trans}
        roles_new = {}
        for key, v in trans.items():
            a, b = key.split(" -> ")
            roles_old[a] = roles_old.get(a, 0) + v
            roles_new[b] = roles_new.get(b, 0) + v
        changed = sum(v for key, v in trans.items() if key.split(" -> ")[0] != key.split(" -> ")[1])
        report["seeds"][str(s)] = {"n_rings": len(old), "roles_raw": roles_old, "roles_converted": roles_new,
                                   "n_accounts": sum(trans.values()), "n_roles_changed": changed,
                                   "role_transitions": dict(sorted(trans.items())),
                                   "topk_conversions_before_filter": {str(k): v for k, v in topk_conv.items()},
                                   "topk_same_edge_set": {str(k): v for k, v in topk_same.items()},
                                   "fidelity": fid}
        pooled["n_rings"] += len(old)
        for key, v in trans.items():
            pooled["role_transitions"][key] = pooled["role_transitions"].get(key, 0) + v
        for k in ks:
            pooled["topk_conversions_raw"][k] += topk_conv[k]
            pooled["topk_same_set"][k] += topk_same[k]
    mean = lambda fs, n, k: float(np.mean([f[n][str(k)] for f in fs]))
    t = pooled["role_transitions"]
    report["pooled"] = {
        "n_rings": pooled["n_rings"], "n_accounts": sum(t.values()),
        "n_roles_changed": sum(v for key, v in t.items() if key.split(" -> ")[0] != key.split(" -> ")[1]),
        "role_transitions": dict(sorted(t.items())),
        "topk_conversions_before_filter": {str(k): v for k, v in pooled["topk_conversions_raw"].items()},
        "topk_slots_total": {str(k): k * pooled["n_rings"] for k in ks},
        "topk_same_edge_set_rings": {str(k): v for k, v in pooled["topk_same_set"].items()},
        "fidelity_mean_over_seeds": {pol: {n: {str(k): mean(pooled["fidelity"][pol], n, k) for k in ks}
                                           for n in ("score_only", "random")} for pol in ("raw", "converted")},
        "matched_rings_saturation": {pol: {"n_matched": v[0], "all_ranked_edges_true": v[1],
                                           "can_discriminate_rankings": v[2]}
                                     for pol, v in pooled["saturation"].items()},
        "note": ("Default (untuned) mixing in both runs; fidelity uses the score-only ranking and the random "
                 "control. 'can_discriminate_rankings' = matched rings with at least one true and one non-true "
                 "ranked edge: only those can tell two orderings apart.")}
    return report


# ----------------------------------------------------------------------------- XR-05: mixing weights on validation
def mixing_grid(step: float) -> list[tuple[float, float, float]]:
    """Every (alpha, beta, gamma) on a `step` grid with alpha + beta + gamma = 1 (66 triples for 0.1)."""
    n = int(round(1 / step))
    return [(a / n, b / n, (n - a - b) / n) for a in range(n + 1) for b in range(n + 1 - a)]


def tune_mixing(cfg: dict, seeds) -> dict:
    """Choose (alpha, beta, gamma) on the VALIDATION split only (XR-05).

    For each detector seed: the validation rings (experiments_valrings, schema v2) are matched to the truth with
    the research side's matching on the `val` window; for every matched ring, w_loo comes from a NON-degraded
    leave-one-out rerun (val GFP + val embeddings) and the edge table is built under policy `converted`. Each
    grid triple orders the ring's in-window evidence edges by w_total; the objective is fidelity@k (k = 5),
    averaged over matched rings per seed, then over seeds. Ties (within 1e-12) go to the triple closest to the
    untuned default, then to the larger (alpha, beta). Nothing here opens a test-split file; every path read is
    recorded in the output."""
    from explainability.edge_weights import edge_weight_table, load_fx, load_loo_inputs, w_loo
    vi, ew, ev = cfg["val_inputs"], cfg["edge_weights"], cfg["evaluation"]
    k = int(ew["xr05_objective_k"])
    grid = mixing_grid(float(ew["grid_step"]))
    cfg_val = {**cfg, "evaluation": {**ev, "window": vi["window"]}}
    W = window_from_config(cfg_val)
    thr, scope = matching_rule(cfg)
    fx = load_fx(cfg)
    files_read, per_seed, max_ts = set(), {}, 0
    for s in seeds:
        scores, rings_path = vi["scored_edges"].format(seed=s), vi["rings"].format(seed=s)
        se = read_scored_edges(scores)
        rings = read_rings(rings_path, scored_edges=se)
        prov = provenance(se, rings)
        res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=cfg["inputs"]["truth"])
        T = truth_edge_sets(vi["split_parquet"], W, ring_ids=res.matches["truth_ring_id"])
        inc_of = lambda r: sorted(set(map(int, r.seed_edges)) | set(map(int, r.expanded_edges)))
        by_id = rings.set_index("ring_id")
        matched_ids = list(res.matches["ring_id"])
        ids = [e for rid in matched_ids for e in inc_of(by_id.loc[rid])]
        loo_in = load_loo_inputs(cfg, s, prov["aggregator_id"], rings_path, ids, split="val")
        files_read |= {scores, rings_path, vi["split_parquet"], cfg["inputs"]["truth"], loo_in.params.get("gfp", ""),
                       loo_in.params.get("embeddings", ""), cfg["amounts"]["fx_rates"]}
        sei = se.set_index("edge_id")
        conv = conversion_mask(se)
        in_win = in_window_edge_ids(se, W)
        rows, n_disc, n_repro = [], 0, 0
        for m in res.matches.itertuples(index=False):
            r = by_id.loc[m.ring_id]
            member = sei.loc[sorted(map(int, r.member_edges))].reset_index()
            max_ts = max(max_ts, int(member["timestamp"].max()))
            loo = w_loo(sei.loc[inc_of(r)].reset_index(), loo_in.rerunner, lambda_split=float(ew["lambda_split"]),
                        nan_policy=ew["loo_nan_policy"])
            n_repro += int(bool(loo["base_is_input"].iloc[0])) if len(loo) else 0
            evid, _ = evidence_edge_ids([e for e in r.member_edges if e in in_win], conv, "converted")
            Tm = T.edges[int(m.truth_ring_id)]
            keep = set(evid)
            n_disc += int(0 < len(keep & Tm) < len(keep))
            scores_k = []
            for a, b, g in grid:
                table = edge_weight_table(member, loo, {"alpha": a, "beta": b, "gamma": g},
                                          tol=float(ew["mixing_sum_tolerance"]), policy="converted", fx=fx)
                order = [e for e in table["edge_id"] if e in keep]
                scores_k.append(fidelity_at_k(order, Tm, k))
            rows.append(scores_k)
        arr = np.array(rows, dtype=float)
        per_seed[str(s)] = {"n_val_rings": len(rings), "n_matched": res.n_matched, "n_truth_in_scope": res.n_truth,
                            "n_rings_that_can_discriminate": n_disc, "n_rerun_reproduces_ring": n_repro,
                            "mean_by_triple": arr.mean(axis=0).tolist() if len(arr) else [None] * len(grid)}
    obj = np.nanmean(np.array([v["mean_by_triple"] for v in per_seed.values()], dtype=float), axis=0)
    d = np.array([float(np.linalg.norm(np.array(t) - np.array([ew["mixing_default"][x] for x in ("alpha", "beta", "gamma")])))
                  for t in grid])
    best = float(np.max(obj))
    tied = [i for i in range(len(grid)) if abs(obj[i] - best) < 1e-12]
    chosen = sorted(tied, key=lambda i: (round(d[i], 12), -grid[i][0], -grid[i][1]))[0]
    a, b, g = grid[chosen]
    return {"what": f"XR-05: (alpha, beta, gamma) chosen on VALIDATION fidelity@{k}; test split never read",
            "explainer_version": cfg["explainer_version"], "policy": "converted", "objective": f"fidelity@{k}",
            "window": W.as_dict(), "max_timestamp_read": max_ts, "files_read": sorted(f for f in files_read if f),
            "grid_step": float(ew["grid_step"]), "n_triples": len(grid),
            "grid": [{"alpha": t[0], "beta": t[1], "gamma": t[2], "objective": float(obj[i])} for i, t in enumerate(grid)],
            "per_seed": per_seed,
            "chosen": {"alpha": a, "beta": b, "gamma": g}, "chosen_objective": best,
            "n_triples_tied_at_best": len(tied),
            "default_objective": float(obj[int(np.argmin(d))]),
            "tie_break": "closest to the untuned default (0.4, 0.4, 0.2), then larger alpha, then larger beta"}


# ----------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", choices=["test", "val"], default="test",
                    help="test = the reporting split; val = the validation rings (only for choosing settings)")
    ap.add_argument("--policy", choices=["converted", "raw"], default=cfg["amounts"]["currency_policy"],
                    help="converted = conversions dropped from evidence; raw = reproduce Week 1 exactly")
    ap.add_argument("--scores", default=None, help="scored_edges parquet; '{seed}' is filled in")
    ap.add_argument("--rings", default=None, help="rings parquet; '{seed}' is filled in")
    ap.add_argument("--truth", default=cfg["inputs"]["truth"])
    ap.add_argument("--split-parquet", default=None)
    ap.add_argument("--window", default=None, help="name in configs/eval_window.yaml")
    ap.add_argument("--seeds", type=int, nargs="+", default=cfg["inputs"]["seeds"])
    ap.add_argument("--out", default=cfg["output_dir"])
    ap.add_argument("--name", default=None, help="output file name; '{seed}' is filled in")
    ap.add_argument("--compare-policies", action="store_true",
                    help="write the Week 2 (raw) vs migrated (converted) comparison report and stop")
    ap.add_argument("--tune-mixing", action="store_true",
                    help="XR-05: choose (alpha, beta, gamma) on the VALIDATION split, write the choice file and stop")
    ap.add_argument("--explanations", default=None,
                    help="explanations parquet ('{seed}' filled in): adds the w_total ranking it contains")
    a = ap.parse_args(argv)
    if a.tune_mixing:
        rep = tune_mixing(cfg, a.seeds)
        path = write_json(rep, repo_path(a.out) / cfg["xr05_choice_name"])
        print(f"chosen {rep['chosen']} (validation fidelity@5 {rep['chosen_objective']:.4f}; default "
              f"{rep['default_objective']:.4f}; {rep['n_triples_tied_at_best']} triple(s) tied at the best)")
        for s, v in rep["per_seed"].items():
            print(f"  seed {s}: {v['n_matched']} matched val rings, {v['n_rings_that_can_discriminate']} can discriminate, "
                  f"rerun reproduces {v['n_rerun_reproduces_ring']}")
        print(f"-> {_rel(path)}")
        return 0
    if a.compare_policies:
        rep = compare_policies(cfg, a.seeds, a.out)
        path = write_json(rep, repo_path(a.out) / cfg["migration_report_name"])
        print(json.dumps(rep["pooled"], indent=2))
        print(f"-> {_rel(path)}")
        return 0
    inp = cfg["inputs"] if a.split == "test" else cfg["val_inputs"]
    a.scores = a.scores or inp["scored_edges"]
    a.rings = a.rings or inp["rings"]
    a.split_parquet = a.split_parquet or inp["split_parquet"]
    cfg["evaluation"]["window"] = a.window or (cfg["evaluation"]["window"] if a.split == "test" else inp["window"])
    if a.name is None:
        a.name = (cfg["output_name"] if (a.split, a.policy) == ("test", "raw") else
                  cfg["output_name_converted"] if a.split == "test" else f"fidelity_val_{a.policy}_seed{{seed}}.json")
    ks = cfg["evaluation"]["k"]
    print(f"[{a.split}, policy {a.policy}]")
    names = ["score_only"] + (["w_total"] if a.explanations else []) + ["random"]
    print(f"{'seed':>4}  {'rings':>5}  {'matched':>7}  " + "  ".join(f"{n}@{k}".rjust(14) for n in names for k in ks))
    for s in a.seeds:
        pre = None
        if a.explanations:
            import pyarrow.parquet as pq
            rows = pq.read_table(repo_path(a.explanations.format(seed=s)), columns=["ring_id", "edge_weights"]).to_pylist()
            pre = {"w_total": {r["ring_id"]: [e["edge_id"] for e in r["edge_weights"]] for r in rows}}
        out = evaluate_seed(cfg, s, scores=a.scores.format(seed=s), rings_path=a.rings.format(seed=s),
                            truth=a.truth, split_parquet=a.split_parquet, policy=a.policy, precomputed=pre)
        path = write_json(out, repo_path(a.out) / a.name.format(seed=s))
        f, c = out["fidelity"], out["counts"]
        print(f"{s:>4}  {c['n_pred_total']:>5}  {c['n_matched']:>7}  "
              + "  ".join(f"{f[n][str(k)]:14.4f}" for n in names for k in ks) + f"  -> {_rel(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
