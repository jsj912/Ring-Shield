"""T-P8: seed-budget sweep for every detector (sensitivity analysis; nothing is re-tuned).

    python evaluation/budget_sweep.py --detectors gine_causal mega gfpxgb
    python evaluation/budget_sweep.py --pairs-only          # seed-set Jaccard / touched-ring union

Same pipeline as `evaluation/window_budget.py` (B0 = connected components of the seed edges;
full = the detector's own val-chosen expansion and partition cells), with **only the seed mask
changed**: k in {0.05, 0.10, 0.15, 0.20, 0.30} % of the test split, counted either over the whole
test split (`global`, the shipped rule) or over primary-window edges only (`in_window`).
Delta_t, p_min, min_size, the partition method and its cut are read from each detector's shipped
val-chosen configs and kept fixed for every k.

Per cell, written to `<exp-out>/<detector>/<rule>/k<pct>/seed<S>/metrics.json` (+ `seeds.json` with
the in-window seed edge ids and touched ring ids, used by --pairs-only): seeds total / in window,
rings touched, B0 and full ring P/R/F1, untouched count (class b), matched rings, added-member
precision (in-window expanded edges, `expansion_vs_truth`, the r9 definition).

Table: `--out` (default results/tables/v42_budget_sweep.csv) with one row per detector x rule x k
x seed, plus `.json` with mean / SD per detector x rule x k and, per k x rule, MEGA - Multi-GINe
B0 ring-F1, both SDs, the union of touched rings and the seed-set Jaccard.

MEGA reads the batch-2048 scores and the ring cells re-chosen on val from them
(`experiments/R6_mega_sb2048`, `experiments/R6_full_sb2048_k010/mega`: B0 grid fixed at k = 0.1 %;
author decisions 2026-11-15).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from evaluation.window_budget import cc_rings_from_mask, seed_mask  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.expand.run_expand import expansion_vs_truth  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

EXP = REPO_ROOT / "experiments"
K_GRID = (0.05, 0.10, 0.15, 0.20, 0.30)
RULES = ("global", "in_window")

# detector -> scores dir, model id, policy, affinity, and the val-chosen expand / full configs
DETECTORS: dict[str, dict] = {
    "gine_causal": {"r1": "R1_gine_causal", "model_id": "gine_causal",
                    "policy": "R3_expansion/policy_proposed", "affinity": "R4_partition/affinity",
                    "r3": "R3_expansion/runs/proposed/seed{S}/config.yaml",
                    "r4": "R4_partition/runs/average/seed{S}/config.yaml"},
    "mega": {"r1": "R6_mega_sb2048", "model_id": "mega",
             "policy": "R3_expansion/policy_proposed", "affinity": "R4_partition/affinity",
             "r3": "R6_full_sb2048_k010/mega/expand/seed{S}/config.yaml",
             "r4": "R6_full_sb2048_k010/mega/seed{S}/config.yaml"},
    "gfpxgb": {"r1": "R2_b0/gfpxgb_scores", "model_id": "gfpxgb",
               "policy": "R6_gfpxgb_expand/policy_gfpxgb", "affinity": "R6_gfpxgb_partition/affinity_gfpxgb",
               "r3": "R6_full/gfpxgb/expand/seed{S}/config.yaml",
               "r4": "R6_full/gfpxgb/seed{S}/config.yaml"},
    "megagenagg": {"r1": "R6_megagenagg", "model_id": "mega",
                   "policy": "R3_expansion/policy_proposed", "affinity": "R4_partition/affinity",
                   "r3": "R6_full_sb2048_k010/megagenagg/expand/seed{S}/config.yaml",
                   "r4": "R6_full_sb2048_k010/megagenagg/seed{S}/config.yaml"},
}


def kdir(k: float) -> str:
    return f"k{k:.2f}"


def chosen(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["chosen"]


def run_detector(name: str, spec: dict, seeds, ks, rules, exp_root: Path, out_root: Path, scope: str,
                 shared: dict) -> list[dict]:
    pdir, W, truth, patterns, ring_id_of = (shared[k] for k in ("pdir", "W", "truth", "patterns", "ring_id_of"))
    r1 = exp_root / spec["r1"]
    policy, affinity = Policy.load(exp_root / spec["policy"]), Affinity.load(exp_root / spec["affinity"])
    rows = []
    for S in seeds:
        t0 = time.time()
        r3 = chosen(exp_root / spec["r3"].format(S=S))
        r4 = chosen(exp_root / spec["r4"].format(S=S))
        min_size, p_min, dt = int(r3["min_size"]), float(r3["p_min"]), float(r3["delta_t_h"])
        assert (int(r4["min_size"]), float(r4["p_min"]), float(r4["delta_t_h"])) == (min_size, p_min, dt), \
            f"{name} seed {S}: expand and full configs disagree on the fixed cell"
        se = build_scored_edges(r1 / f"scores_test_seed{S}.parquet", "test", model_id=spec["model_id"], seed=S,
                                processed_dir=pdir)
        emb, ckpt = r1 / f"embeddings_test_seed{S}.parquet", r1 / f"model_best_seed{S}.pt"
        ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                            embeddings_parquet=emb if emb.exists() else None,
                            checkpoint=ckpt if ckpt.exists() else None)
        scores, ts = se[SELECT_COL].to_numpy(float), se["timestamp"].to_numpy(np.int64)
        in_win = W.mask(ts)
        rid = ring_id_of.reindex(se["edge_id"].to_numpy()).fillna(-1).to_numpy()
        eid = se["edge_id"].to_numpy()
        for rule in rules:
            for k in ks:
                mask = seed_mask(rule, scores, ts, k, W)
                trajs = expand_all(se, mask, policy, ctx, delta_t_h=dt, p_floor=p_min)
                inc_pos, is_seed = included_from_trajectories(se, mask, trajs, p_min)
                comp = components_of(ctx.idx, inc_pos)
                P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
                lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=min_size,
                                       **{x: r4[x] for x in ("cut", "threshold", "gap_h", "resolution") if x in r4})
                full = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, min_size)
                b0 = cc_rings_from_mask(se, mask, min_size)
                touched = sorted({int(r) for r in rid[mask & in_win] if r > 0} & set(truth))
                ev = expansion_vs_truth(full, b0, se, ring_id_of, truth, W)
                row = {"detector": name, "rule": rule, "k_pct": k, "seed": S, "seeds_total": int(mask.sum()),
                       "seeds_in_window": int((mask & in_win).sum()), "n_truth": len(truth),
                       "rings_touched": len(touched),
                       "added_member_precision": ev["expanded_member_precision"],
                       "n_added_edges": ev["n_expanded_edges_in_window"]}
                for mname, rings in (("b0", b0), ("full", full)):
                    m = evaluate_rings(restrict_rings(rings, se, W), truth, 0.5, patterns)
                    c = Counter(classify(rings, se, truth, patterns, W)["klass"])
                    row.update({f"{mname}_ring_p": round(m.ring_precision, 4), f"{mname}_ring_r": round(m.ring_recall, 4),
                                f"{mname}_ring_f1": round(m.ring_f1, 4), f"{mname}_n_rings": len(rings),
                                f"{mname}_matched": c["matched"], f"{mname}_untouched": c["b_untouched"]})
                cell = out_root / name / rule / kdir(k) / f"seed{S}"
                cell.mkdir(parents=True, exist_ok=True)
                (cell / "metrics.json").write_text(json.dumps(
                    {**row, "fixed_cell": {"min_size": min_size, "p_min": p_min, "delta_t_h": dt,
                                           **{x: r4[x] for x in ("method", "cut") if x in r4}},
                     "scores_dir": str(r1), "scope": scope, "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                    indent=1, default=float), encoding="utf-8")
                (cell / "seeds.json").write_text(json.dumps(
                    {"seed_edges_in_window": [int(x) for x in eid[mask & in_win]], "touched_rings": touched}),
                    encoding="utf-8")
                rows.append(row)
                print(f"{name} s{S} {rule:9s} k={k:.2f}: in-window seeds {row['seeds_in_window']} | touched "
                      f"{row['rings_touched']} | b0 F1 {row['b0_ring_f1']:.4f} | full F1 {row['full_ring_f1']:.4f} "
                      f"| added prec {row['added_member_precision']}", flush=True)
        print(f"{name} seed {S}: {time.time() - t0:.0f} s", flush=True)
    return rows


def pair_stats(out_root: Path, a: str, b: str, seeds, ks, rules) -> list[dict]:
    """Per k x rule x seed: seed-set Jaccard (in-window seed edges) and union of touched rings."""
    out = []
    for rule in rules:
        for k in ks:
            for S in seeds:
                pa, pb = (out_root / d / rule / kdir(k) / f"seed{S}" / "seeds.json" for d in (a, b))
                if not (pa.exists() and pb.exists()):
                    continue
                ja, jb = json.loads(pa.read_text()), json.loads(pb.read_text())
                sa, sb = set(ja["seed_edges_in_window"]), set(jb["seed_edges_in_window"])
                ta, tb = set(ja["touched_rings"]), set(jb["touched_rings"])
                out.append({"pair": f"{a}|{b}", "rule": rule, "k_pct": k, "seed": S,
                            "seed_jaccard": len(sa & sb) / len(sa | sb) if sa | sb else float("nan"),
                            "touched_a": len(ta), "touched_b": len(tb), "touched_union": len(ta | tb),
                            "touched_intersection": len(ta & tb)})
    return out


def summarise(df: pd.DataFrame, pairs: pd.DataFrame) -> dict:
    num = [c for c in df.columns if c not in ("detector", "rule", "k_pct", "seed")]
    cells = {}
    for (d, r, k), g in df.groupby(["detector", "rule", "k_pct"]):
        cells[f"{d}|{r}|{k:.2f}"] = {c: {"mean": float(g[c].mean()), "sd": float(g[c].std(ddof=1)) if len(g) > 1 else None,
                                         "n": int(g[c].notna().sum())} for c in num}
    bars = []
    for (r, k), g in df.groupby(["rule", "k_pct"]):
        m, n = g[g.detector == "mega"]["b0_ring_f1"], g[g.detector == "gine_causal"]["b0_ring_f1"]
        if len(m) and len(n):
            sd_m, sd_n = float(m.std(ddof=1)), float(n.std(ddof=1))
            gap = float(m.mean() - n.mean())
            bars.append({"rule": r, "k_pct": k, "mega_minus_gine_b0_f1": gap, "sd_mega": sd_m, "sd_gine": sd_n,
                         "holds": abs(gap) <= max(sd_m, sd_n), "fails": (k >= 0.15) and abs(gap) > 2 * max(sd_m, sd_n)})
    vetoed = df[df["added_member_precision"] < 0.85][["detector", "rule", "k_pct", "seed", "added_member_precision"]]
    psum = (pairs.groupby(["pair", "rule", "k_pct"])[["seed_jaccard", "touched_union", "touched_a", "touched_b"]]
            .mean().reset_index().to_dict("records")) if len(pairs) else []
    return {"cells": cells, "tp8_bar": bars, "veto_rows": vetoed.to_dict("records"), "pairs_mean": psum}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detectors", nargs="+", default=["gine_causal", "mega", "gfpxgb"], choices=sorted(DETECTORS))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--k-grid", type=float, nargs="+", default=list(K_GRID))
    ap.add_argument("--rules", nargs="+", default=list(RULES), choices=list(RULES))
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--exp-root", type=Path, default=EXP, help="where scores, policies and ring configs are read")
    ap.add_argument("--exp-out", type=Path, default=EXP / "R14_budget_sweep")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v42_budget_sweep.csv")
    ap.add_argument("--pairs-only", action="store_true", help="rebuild the table from existing cells; no pipeline runs")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    rows = []
    if not a.pairs_only:
        pdir = load_paths()["processed_dir"]
        W = load_windows()["primary"]
        truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, a.scope, verbose=False)
        ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
        shared = {"pdir": pdir, "W": W, "truth": truth, "patterns": patterns, "ring_id_of": ring_id_of}
        for d in a.detectors:
            run_detector(d, DETECTORS[d], a.seeds, a.k_grid, a.rules, a.exp_root, a.exp_out, a.scope, shared)
    # the table is always rebuilt from every cell on disk, so detectors can be run in separate processes
    for p in sorted(a.exp_out.glob("*/*/k*/seed*/metrics.json")):
        if p.relative_to(a.exp_out).parts[0].startswith("_"):   # superseded runs are kept under _<name>
            continue
        m = json.loads(p.read_text(encoding="utf-8"))
        rows.append({k: v for k, v in m.items() if k not in ("fixed_cell", "scores_dir", "scope", "created_utc")})
    if not rows:
        print("no cells found"); return
    df = pd.DataFrame(rows).sort_values(["detector", "rule", "k_pct", "seed"]).reset_index(drop=True)
    dets = sorted(df.detector.unique())
    pairs = pd.DataFrame([r for x in dets for y in dets if x < y
                          for r in pair_stats(a.exp_out, x, y, sorted(df.seed.unique()), sorted(df.k_pct.unique()),
                                              sorted(df.rule.unique()))])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    if len(pairs):
        pairs.to_csv(str(a.out).replace(".csv", "_pairs.csv"), index=False)
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "scope": a.scope,
         "k_grid": sorted(df.k_pct.unique().tolist()), "rules": sorted(df.rule.unique().tolist()),
         "detectors": {d: DETECTORS[d] for d in dets}, "summary": summarise(df, pairs)}, indent=1, default=float),
        encoding="utf-8")
    print(df.groupby(["detector", "rule", "k_pct"])[["seeds_in_window", "rings_touched", "b0_ring_f1", "full_ring_f1",
                                                     "added_member_precision"]].mean().round(4).to_string())
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
