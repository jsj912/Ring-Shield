"""Classical community-detection baselines under the attempt-level protocol (runbook T-P3).

    python evaluation/community_baselines.py --scores-root ../RS-e2e/experiments/R1_gine_causal \
        --expansion-root ../RS-e2e/experiments/R3_expansion/runs/proposed \
        --labels-dir ../RS-e2e/contract/out --out experiments/R13_baselines

Flagged-edge graph of a split: accounts as nodes, an edge for every transaction in the top k % of
`score_raw` (strict cut `score > q`, the B0 rule of configs/threshold_rule.yaml). Communities on
that graph replace B0's connected components; everything else is the cc aggregator's own ring
construction (`ringshield.aggregators.cc.rings_from_masks`: member edges, time span, confidence,
min_size), so forcing every component into one community reproduces B0 exactly.

Methods (weight = the maximum raw score between two accounts):
    louvain_r{0.5,1,2}   networkx.community.louvain_communities(resolution=r, seed=detector seed)
    lpa                  networkx.community.asyn_lpa_communities(weight, seed=detector seed)
    components           connected components (the B0 identity check, not a baseline)
k is chosen per method and detector seed on validation ring-F1 (test_visible, Jaccard 0.5) over the
B0 grid; min_size 3; ties -> smaller k. The full validation grid is written to config.yaml.

Partition alternatives (`<method>_on_expansion`): the same community step applied to the learned
policy's expanded subgraph (seed + expanded edges of R3 proposed, per detector seed). No validation
rings exist for that subgraph, so nothing is tuned: Louvain uses resolution 1.0 (the networkx
default) and LPA has no parameter.

Writes only under --out: <method>/seed{S}/{rings.parquet, metrics.json, config.yaml}.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import ringshield.aggregators.cc as cc  # noqa: E402
from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_stats import metrics_from_evidence, ring_evidence  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from ringshield.rings import write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RULE = yaml.safe_load((REPO_ROOT / "configs" / "threshold_rule.yaml").read_text(encoding="utf-8"))
K_GRID = [float(k) for k in RULE["grid"]["seed_frac_pct"]]
MIN_SIZE = 3
METHODS = {"louvain_r0.5": ("louvain", 0.5), "louvain_r1": ("louvain", 1.0), "louvain_r2": ("louvain", 2.0),
           "lpa": ("lpa", None), "components": ("components", None)}


def communities(G: nx.Graph, method: str, param, seed: int, weight: str = "w") -> list[set]:
    if method == "components":
        return [set(c) for c in nx.connected_components(G)]
    out = []
    for comp in nx.connected_components(G):       # run per component: communities never span two
        H = G.subgraph(comp)
        if H.number_of_edges() == 0:
            out.append(set(comp))
            continue
        if method == "louvain":
            parts = nx.community.louvain_communities(H, weight=weight, resolution=param, seed=seed)
        elif method == "lpa":
            parts = nx.community.asyn_lpa_communities(H, weight=weight, seed=seed)
        else:
            raise ValueError(method)
        out.extend(set(p) for p in parts)
    return out


class _CommunityNX:
    """Stands in for `networkx` inside ringshield.aggregators.cc for one call: identical except that
    `connected_components` returns the chosen communities (node-disjoint, like components)."""

    def __init__(self, fn):
        self._fn = fn

    def __getattr__(self, name):
        return getattr(nx, name)

    def connected_components(self, G):
        return self._fn(G)


@contextlib.contextmanager
def community_step(fn):
    orig = cc.nx
    cc.nx = _CommunityNX(fn)
    try:
        yield
    finally:
        cc.nx = orig


def max_raw_weights(se: pd.DataFrame, mask: np.ndarray) -> dict:
    sub = se.loc[mask, ["from_id", "to_id", "score_raw"]]
    a = np.minimum(sub["from_id"].to_numpy(), sub["to_id"].to_numpy())
    b = np.maximum(sub["from_id"].to_numpy(), sub["to_id"].to_numpy())
    g = pd.DataFrame({"a": a, "b": b, "s": sub["score_raw"].to_numpy()}).groupby(["a", "b"])["s"].max()
    return {k: float(v) for k, v in g.items()}


def rings_with(se: pd.DataFrame, flagged: np.ndarray, expanded: np.ndarray | None, method: str, param,
               seed: int, aggregator_id: str, min_size: int = MIN_SIZE):
    w = max_raw_weights(se, flagged | (expanded if expanded is not None else np.zeros(len(se), bool)))

    def fn(G):
        for u, v, d in G.edges(data=True):
            d["w"] = w.get((min(u, v), max(u, v)), 0.0)
        return communities(G, method, param, seed)
    conf_col = cc.score_column(se)
    with community_step(fn):
        return cc.rings_from_masks(se, flagged, expanded, min_size, None, conf_col=conf_col, aggregator_id=aggregator_id)


def ring_f1(rings, se, truth, W) -> dict:
    ev = ring_evidence(rings, se, truth, W, method="x", seed=0, threshold=0.5, causal=True)
    m = metrics_from_evidence(ev)
    return {k: float(m[k]) for k in ("ring_precision", "ring_recall", "ring_f1")}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scores-root", type=Path, default=REPO_ROOT / "experiments" / "R1_gine_causal")
    ap.add_argument("--expansion-root", type=Path, default=REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed")
    ap.add_argument("--labels-dir", type=Path, default=REPO_ROOT / "contract" / "out")  # recorded only
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--methods", nargs="+", default=list(METHODS), choices=list(METHODS))
    ap.add_argument("--no-expansion", action="store_true", help="skip the partition-alternative runs")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    wins = load_windows()
    Wv, Wt = wins["val"], wins["primary"]
    gt = pdir / "amlworld_ring_ground_truth.parquet"
    tv_val, _ = load_ground_truth(gt, *Wv.bounds, "test_visible", verbose=False)
    tv_test, _ = load_ground_truth(gt, *Wt.bounds, "test_visible", verbose=False)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    summary = []
    for s in a.seeds:
        se = {sp: build_scored_edges(a.scores_root / f"scores_{sp}_seed{s}.parquet", sp, model_id="gine_causal",
                                     seed=s, processed_dir=pdir) for sp in ("val", "test")}
        masks = {}
        for sp in ("val", "test"):
            sc = se[sp]["score_raw"].to_numpy(float)
            masks[sp] = {k: cc.seed_mask_for_pct(sc, k) for k in K_GRID}
        for name in a.methods:
            method, param = METHODS[name]
            t0 = time.time()
            grid = []
            for k in K_GRID:
                r = rings_with(se["val"], masks["val"][k], None, method, param, s, name)
                grid.append({"seed_frac_pct": k, "n_rings": len(r), **ring_f1(r, se["val"], tv_val, Wv)})
            best = max(grid, key=lambda g: (round(g["ring_f1"], 10), -g["seed_frac_pct"]))
            k = best["seed_frac_pct"]
            rings = rings_with(se["test"], masks["test"][k], None, method, param, s, name)
            tm = ring_f1(rings, se["test"], tv_test, Wt)
            out = a.out / name / f"seed{s}"
            out.mkdir(parents=True, exist_ok=True)
            write_rings_parquet(rings, out / "rings.parquet")
            cfg = {"experiment": f"R13_baselines/{name}", "created_utc": stamp, "git_commit": _git_commit(),
                   "method": method, "resolution": param, "detector_seed": s, "community_seed": s,
                   "weight": "max score_raw between the two accounts", "min_size": MIN_SIZE,
                   "k_grid": K_GRID, "cut": "strict score > q (configs/threshold_rule.yaml)",
                   "chosen_on": "val ring-F1, test_visible, Jaccard 0.5; ties -> smaller k",
                   "chosen": {"seed_frac_pct": k, "val_ring_f1": best["ring_f1"]}, "val_grid": grid,
                   "scores": str(a.scores_root), "networkx": nx.__version__}
            (out / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
            (out / "metrics.json").write_text(json.dumps({"test_primary": tm, "n_rings": len(rings), **cfg["chosen"]},
                                                         indent=2), encoding="utf-8")
            summary.append({"method": name, "seed": s, "k": k, "val_ring_f1": best["ring_f1"], **tm})
            print(f"  seed {s} {name:14s} k={k:<5} val F1 {best['ring_f1']:.4f} | test P {tm['ring_precision']:.4f} "
                  f"R {tm['ring_recall']:.4f} F1 {tm['ring_f1']:.4f} ({len(rings)} rings, {time.time() - t0:.0f}s)", flush=True)

        if a.no_expansion:
            continue
        exp_rings = read_rings_any(a.expansion_root / f"seed{s}" / "rings.parquet")
        exp_cfg = yaml.safe_load((a.expansion_root / f"seed{s}" / "config.yaml").read_text(encoding="utf-8"))
        ids = se["test"]["edge_id"].to_numpy()
        seed_ids = {e for r in exp_rings for e in r.seed_edges}
        add_ids = {e for r in exp_rings for e in r.expanded_edges} - seed_ids
        flagged, expanded = np.isin(ids, list(seed_ids)), np.isin(ids, list(add_ids))
        for name, (method, param) in {"louvain_r1_on_expansion": ("louvain", 1.0), "lpa_on_expansion": ("lpa", None),
                                      "components_on_expansion": ("components", None)}.items():
            rings = rings_with(se["test"], flagged, expanded, method, param, s, name)
            tm = ring_f1(rings, se["test"], tv_test, Wt)
            out = a.out / name / f"seed{s}"
            out.mkdir(parents=True, exist_ok=True)
            write_rings_parquet(rings, out / "rings.parquet")
            cfg = {"experiment": f"R13_baselines/{name}", "created_utc": stamp, "git_commit": _git_commit(),
                   "method": method, "resolution": param, "detector_seed": s, "community_seed": s,
                   "subgraph": f"seed + expanded edges of {a.expansion_root / f'seed{s}'} (min_size {MIN_SIZE})",
                   "expansion_chosen": exp_cfg.get("chosen"), "tuned": "nothing (no validation rings for this subgraph)",
                   "networkx": nx.__version__}
            (out / "config.yaml").write_text(yaml.dump(cfg, sort_keys=False), encoding="utf-8")
            (out / "metrics.json").write_text(json.dumps({"test_primary": tm, "n_rings": len(rings)}, indent=2), encoding="utf-8")
            summary.append({"method": name, "seed": s, "k": None, "val_ring_f1": None, **tm})
            print(f"  seed {s} {name:24s} test P {tm['ring_precision']:.4f} R {tm['ring_recall']:.4f} F1 {tm['ring_f1']:.4f} "
                  f"({len(rings)} rings)", flush=True)
    df = pd.DataFrame(summary)
    a.out.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out / "summary_test_primary.csv", index=False)
    print(df.groupby("method")[["ring_precision", "ring_recall", "ring_f1"]].mean().round(4).to_string())
    return df


if __name__ == "__main__":
    main()
