"""Explanation fidelity (spec section 6.1-6.2, minimal Week 1 version: XR-22 point estimates, XR-24 controls).

    python -m explainability.evaluate                       # all seeds in config.yaml, primary window
    python -m explainability.evaluate --week4               # Week 4: results/xai/fidelity.json (CIs, controls, XR-23)
    python -m explainability.evaluate --typology            # Week 5: results/xai/typology_eval.json (XR-25)
    python -m explainability.evaluate --roles               # Week 5: XR-26 role accuracy, added to fidelity.json
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

from explainability.contract_io import (REPO_ROOT, detector_cfg, load_config, load_research_config, provenance,
                                        read_rings, read_scored_edges, repo_path)
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


# ----------------------------------------------------------------------------- Week 4: fidelity.json
RANKS_W4 = ("w_total", "score_only", "random")


def expanded_rows(scored_edges: pd.DataFrame, rings: pd.DataFrame, match_result, truth_edges, window, cfg: dict,
                  detector_seed: int, orders: dict) -> list[dict]:
    """XR-23 per matched ring-instance (Joan, Q3). X = the ring's expanded edges inside the window, conversions removed.
      (b) expanded recall@k (headline): of the TRUE expanded edges (X & T), how many are in the top k of the FULL
          member ranking, / min(k, |X & T|). Asks: does the ranking put the recovered quiet-member edges near the top?
      (c) literal: rank X alone against T's non-seed edges (spec 6.1 wording); few rings can discriminate.
      (a) expanded precision |X & T| / |X|: context -- it measures the ring layer, not the explanation."""
    ev = cfg["evaluation"]
    ks = [int(k) for k in ev["k"]]
    in_win = in_window_edge_ids(scored_edges, window)
    conv = conversion_mask(scored_edges)
    se = scored_edges.set_index("edge_id")
    ring_by_id = rings.set_index("ring_id")
    out = []
    for i, m in enumerate(match_result.matches.itertuples(index=False)):
        r = ring_by_id.loc[m.ring_id]
        member, _ = evidence_edge_ids([int(e) for e in r["member_edges"] if e in in_win], conv, "converted")
        X, _ = evidence_edge_ids([int(e) for e in r["expanded_edges"] if e in in_win], conv, "converted")
        T = truth_edges.edges[int(m.truth_ring_id)]
        XT = set(X) & T
        T_nonseed = {e for e in T if e in se.index and not bool(se.at[e, "is_seed"])}
        row = {"ring_id": m.ring_id, "truth_ring_id": int(m.truth_ring_id), "n_expanded": len(X),
               "n_expanded_true": len(XT), "precision": (len(XT) / len(X)) if X else None,
               "c_defined": bool(X) and bool(set(X) & T_nonseed),
               "c_discriminates": bool(set(X) & T_nonseed) and len(set(X) & T_nonseed) < len(X)}
        edges = se.loc[sorted(member)].reset_index()
        ranked = {"w_total": [e for e in orders[m.ring_id] if e in set(member)], "score_only": rank_by_score(edges)}
        salt = [int(ev["random_seed"]), int(detector_seed), i, 23]
        if XT:
            for name, order in ranked.items():
                for k in ks:
                    row[f"b_{name}@{k}"] = fidelity_at_k(order, XT, k)
            rnd = random_fidelity(member, XT, ks, int(ev["random_shuffles"]), salt)
            for k in ks:
                row[f"b_random@{k}"] = rnd[k]
        if row["c_defined"]:
            xs = set(X)
            for name, order in ranked.items():
                for k in ks:
                    row[f"c_{name}@{k}"] = fidelity_at_k([e for e in order if e in xs], T_nonseed, k)
            rnd = random_fidelity(X, T_nonseed, ks, int(ev["random_shuffles"]), salt + [3])
            for k in ks:
                row[f"c_random@{k}"] = rnd[k]
        out.append(row)
    return out


def _block(rows: pd.DataFrame, prefix: str, cfg: dict, label: str) -> dict:
    """Per truth ring (mean over the seeds where it is in `rows`): CIs for the three rankings at every k, the six
    paired comparisons of w_total against each control (Holm over the six), the spec's k=5 non-overlap verdict."""
    from explainability.stats import bootstrap_mean, holm, non_overlap_verdict, paired_test, per_truth_ring
    ev = cfg["evaluation"]
    ks = [int(k) for k in ev["k"]]
    nb, npm, sd, ci = int(ev["bootstrap_resamples"]), int(ev["permutation_resamples"]), int(ev["stats_seed"]), float(ev["ci"])
    if rows.empty:
        return {"label": label, "n_ring_instances": 0, "n_truth_rings": 0}
    vals, seeds = {}, None
    for name in RANKS_W4:
        for k in ks:
            col = f"{prefix}{name}@{k}"
            per_seed = [dict(zip(g["truth_ring_id"], g[col])) for _, g in rows.groupby("seed", sort=True)]
            vals[(name, k)], seeds = per_truth_ring(per_seed)
    table = {name: {str(k): {**bootstrap_mean(vals[(name, k)], n_resamples=nb, seed=sd, ci=ci),
                             "ring_instance_mean": float(rows[f"{prefix}{name}@{k}"].mean())} for k in ks}
             for name in RANKS_W4}
    comps = {}
    for control in ("score_only", "random"):
        for k in ks:
            comps[f"w_total vs {control} @{k}"] = paired_test(vals[("w_total", k)], vals[(control, k)],
                                                              n_permutations=npm, seed=sd, ci=ci)
    for h in holm([(n, c["p_value"]) for n, c in comps.items()]):
        comps[h["comparison"]].update(p_holm=h["p_holm"], reject_at_05=h["reject_at_05"])
    vk = str(int(ev["verdict_k"]))
    verdict = {c: non_overlap_verdict(table["w_total"][vk], table[c][vk]) for c in ("score_only", "random")}
    return {"label": label, "n_ring_instances": int(len(rows)), "n_truth_rings": len(vals[("w_total", ks[0])]),
            "truth_rings_by_n_seeds_matched": seeds, "fidelity": table, "comparisons": comps,
            "holm_family": "the six comparisons of this block (2 controls x 3 k)",
            f"verdict_at_k{vk}": verdict,
            "overall": "positive" if all(v == "positive" for v in verdict.values()) else "negative"}


