"""Seed reallocation evaluated under `full`, not only B0 (deep-analysis #5).

    python evaluation/realloc_full.py --exp-root ../RS-e2e/experiments \
        --out results/tables/v37_realloc_full.csv

B14 compared three ways of spending the same 0.1 % budget at B0 only. Here the SEED MASK comes from
each rule, and everything downstream is the shipped pipeline unchanged:

    global     strict 0.1 % quantile of gine_causal score_raw (shipped)
    ensemble   11b: strict 0.1 % quantile of experiments/R11b_ensemble score_raw (best rank over
               gine_causal and mega)
    local      11c: strict 0.1 % quantile of experiments/R11c_local score_raw (account local
               maxima ranked first)

Downstream (expansion, policy features, partition) reads the ORIGINAL gine_causal scored edges,
embeddings and checkpoint, at the shipped val-chosen R3 / R4 cells -- so only which edges are seeds
changes, and the policy never sees an out-of-distribution score. Metrics as in
evaluation/window_budget.py, primary window: rings touched (B14 definition), matched rings, B0 and
full ring-F1, class (b), added-member precision.
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
from evaluation.unmatched_rings import CLASSES, R3, R4, classify  # noqa: E402
from evaluation.window_budget import cc_rings_from_mask  # noqa: E402
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

RULES = {"global": "R1_gine_causal", "ensemble": "R11b_ensemble", "local": "R11c_local"}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp-root", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--k-pct", type=float, default=0.1)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v37_realloc_full.csv")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    R1 = a.exp_root / "R1_gine_causal"
    policy, affinity = Policy.load(R3 / "policy_proposed"), Affinity.load(R4 / "affinity")
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows, kl = [], []
    for S in a.seeds:
        r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        r4 = yaml.safe_load((R4 / "runs" / "average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        min_size, p_min = int(r3["min_size"]), float(r3["p_min"])
        se = build_scored_edges(R1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
        ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                            embeddings_parquet=R1 / f"embeddings_test_seed{S}.parquet", checkpoint=R1 / f"model_best_seed{S}.pt")
        ts = se["timestamp"].to_numpy(np.int64)
        in_win = W.mask(ts)
        rid = ring_id_of.reindex(se["edge_id"].to_numpy()).fillna(-1).to_numpy()
        for rule, d in RULES.items():
            alt = pd.read_parquet(a.exp_root / d / f"scores_test_seed{S}.parquet", columns=["edge_id", "score_raw"])
            sc = alt.set_index("edge_id")["score_raw"].reindex(se["edge_id"].to_numpy()).to_numpy(float)
            assert not np.isnan(sc).all()
            mask = seed_mask_for_pct(sc, a.k_pct)
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
            sm = mask & in_win
            per_ring = Counter(int(r) for r in rid[sm] if r > 0 and int(r) in truth)
            row = {"seed": S, "rule": rule, "seeds_total": int(mask.sum()), "seeds_in_window": int(sm.sum()),
                   "rings_touched": len(touched), "seeds_off_ring_share": round(float((rid[sm] <= 0).mean()), 4),
                   "seeds_per_touched_ring": round(float(np.mean(list(per_ring.values()))), 3) if per_ring else 0.0,
                   "added_member_precision": ev["expanded_member_precision"], "n_added_edges": ev["n_expanded_edges_in_window"]}
            for name, rings in (("b0", b0), ("full", full)):
                m = evaluate_rings(restrict_rings(rings, se, W), truth, 0.5, patterns)
                c = Counter(classify(rings, se, truth, patterns, W)["klass"])
                row.update({f"{name}_ring_f1": round(m.ring_f1, 4), f"{name}_ring_p": round(m.ring_precision, 4),
                            f"{name}_ring_r": round(m.ring_recall, 4), f"{name}_matched": c["matched"],
                            **{f"{name}_{k}": c[k] for k in CLASSES}})
                if name == "full":
                    kl.append({"seed": S, "rule": rule, **c})
            rows.append(row)
            print(f"seed {S} {rule:8s}: seeds {row['seeds_total']} ({row['seeds_in_window']} in win) touched {row['rings_touched']} "
                  f"| b0 F1 {row['b0_ring_f1']:.4f} m {row['b0_matched']} | full F1 {row['full_ring_f1']:.4f} m {row['full_matched']} "
                  f"(b) {row['full_b_untouched']} | added prec {row['added_member_precision']}", flush=True)
    df = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    cols = ["seeds_in_window", "rings_touched", "seeds_per_touched_ring", "seeds_off_ring_share", "b0_ring_f1", "b0_matched",
            "full_ring_f1", "full_matched", "full_b_untouched", "added_member_precision"]
    g = df.groupby("rule")[cols].agg(["mean", "std"]).round(4)
    paired = {}
    for rule in ("ensemble", "local"):
        dd = df[df.rule == rule].set_index("seed")[cols] - df[df.rule == "global"].set_index("seed")[cols]
        paired[rule] = {c: {"mean": round(float(dd[c].mean()), 4), "sd": round(float(dd[c].std(ddof=1)), 4),
                            "per_seed": [round(float(x), 4) for x in dd[c]]} for c in cols}
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "k_pct": a.k_pct,
         "exp_root": str(a.exp_root), "summary": json.loads(g.to_json()), "paired_vs_global": paired}, indent=2), encoding="utf-8")
    print("\n== mean / sd over seeds ==")
    print(g.T.to_string())
    print("\n== paired vs global (mean, sd) ==")
    for r, d in paired.items():
        print(r, {c: (v["mean"], v["sd"]) for c, v in d.items()})
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
