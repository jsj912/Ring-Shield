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
from explainability.edge_weights import rank_by_score
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
                    detector_seed: int) -> tuple[pd.DataFrame, dict]:
    """Per-ring fidelity rows and the summary (mean over matched rings) for every ranking."""
    ev = cfg["evaluation"]
    ks = [int(k) for k in ev["k"]]
    in_win = in_window_edge_ids(scored_edges, window)
    se = scored_edges.set_index("edge_id")
    ring_by_id = rings.set_index("ring_id")
    rows = []
    for i, m in enumerate(match_result.matches.itertuples(index=False)):     # sorted by ring_id
        member = [int(e) for e in ring_by_id.at[m.ring_id, "member_edges"] if e in in_win]
        edges = se.loc[sorted(member)].reset_index()
        T = truth_edges.edges[int(m.truth_ring_id)]
        row = {"ring_id": m.ring_id, "truth_ring_id": int(m.truth_ring_id), "pattern_type": m.pattern_type,
               "jaccard": float(m.jaccard), "n_edges_ranked": len(member), "n_true_edges": len(T),
               "n_true_among_ranked": len(set(member) & T)}
        for name, rank in RANKINGS.items():
            ranked = rank(edges)
            for k in ks:
                row[f"{name}@{k}"] = fidelity_at_k(ranked, T, k)
        rnd = random_fidelity(member, T, ks, int(ev["random_shuffles"]), [int(ev["random_seed"]), int(detector_seed), i])
        for k in ks:
            row[f"random@{k}"] = rnd[k]
        rows.append(row)
    per_ring = pd.DataFrame(rows)
    names = list(RANKINGS) + ["random"]
    summary = {name: {str(k): (float(per_ring[f"{name}@{k}"].mean()) if len(per_ring) else None) for k in ks}
               for name in names}
    return per_ring, summary


def evaluate_seed(cfg: dict, seed: int, *, scores: str, rings_path: str, truth: str, split_parquet: str) -> dict:
    se = read_scored_edges(scores)
    rings = read_rings(rings_path, scored_edges=se)
    prov = provenance(se, rings)
    W = window_from_config(cfg)
    thr, scope = matching_rule(cfg)
    res = match_in_window(rings, se, W, threshold=thr, scope=scope, truth_path=truth)
    T = truth_edge_sets(split_parquet, W, ring_ids=res.matches["truth_ring_id"])
    per_ring, summary = evaluate_frames(se, rings, res, T, W, cfg, prov["seed"])
    ev = cfg["evaluation"]
    return {
        "experiment_id": cfg["experiment_id"], "explainer_version": cfg["explainer_version"],
        "what": "fidelity@k of the score-only ranking and a random control, on matched rings",
        "inputs": {"scored_edges": _rel(scores), "rings": _rel(rings_path), "truth": _rel(truth),
                   "split_parquet": _rel(split_parquet)},
        "provenance": prov,
        "evaluation": {"window": res.window, "scope": scope, "match_threshold": thr, "k": [int(k) for k in ev["k"]],
                       "random_shuffles": int(ev["random_shuffles"]), "random_seed": int(ev["random_seed"]),
                       "edges_ranked": "ring member_edges inside the window",
                       "true_edges": "truth ring transactions inside the window (split parquet ring_id)"},
        "counts": {"n_pred_total": res.n_pred_total, "n_pred_in_window": res.n_pred_in_window,
                   "n_truth_in_scope": res.n_truth, "n_matched": res.n_matched, "n_rings_scored": len(per_ring)},
        "fidelity": summary,
        "per_ring": per_ring.to_dict("records"),
    }


def write_json(obj: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return path


# ----------------------------------------------------------------------------- CLI
def main(argv=None) -> int:
    cfg = load_config()
    inp = cfg["inputs"]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores", default=inp["scored_edges"], help="scored_edges parquet; '{seed}' is filled in")
    ap.add_argument("--rings", default=inp["rings"], help="rings parquet; '{seed}' is filled in")
    ap.add_argument("--truth", default=inp["truth"])
    ap.add_argument("--split-parquet", default=inp["split_parquet"])
    ap.add_argument("--window", default=cfg["evaluation"]["window"], help="name in configs/eval_window.yaml")
    ap.add_argument("--seeds", type=int, nargs="+", default=inp["seeds"])
    ap.add_argument("--out", default=cfg["output_dir"])
    ap.add_argument("--name", default=cfg["output_name"], help="output file name; '{seed}' is filled in")
    a = ap.parse_args(argv)
    cfg["evaluation"]["window"] = a.window
    ks = cfg["evaluation"]["k"]
    print(f"{'seed':>4}  {'rings':>5}  {'matched':>7}  " + "  ".join(f"{n}@{k}".rjust(14) for n in ("score_only", "random") for k in ks))
    for s in a.seeds:
        out = evaluate_seed(cfg, s, scores=a.scores.format(seed=s), rings_path=a.rings.format(seed=s),
                            truth=a.truth, split_parquet=a.split_parquet)
        path = write_json(out, repo_path(a.out) / a.name.format(seed=s))
        f, c = out["fidelity"], out["counts"]
        print(f"{s:>4}  {c['n_pred_total']:>5}  {c['n_matched']:>7}  "
              + "  ".join(f"{f[n][str(k)]:14.4f}" for n in ("score_only", "random") for k in ks) + f"  -> {_rel(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