def week4_report(cfg: dict, seeds) -> dict:
    """XR-22/23/24 pooled over the detector seeds, on the primary window, policy converted, w_total from the Week 3
    explanations (mixing tuned on validation; NOT re-tuned). Joan's decisions Q1-Q4 (2026-10)."""
    import pyarrow.parquet as pq
    ev = cfg["evaluation"]
    ks = [int(k) for k in ev["k"]]
    W = window_from_config(cfg)
    thr, scope = matching_rule(cfg)
    inp, out_dir = cfg["inputs"], repo_path(cfg["output_dir"])
    head, expd, per_seed, files = [], [], {}, []
    for s in seeds:
        scores, rings_path = inp["scored_edges"].format(seed=s), inp["rings"].format(seed=s)
        expl = out_dir / cfg["explanations_name_week3"].format(seed=s)
        files += [_rel(scores), _rel(rings_path), _rel(expl)]
        se = read_scored_edges(scores)
        rings = read_rings(rings_path, scored_edges=se)
        res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=inp["truth"])
        T = truth_edge_sets(inp["split_parquet"], W, ring_ids=res.matches["truth_ring_id"])
        orders = {r["ring_id"]: [e["edge_id"] for e in r["edge_weights"]]
                  for r in pq.read_table(expl, columns=["ring_id", "edge_weights"]).to_pylist()}
        pr, summ = evaluate_frames(se, rings, res, T, W, cfg, s, policy="converted", precomputed={"w_total": orders})
        head.append(pr.assign(seed=s))
        expd.append(pd.DataFrame(expanded_rows(se, rings, res, T, W, cfg, s, orders)).assign(seed=s))
        per_seed[str(s)] = {"n_matched": int(len(pr)), "fidelity": summ}
    head, expd = pd.concat(head, ignore_index=True), pd.concat(expd, ignore_index=True)
    files += [_rel(inp["truth"]), _rel(inp["split_parquet"])]
    sat = head["n_true_among_ranked"] == head["n_edges_ranked"]
    some_true = head["n_true_among_ranked"] > 0
    nonsat = head[some_true & ~sat]
    xr05 = json.loads((out_dir / cfg["xr05_choice_name"]).read_text(encoding="utf-8"))
    val_n = sum(v["n_matched"] for v in xr05["per_seed"].values())
    val_disc = sum(v["n_rings_that_can_discriminate"] for v in xr05["per_seed"].values())
    objs = [g["objective"] for g in xr05["grid"]]
    b_rows = expd[expd["n_expanded_true"] > 0]
    c_rows = expd[expd["c_defined"]]
    with_x = expd[expd["n_expanded"] > 0]
    return {
        "experiment_id": "XAI-W4", "explainer_version": cfg["explainer_version"],
        "what": "explanation fidelity with 95% bootstrap CIs over truth rings (XR-22), expanded-edge fidelity (XR-23), "
                "random and score-only controls with paired tests (XR-24); primary window; pooled over detector seeds",
        "inputs": {"files_read": files, "xr05_choice": _rel(out_dir / cfg["xr05_choice_name"])},
        "evaluation": {"window": "primary", "scope": scope, "match_threshold": thr, "k": ks, "policy": "converted",
                       "ranked_edges": "ring member_edges inside the window, currency conversions removed",
                       "unit": "truth ring; its value = mean over the detector seeds in which it was matched (Joan, Q2)",
                       "bootstrap_resamples": int(ev["bootstrap_resamples"]), "ci": float(ev["ci"]),
                       "permutation_resamples": int(ev["permutation_resamples"]), "stats_seed": int(ev["stats_seed"]),
                       "random_shuffles": int(ev["random_shuffles"]), "mixing": cfg["edge_weights"]["mixing_tuned"],
                       "mixing_retuned_on_test": False, "seeds": [int(s) for s in seeds]},
        "headline": _block(head, "", cfg, "fidelity@k on ring member edges (spec 6.1 definition)"),
        "secondary_non_saturated": _block(nonsat, "", cfg, "the same, on ring-instances whose ranked edges are neither "
                                                           "all true nor all false (the only ones where order matters)"),
        "xr23": {
            "headline_b_expanded_recall": _block(b_rows, "b_", cfg, "expanded recall@k: true expanded edges in the top k "
                                                                     "of the full member ranking / min(k, their number)"),
            "c_literal": {**_block(c_rows, "c_", cfg, "spec wording: rank expanded edges only, against the truth ring's "
                                                      "non-seed edges"),
                          "n_ring_instances_that_discriminate": int(expd["c_discriminates"].sum())},
            "a_expanded_precision": {"what": "share of expanded in-window edges that are truly in the ring; measures the "
                                             "ring layer (L3), not the explanation",
                                     "n_ring_instances_with_expanded_edges": int(len(with_x)),
                                     "mean": float(with_x["precision"].mean()) if len(with_x) else None,
                                     "pooled": float(with_x["n_expanded_true"].sum() / with_x["n_expanded"].sum())
                                     if len(with_x) else None}},
        "findings": {
            "saturation": {"n_matched_ring_instances": int(len(head)),
                           "n_with_a_true_ranked_edge": int(some_true.sum()),
                           "n_only_true_edges": int((sat & some_true).sum()),
                           "n_no_true_ranked_edge": int((~some_true).sum()),
                           "n_non_saturated": int(len(nonsat)),
                           "reading": "after removing currency conversions most matched predicted rings contain only "
                                      "true transactions: the rings are very clean, and fidelity cannot separate "
                                      "rankings on them (Joan, Q1-i)"},
            "xr05_strength": {"chosen": xr05["chosen"], "validation_objective_chosen": xr05["chosen_objective"],
                              "validation_objective_default": xr05["default_objective"],
                              "grid_objective_range": [min(objs), max(objs)],
                              "n_validation_ring_instances_matched": val_n,
                              "n_validation_ring_instances_that_can_discriminate": val_disc,
                              "leave_one_out_weight": xr05["chosen"]["beta"],
                              "reading": f"the mixing weights were chosen on validation where only {val_disc} of "
                                         f"{val_n} matched ring-instances could discriminate, and the whole grid spans "
                                         f"{max(objs) - min(objs):.3f}: the choice is weakly determined. Leave-one-out "
                                         f"got zero weight (beta = {xr05['chosen']['beta']}). The weights were not "
                                         f"re-tuned on test (Joan, Q1-ii)."}},
        "per_seed": per_seed,
    }


