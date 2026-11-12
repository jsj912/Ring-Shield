"""Window-matched seed budget on HI-Small (sensitivity row, not a pre-registration).

    python evaluation/window_budget.py --out results/tables/v34_window_budget.csv

The shipped rule takes the k* = 0.1 % strict quantile over the WHOLE test split (864 seeds), of
which only ~463 per seed fall in the primary window (docs/V3_DIAGNOSTICS.md). Two label-free
alternatives, everything else fixed at the shipped val-chosen cell (R3 expansion, R4 partition):

    global      shipped: seed_mask_for_pct over all test edges
    in_window   the same quantile computed over primary-window edges only; no seeds outside
    per_day     the same quantile computed separately within each test day

Per (seed, rule), primary window: seeds total / in window, rings touched (truth rings with >= 1
in-window seed edge that is one of their member edges -- B14's definition), the unmatched-ring
classes of evaluation/unmatched_rings.py for b0 and full, ring P/R/F1, and the precision of the
expanded (added) edges in the window (expansion_vs_truth; veto bound 0.85, B15).
"""
from __future__ import annotations

import argparse
import json
import sys
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
from evaluation.unmatched_rings import CLASSES, R1, R3, R4, classify  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
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

RULES = ("global", "in_window", "per_day")


def seed_mask(rule: str, scores: np.ndarray, ts: np.ndarray, k_pct: float, window) -> np.ndarray:
    if rule == "global":
        return seed_mask_for_pct(scores, k_pct)
    m = np.zeros(len(scores), dtype=bool)
    if rule == "in_window":
        w = window.mask(ts)
        m[w] = seed_mask_for_pct(scores[w], k_pct)
        return m
    days = window.days_of(ts)
    for d in np.unique(days):
        sel = days == d
        m[sel] = seed_mask_for_pct(scores[sel], k_pct)
    return m


def cc_rings_from_mask(se, mask, min_size):
    """B0 (connected components of the seed edges) for an arbitrary seed mask."""
    from ringshield.aggregators.cc import aggregate_cc
    se2 = se.copy()
    se2["_sel"] = np.where(mask, 1.0, 0.0)                 # selection column only; confidence keeps its own
    return aggregate_cc(se2, 0.1, min_size, score_col="_sel", threshold=1.0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--rules", nargs="+", default=list(RULES))
    ap.add_argument("--scope", default="test_visible")
    ap.add_argument("--r1-dir", type=Path, default=R1, help="scores, embeddings and model_best_seed*.pt")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v34_window_budget.csv")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()["primary"]
    policy = Policy.load(R3 / "policy_proposed")
    affinity = Affinity.load(R4 / "affinity")
    truth, patterns = load_ground_truth(ring_gt, *W.bounds, a.scope, verbose=False)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows, klass_rows = [], []
    for S in a.seeds:
        r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        r4 = yaml.safe_load((R4 / "runs" / "average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        k_pct, min_size, p_min = float(r3["seed_frac_pct"]), int(r3["min_size"]), float(r3["p_min"])
        se = build_scored_edges(a.r1_dir / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
        emb = a.r1_dir / f"embeddings_test_seed{S}.parquet"
        ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                            embeddings_parquet=emb if emb.exists() else None, checkpoint=a.r1_dir / f"model_best_seed{S}.pt")
        scores, ts = se[SELECT_COL].to_numpy(float), se["timestamp"].to_numpy(np.int64)
        in_win = W.mask(ts)
        rid = ring_id_of.reindex(se["edge_id"].to_numpy()).fillna(-1).to_numpy()
        for rule in a.rules:
            mask = seed_mask(rule, scores, ts, k_pct, W)
            trajs = expand_all(se, mask, policy, ctx, delta_t_h=float(r3["delta_t_h"]), p_floor=p_min)
            inc_pos, is_seed = included_from_trajectories(se, mask, trajs, p_min)
            comp = components_of(ctx.idx, inc_pos)
            P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
            lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, min_members=min_size,
                                   **{k: r4[k] for k in ("cut", "threshold", "gap_h", "resolution") if k in r4})
            full = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, min_size)
            b0 = cc_rings_from_mask(se, mask, min_size)
            touched = {int(r) for r in rid[mask & in_win] if r > 0} & set(truth)
            ev = expansion_vs_truth(full, b0, se, ring_id_of, truth, W)
            row = {"seed": S, "rule": rule, "k_pct": k_pct, "seeds_total": int(mask.sum()),
                   "seeds_in_window": int((mask & in_win).sum()), "n_truth": len(truth), "rings_touched": len(touched),
                   "seed_precision_in_window": round(float((rid[mask & in_win] > 0).mean()), 4) if (mask & in_win).any() else None,
                   "added_member_precision": ev["expanded_member_precision"], "n_added_edges": ev["n_expanded_edges_in_window"]}
            for name, rings in (("b0", b0), ("full", full)):
                m = evaluate_rings(restrict_rings(rings, se, W), truth, 0.5, patterns)
                d = classify(rings, se, truth, patterns, W)
                c = Counter(d["klass"])
                row.update({f"{name}_ring_p": round(m.ring_precision, 4), f"{name}_ring_r": round(m.ring_recall, 4),
                            f"{name}_ring_f1": round(m.ring_f1, 4), f"{name}_n_rings": len(rings),
                            f"{name}_matched": c["matched"], **{f"{name}_{k}": c[k] for k in CLASSES}})
                d.insert(0, "method", name); d.insert(0, "rule", rule); d.insert(0, "seed", S)
                klass_rows.append(d)
            rows.append(row)
            print(f"seed {S} {rule:9s}: seeds {row['seeds_total']} ({row['seeds_in_window']} in window) | touched {row['rings_touched']} "
                  f"| full F1 {row['full_ring_f1']:.4f} class(b) {row['full_b_untouched']} | b0 F1 {row['b0_ring_f1']:.4f} "
                  f"class(b) {row['b0_b_untouched']} | added prec {row['added_member_precision']}", flush=True)
    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    pd.concat(klass_rows, ignore_index=True).to_csv(str(a.out).replace(".csv", "_classes.csv"), index=False)
    num = df.drop(columns=["seed", "k_pct"]).groupby("rule")
    summ = {r: {c: {"mean": round(float(g[c].mean()), 4), "sd": round(float(g[c].std(ddof=1)), 4)} for c in g.columns if c != "rule"}
            for r, g in num}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "scope": a.scope,
         "window": W.as_dict(), "summary": summ}, indent=2), encoding="utf-8")
    cols = ["seeds_total", "seeds_in_window", "rings_touched", "added_member_precision", "b0_ring_f1", "b0_b_untouched",
            "full_ring_f1", "full_b_untouched", "full_matched"]
    print("\n== mean ± sd over seeds ==")
    print(df.groupby("rule")[cols].agg(["mean", "std"]).round(3).T.to_string())
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