# ----------------------------------------------------------------------------- Week 5: typology_eval.json (XR-25)
SHAPE_CLAUSES = ("fan_out", "fan_in", "gather_scatter", "scatter_gather", "cycle", "stack", "bipartite")


def typing_rows(cfg: dict, seeds, window_name: str, *, mapping: str = "by_name") -> pd.DataFrame:
    """One row per matched ring: true pattern type, the narrated type (the ring's topology_type, as the explanation
    states it) and the research rule scorer's type, as in evaluation/typing_eval.py.

    mapping "by_name"   the matched prediction is found by ring id (match.match_in_window keeps names aligned).
    mapping "position"  research's typing_eval.py lookup, rings[m.pred_idx] on restrict_rings positions. restrict_rings
                        drops rings with no edge in the window, so on the primary window the positions shift and the
                        wrong ring is typed. Kept ONLY to show that it reproduces r5_typing.json exactly."""
    from contract.make_scored_edges import load_paths
    from evaluation.ring_metrics import match_rings
    from ringshield.evaluate import restrict_rings
    from ringshield.rings import read_rings_parquet
    from ringshield.roles import account_roles
    from ringshield.truth import load_ground_truth
    from ringshield.typing.features import ring_features
    from ringshield.typing.rules import rule_type
    from ringshield.windows import load_windows
    W = load_windows(repo_path(cfg["research_configs"]["eval_window"]))[window_name]
    thr, scope = matching_rule(cfg)
    truth, patterns = load_ground_truth(load_paths()["processed_dir"] / "amlworld_ring_ground_truth.parquet",
                                        *W.bounds, scope, verbose=False)
    rows = []
    for s in seeds:
        rings_path = cfg["inputs"]["rings"].format(seed=s)
        recs = read_rings_parquet(repo_path(rings_path))
        se = read_scored_edges(cfg["inputs"]["scored_edges"].format(seed=s))
        sei = se.set_index("edge_id")
        if mapping == "position":
            in_win = set(se.loc[W.mask(se["timestamp"].to_numpy()), "edge_id"])
            kept = [r for r in recs if any(e in in_win for e in r.member_edges)]   # what restrict_rings kept
            ms = match_rings(restrict_rings(recs, se, W), truth, thr)[0]
            pairs = [(recs[m.pred_idx], m.truth_id) for m in ms]
            correct = [kept[m.pred_idx].ring_id for m in ms]
        else:
            by_id = {r.ring_id: r for r in recs}
            res = match_in_window(read_rings(rings_path, scored_edges=se), se, W, threshold=thr, scope=scope,
                                  truth=truth, patterns=patterns)
            pairs = [(by_id[m.ring_id], int(m.truth_ring_id)) for m in res.matches.itertuples(index=False)]
        for j, (r, tid) in enumerate(pairs):
            inc = sorted(set(r.seed_edges + r.expanded_edges))
            f = ring_features(sei.loc[inc].reset_index(), account_roles(r, se), seed_ratio=len(r.seed_edges) / max(len(inc), 1))
            rows.append({"seed": s, "ring_id": r.ring_id, "truth_ring": int(tid), "true_type": patterns.get(tid, "?"),
                         "head_type": r.topology_type, "rule_type": rule_type(f),
                         "matched_ring_id": correct[j] if mapping == "position" else r.ring_id})
    return pd.DataFrame(rows)


def typing_metrics(d: pd.DataFrame, n_bootstrap: int, rng_seed: int) -> dict:
    """Accuracy with research's bootstrap over matched rings (typing_eval.py `boot`, same draws), macro-F1,
    per-class recall and the 8x8 confusion matrices -- the r5_typing.json fields."""
    from sklearn.metrics import f1_score
    from contract.schema import TOPOLOGY_TYPES
    from ringshield.typing.head import confusion

    def boot(col):
        ok = (d[col].to_numpy() == d["true_type"].to_numpy()).astype(float)
        rng = np.random.default_rng(rng_seed)
        draws = ok[rng.integers(0, len(ok), (n_bootstrap, len(ok)))].mean(axis=1)
        return {"point": float(ok.mean()), "lo": float(np.percentile(draws, 2.5)), "hi": float(np.percentile(draws, 97.5)),
                "n": int(len(ok))}
    return {
        "n_matched_rings": int(len(d)), "head": boot("head_type"), "rule": boot("rule_type"),
        "head_macro_f1": float(f1_score(d.true_type, d.head_type, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
        "rule_macro_f1": float(f1_score(d.true_type, d.rule_type, average="macro", labels=TOPOLOGY_TYPES, zero_division=0)),
        "per_class": {t: {"n": int((d.true_type == t).sum()),
                          "head_recall": float((d.loc[d.true_type == t, "head_type"] == t).mean()) if (d.true_type == t).any() else None,
                          "rule_recall": float((d.loc[d.true_type == t, "rule_type"] == t).mean()) if (d.true_type == t).any() else None}
                      for t in TOPOLOGY_TYPES},
        "head_confusion": json.loads(confusion(list(d.true_type), list(d.head_type)).to_json(orient="split")),
        "rule_confusion": json.loads(confusion(list(d.true_type), list(d.rule_type)).to_json(orient="split")),
        "per_seed": {str(s): {"n_matched": int(len(g)), "head_accuracy": float((g.head_type == g.true_type).mean()),
                              "rule_accuracy": float((g.rule_type == g.true_type).mean())}
                     for s, g in d.groupby("seed")}}


def typology_report(cfg: dict, seeds) -> dict:
    """XR-25: accuracy of the narrated topology_type against the true pattern type on matched rings (Joan, Q1).
    Headline on the primary window with matches found by ring id; the whole test period as the window sensitivity;
    the shape-sentence split from the Week 3 narratives; and the reproduction of research's r5_typing.json."""
    import pyarrow.parquet as pq
    nb, sd = 1000, 0                                   # research's typing_eval.py defaults, so the CIs are comparable
    prim = typing_rows(cfg, seeds, "primary")
    whole = typing_rows(cfg, seeds, "whole")
    shipped = cfg.get("detector", "gine_causal") == "gine_causal"     # r5_typing.json exists only for it
    legacy = typing_rows(cfg, seeds, "primary", mapping="position") if shipped else None
    out_dir = repo_path(cfg["output_dir"])
    shape = {}
    for s in seeds:
        for r in pq.read_table(out_dir / cfg["explanations_name_week3"].format(seed=s),
                               columns=["ring_id", "evidence_summary"]).to_pylist():
            shape[(s, r["ring_id"])] = bool(set(json.loads(r["evidence_summary"])["clauses"]) & set(SHAPE_CLAUSES))
    prim["shape_sentence"] = [shape[(s, rid)] for s, rid in zip(prim["seed"], prim["ring_id"])]
    split = {}
    for flag, g in prim.groupby("shape_sentence"):
        split["stated" if flag else "not_stated"] = {"n": int(len(g)),
                                                     "narrated_type_accuracy": float((g.head_type == g.true_type).mean())}
    r5 = json.loads(repo_path("results/tables/r5_typing.json").read_text(encoding="utf-8")) if shipped else None
    n_wrong = int((legacy["ring_id"] != legacy["matched_ring_id"]).sum()) if shipped else None
    head_prim = typing_metrics(prim, nb, sd)
    head_whole = typing_metrics(whole, nb, sd)
    return {
        "experiment_id": "XAI-W5", "explainer_version": cfg["explainer_version"],
        "what": "XR-25: accuracy of the narrated topology type (the ring's topology_type, Step 8 typing head) and of the "
                "research rule scorer against the true pattern type, on matched rings; 8x8 confusion; per-type recall",
        "status": "headline uses matches found by ring id; differs from research's r5_typing.json, whose primary-window "
                  "rows type the wrong ring (see reproduction_of_r5_typing) -- pending Joan's confirmation",
        "evaluation": {"seeds": [int(s) for s in seeds], "scope": "test_visible", "match_threshold": matching_rule(cfg)[0],
                       "bootstrap": f"over matched rings, {nb} resamples, rng seed {sd} (research's typing_eval.py)",
                       "rule_type": "ringshield.typing.rules.rule_type on ring_features(included edges, account_roles raw)"},
        "primary": head_prim,
        "whole_test_period": head_whole,
        "shape_sentence_split": {"what": "narrated-type accuracy on matched primary-window rings, by whether the Week 3 "
                                         "narrative states a shape sentence (one that holds on the ring's transactions)",
                                 **split},
        "detector": cfg.get("detector", "gine_causal"),
        "reproduction_of_r5_typing": None if not shipped else {
            "what": "research's evaluation/typing_eval.py looks the matched ring up as rings[m.pred_idx], but the "
                    "positions index restrict_rings' output, which drops rings with no edge in the window; on the "
                    "primary window 72 rings are dropped and the lookup shifts. With that lookup we reproduce "
                    "r5_typing.json exactly; with the lookup by ring id the numbers are the 'primary' block above.",
            "position_lookup": {"head_accuracy": float((legacy.head_type == legacy.true_type).mean()),
                                "rule_accuracy": float((legacy.rule_type == legacy.true_type).mean()),
                                "n": int(len(legacy))},
            "r5_typing_json": {"head_accuracy": r5["pooled"]["head_accuracy"], "rule_accuracy": r5["pooled"]["rule_accuracy"],
                               "n": r5["n_matched_rings_total"]},
            "n_rows_typing_a_different_ring_than_matched": n_wrong,
            "whole_window_unaffected": "no ring is dropped on the whole test period, so both lookups agree there"},
        "caveats": {
            "window": f"primary {head_prim['head']['point']:.3f} vs whole test period {head_whole['head']['point']:.3f} "
                      f"(same classifier): with the lookup by ring id typing is NOT strongly window-bounded; the 0.219 "
                      f"vs 0.594 gap in docs/TYPING.md comes from the shifted lookup",
            "raw_roles": "the typing head's role-count features were built on raw (cross-currency) roles "
                         "(docs/PITFALLS.md, 'What it reached'); the narrated roles are currency-converted"},
    }


# ----------------------------------------------------------------------------- Week 5: role accuracy (XR-26)
ROLE_NAMES = ("source", "sink", "mule", "holder", "peripheral", "undetermined")
ROLE_VARIANTS = {
    "headline": "our roles over the ring's seed + expanded edges (conversions removed), vs the truth ring's roles over "
                "its in-window edges; accounts in only one of the two rings count as errors (spec 6.5)",
    "in_window": "the same, our roles recomputed on the ring's in-window seed + expanded edges only -- separates the "
                 "time-window effect from membership errors",
    "accounts_in_both": "per-role agreement on accounts present in BOTH rings only -- pure role errors, no membership "
                        "errors (Joan, Q2)",
}


def _role_counts(pred: dict, truth: dict) -> dict:
    """{role: (correct, predicted with that role, true with that role)}; an account missing on one side has no role
    there, so it can only be wrong for the side that has it."""
    out = {}
    for r in ROLE_NAMES:
        p = {a for a, d in pred.items() if d["role"] == r}
        t = {a for a, d in truth.items() if d["role"] == r}
        out[r] = (len(p & t), len(p), len(t))
    return out


def role_rows(cfg: dict, seeds, *, inputs: dict | None = None, explanations_name: str | None = None) -> pd.DataFrame:
    """One row per (matched ring-instance, variant, role) with correct / predicted / true counts, plus the number of
    accounts whose recomputed role differs from the role shipped in the explanation. Roles everywhere come from
    research's roles_for_edges(currency="converted") -- one code path for both sides (Joan, Q2)."""
    import pyarrow.parquet as pq
    from ringshield.typing.truth_rings import roles_for_edges
    inp = inputs or cfg["inputs"]
    expl_name = explanations_name or cfg["explanations_name_week3"]
    roles_cfg = load_research_config(cfg, "roles")
    W = window_from_config(cfg)
    thr, scope = matching_rule(cfg)
    out = []
    for s in seeds:
        se = read_scored_edges(inp["scored_edges"].format(seed=s))
        rings = read_rings(inp["rings"].format(seed=s), scored_edges=se)
        res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=inp["truth"])
        T = truth_edge_sets(inp["split_parquet"], W, ring_ids=res.matches["truth_ring_id"])
        in_win = in_window_edge_ids(se, W)
        conv = conversion_mask(se)
        sei = se.set_index("edge_id")
        shipped = {r["ring_id"]: {a["account_id"]: a["role"] for a in r["account_weights"]}
                   for r in pq.read_table(repo_path(cfg["output_dir"]) / expl_name.format(seed=s),
                                          columns=["ring_id", "account_weights"]).to_pylist()}
        ring_by_id = rings.set_index("ring_id")

        def roles(ids):
            ids = sorted(ids)
            return roles_for_edges(sei.loc[ids].reset_index(), roles_cfg, currency="converted") if ids else {}
        for m in res.matches.itertuples(index=False):
            r = ring_by_id.loc[m.ring_id]
            inc = [int(e) for e in set(r["seed_edges"]) | set(r["expanded_edges"]) if not conv.loc[int(e)]]
            truth = roles(T.edges[int(m.truth_ring_id)])
            pred = roles(inc)
            pred_win = roles([e for e in inc if e in in_win])
            both = set(pred) & set(truth)
            ship = shipped[m.ring_id]
            n_diff = sum(1 for a in pred if a in ship and ship[a] != pred[a]["role"])
            base = {"seed": s, "ring_id": m.ring_id, "truth_ring_id": int(m.truth_ring_id),
                    "n_pred_accounts": len(pred), "n_truth_accounts": len(truth), "n_both": len(both),
                    "n_recomputed_differs_from_shipped": n_diff}
            for variant, (p, t) in {"headline": (pred, truth), "in_window": (pred_win, truth),
                                    "accounts_in_both": ({a: pred[a] for a in both}, {a: truth[a] for a in both})}.items():
                for role, (c, np_, nt) in _role_counts(p, t).items():
                    out.append({**base, "variant": variant, "role": role, "correct": c, "predicted": np_, "true": nt})
    return pd.DataFrame(out)


def role_accuracy_block(cfg: dict, seeds, **kw) -> dict:
    """XR-26 for fidelity.json: per variant and role, precision = correct / predicted and recall = correct / true,
    pooled over truth rings (each truth ring = mean of its counts over the seeds where it was matched), with percentile
    bootstrap intervals over truth rings (stats.bootstrap_ratio, Week 4 draws)."""
    from explainability.stats import bootstrap_ratio, per_truth_ring
    ev = cfg["evaluation"]
    nb, sd, ci = int(ev["bootstrap_resamples"]), int(ev["stats_seed"]), float(ev["ci"])
    rows = role_rows(cfg, seeds, **kw)
    first = rows[(rows.variant == "headline") & (rows.role == ROLE_NAMES[0])]
    out = {"what": "XR-26 role precision / recall of the narrated (converted) roles against roles derived from the "
                   "truth ring's in-window edges with the same algorithm (ringshield roles_for_edges, converted)",
           "unit": "truth ring; counts averaged over the detector seeds in which it was matched",
           "n_ring_instances": int(len(first)),
           "n_truth_rings": int(first["truth_ring_id"].nunique()),
           "shipped_vs_recomputed": {"n_accounts_compared": int(first["n_pred_accounts"].sum()),
                                     "n_role_differs": int(first["n_recomputed_differs_from_shipped"].sum()),
                                     "why": "the shipped roles include the 33 currency conversions the ring-builder "
                                            "used; the evaluation removes them on both sides (Joan, Q2)"},
           "variants": {}}
    for variant, desc in ROLE_VARIANTS.items():
        g = rows[rows.variant == variant]
        block = {"what": desc, "per_role": {}}
        for role in ROLE_NAMES:
            h = g[g.role == role]
            per_seed = lambda col: [dict(zip(x["truth_ring_id"], x[col])) for _, x in h.groupby("seed", sort=True)]
            corr, _ = per_truth_ring(per_seed("correct"))
            pred, _ = per_truth_ring(per_seed("predicted"))
            true, _ = per_truth_ring(per_seed("true"))
            block["per_role"][role] = {
                "precision": bootstrap_ratio(corr, pred, n_resamples=nb, seed=sd, ci=ci),
                "recall": bootstrap_ratio(corr, true, n_resamples=nb, seed=sd, ci=ci),
                "n_predicted": int(h["predicted"].sum()), "n_true": int(h["true"].sum()),
                "n_correct": int(h["correct"].sum())}
        if variant == "accounts_in_both":
            n_both = int(rows[(rows.variant == variant) & (rows.role == ROLE_NAMES[0])]["n_both"].sum())
            block["n_accounts"] = n_both
            block["agreement"] = (float(g["correct"].sum()) / n_both) if n_both else None
        out["variants"][variant] = block
    return out


# ----------------------------------------------------------------------------- Week 5: XR-36 summary
def detectors_summary(cfg: dict, seeds) -> dict:
    """XR-36: one table over every detector profile, read from the files each detector's run wrote with the SAME code
    (explain, evaluate --week4 / --typology / --roles with --detector). Nothing is recomputed here."""
    import pyarrow.parquet as pq
    out_dir = repo_path(cfg["output_dir"])
    rows = {}
    for d in cfg["detectors"]:
        dc = detector_cfg(cfg, d)
        logs = [json.loads((out_dir / (dc["explanations_name_week3"].format(seed=s) + ".log.json")).read_text(encoding="utf-8"))
                for s in seeds]
        first = pq.read_table(out_dir / dc["explanations_name_week3"].format(seed=seeds[0]), columns=["provenance"])
        prov = json.loads(first.column("provenance")[0].as_py())
        fid = json.loads((out_dir / dc["fidelity_week4_name"]).read_text(encoding="utf-8"))
        typ = json.loads((out_dir / dc["typology_name"]).read_text(encoding="utf-8"))
        h = fid["headline"]["fidelity"]
        ra = fid.get("role_accuracy")
        rows[d] = {
            "label": cfg["detectors"][d]["label"],
            "inputs": {"scored_edges": dc["inputs"]["scored_edges"], "rings": dc["inputs"]["rings"],
                       "embeddings": dc["research_inputs"]["embeddings"], "affinity_dir": dc["research_inputs"]["affinity_dir"],
                       "partition": prov["rerun"].get("partition_config")},
            "mixing": prov["mixing"], "mixing_source": prov["mixing_source"],
            "n_rings": sum(l["n_rings"] for l in logs), "n_explained": sum(l["n_explained"] for l in logs),
            "n_degraded": 0,      # a degraded rerun raises (edge_weights.LooInputs.rerunner); every ring was explained
            "n_reproduces_shipped_ring": sum(l["n_reproduces_shipped_ring"] for l in logs),
            "latency_p95_ms": max(l["latency_ms"]["p95"] for l in logs),
            "latency_max_ms": max(l["latency_ms"]["max"] for l in logs),
            "n_matched_ring_instances": fid["headline"]["n_ring_instances"], "n_truth_rings": fid["headline"]["n_truth_rings"],
            "fidelity_at5": {k: h[k]["5"]["point"] for k in ("w_total", "score_only", "random")},
            "fidelity_at5_ci": {k: [h[k]["5"]["lo"], h[k]["5"]["hi"]] for k in ("w_total", "score_only", "random")},
            "verdict": fid["headline"]["overall"],
            "saturation": fid["findings"]["saturation"],
            "expanded_recall_at5": {k: v["5"]["point"] for k, v in
                                    fid["xr23"]["headline_b_expanded_recall"].get("fidelity", {}).items()},
            "typing_accuracy_primary": typ["primary"]["head"]["point"],
            "rule_accuracy_primary": typ["primary"]["rule"]["point"],
            "role_agreement_accounts_in_both": None if ra is None else ra["variants"]["accounts_in_both"]["agreement"],
        }
    return {"experiment_id": "XAI-W5", "explainer_version": cfg["explainer_version"],
            "what": "XR-36: the same layer run unchanged on every detector's contract files; per detector, what was read "
                    "and the headline results (latency p95 = the worst seed's p95)",
            "same_code": "explainability/ unchanged between detectors; only contract_io.detector_cfg swaps the inputs",
            "detectors": rows}


# ----------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--detector", default="gine_causal")
    cfg = detector_cfg(load_config(), pre.parse_known_args(argv)[0].detector)
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
    ap.add_argument("--week4", action="store_true",
                    help="write results/xai/fidelity.json: CIs, controls, paired tests, XR-23 (pooled over seeds) and stop")
    ap.add_argument("--typology", action="store_true", help="write results/xai/typology_eval.json (XR-25) and stop")
    ap.add_argument("--detector", default="gine_causal",
                    help="XR-36: which detector's files (a profile under `detectors` in config.yaml)")
    ap.add_argument("--detectors-summary", action="store_true",
                    help="XR-36: write results/xai/xr36_detectors.json from every detector's output files and stop")
    ap.add_argument("--roles", action="store_true",
                    help="add XR-26 role accuracy to results/xai/fidelity.json (other sections untouched) and stop")
    a = ap.parse_args(argv)
    if a.detectors_summary:
        rep = detectors_summary(load_config(), a.seeds)
        path = write_json(rep, repo_path(a.out) / cfg["detectors_summary_name"])
        for d, v in rep["detectors"].items():
            print(f"{d}: {v['n_explained']}/{v['n_rings']} explained, degraded {v['n_degraded']}, p95 {v['latency_p95_ms']:.0f} ms, "
                  f"fidelity@5 w_total {v['fidelity_at5']['w_total']:.3f} score {v['fidelity_at5']['score_only']:.3f} "
                  f"random {v['fidelity_at5']['random']:.3f} ({v['verdict']}); typing {v['typing_accuracy_primary']:.3f}")
        print(f"-> {_rel(path)}")
        return 0
    if a.roles:
        path = repo_path(a.out) / cfg["fidelity_week4_name"]
        rep = json.loads(path.read_text(encoding="utf-8"))
        rep["role_accuracy"] = role_accuracy_block(cfg, a.seeds)
        write_json(rep, path)
        ra = rep["role_accuracy"]
        print(f"{ra['n_truth_rings']} truth rings / {ra['n_ring_instances']} ring-instances; shipped vs recomputed "
              f"{ra['shipped_vs_recomputed']}")
        for v, b in ra["variants"].items():
            print(f"  {v}: " + "; ".join(f"{r} P {x['precision']['point'] if x['precision']['point'] is not None else float('nan'):.2f} "
                                       f"R {x['recall']['point'] if x['recall']['point'] is not None else float('nan'):.2f}"
                                       for r, x in b["per_role"].items()) + (f"; agreement {b['agreement']:.3f}" if "agreement" in b else ""))
        print(f"-> {_rel(path)}")
        return 0
    if a.typology:
        rep = typology_report(cfg, a.seeds)
        path = write_json(rep, repo_path(a.out) / cfg["typology_name"])
        p, w = rep["primary"], rep["whole_test_period"]
        print(f"primary: head {p['head']['point']:.3f} [{p['head']['lo']:.3f}, {p['head']['hi']:.3f}], rule "
              f"{p['rule']['point']:.3f} (n {p['n_matched_rings']}); whole: head {w['head']['point']:.3f}; "
              f"shape sentence {rep['shape_sentence_split']}; r5 reproduction "
              f"{(rep['reproduction_of_r5_typing'] or {}).get('position_lookup', 'n/a (shipped detector only)')}")
        print(f"-> {_rel(path)}")
        return 0
    if a.week4:
        rep = week4_report(cfg, a.seeds)
        path = write_json(rep, repo_path(a.out) / cfg["fidelity_week4_name"])
        for key in ("headline", "secondary_non_saturated"):
            blk = rep[key]
            print(f"{key}: {blk['n_truth_rings']} truth rings ({blk['n_ring_instances']} ring-instances); verdict "
                  f"{blk['overall']} {blk['verdict_at_k5']}")
        print(f"-> {_rel(path)}")
        return 0
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
