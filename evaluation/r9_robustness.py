"""Robustness check only: does the quiet-recall result depend on the operating point? (Step 9 close)

    python evaluation/r9_robustness.py --seed-fracs 0.05 0.15

**k\\* is not changed by this script.** The shipped operating point stays the validation-chosen
0.1 % (`configs/threshold_rule.yaml`, Step 3c); this runs `proposed` (expansion + connected
components) and `full` (expansion + partition) at 0.05 % and 0.15 % on the primary window and
reports quiet-member recall, added-member precision and ring-F1 next to the 0.1 % row, to show
whether the quiet-member finding survives a different seed fraction. Every other parameter
(policy, delta_t, p_min, linkage cut) is the seed's own val-chosen value; nothing is chosen here
and nothing is chosen on test.

Output: `results/tables/r9_robustness.csv` (+ `.json` with the run parameters).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402
from evaluation.ring_stats import metrics_from_evidence, ring_evidence  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, expansion_probs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R3 = REPO_ROOT / "experiments" / "R3_expansion"
R4 = REPO_ROOT / "experiments" / "R4_partition"


def added_member_precision(rings, ring_id_of: pd.Series, window, scored_edges: pd.DataFrame) -> tuple[int, int]:
    """(expanded edges inside the window that are member edges of a truth ring, total)."""
    ts = scored_edges.set_index("edge_id")["timestamp"]
    exp = sorted({e for r in rings for e in r.expanded_edges})
    exp = [e for e in exp if window.mask(np.array([ts.loc[e]]))[0]]
    if not exp:
        return 0, 0
    is_member = ring_id_of.reindex(exp).fillna(-1).to_numpy() > 0
    return int(is_member.sum()), int(len(exp))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--seed-fracs", type=float, nargs="+", default=[0.05, 0.15])
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r9_robustness.csv")
    args = ap.parse_args(argv)
    t0 = time.time()
    paths = load_paths()
    pdir = paths["processed_dir"]
    W = load_windows()["primary"]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    policy = Policy.load(R3 / "policy_proposed")
    affinity = Affinity.load(R4 / "affinity")
    ring_id_of = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"]).set_index("EdgeID")["ring_id"]
    rows = []
    for S in args.seeds:
        r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        r4 = yaml.safe_load((R4 / "runs" / "average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
        min_size, delta_t_h, p_min = int(r3["min_size"]), float(r3["delta_t_h"]), float(r3["p_min"])
        cut = float(r4["cut"])
        se = build_scored_edges(R1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
        ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                            embeddings_parquet=R1 / f"embeddings_test_seed{S}.parquet", checkpoint=R1 / f"model_best_seed{S}.pt")
        for k in args.seed_fracs:
            mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k)
            trajs = expand_all(se, mask, policy, ctx, delta_t_h=delta_t_h, p_floor=p_min)
            inc_pos, is_seed = included_from_trajectories(se, mask, trajs, p_min)
            comp = components_of(ctx.idx, inc_pos)
            P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
            probs = expansion_probs(trajs, p_min)
            for method, labels in (("proposed", comp),
                                   ("full", partition_labels(ctx, inc_pos, is_seed, comp, method="average", pairs=P,
                                                             cut=cut, min_members=min_size))):
                rings = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, labels, min_size, aggregator_id=method,
                                                 probs=probs)
                ev = ring_evidence(rings, se, truth, W, method=method, seed=S, seed_mask=mask, patterns=patterns, causal=True)
                m = metrics_from_evidence(ev)
                n_ok, n_exp = added_member_precision(rings, ring_id_of, W, se)
                rows.append({"method": method, "seed_frac_pct": k, "seed": S, "n_seed_edges": int(mask.sum()),
                             "n_rings": len(rings), "ring_precision": m["ring_precision"], "ring_recall": m["ring_recall"],
                             "ring_f1": m["ring_f1"], "quiet_member_recall": m["quiet_member_recall"],
                             "n_quiet": m["n_quiet"], "n_quiet_found": m["n_quiet_found"],
                             "expanded_true_member": n_ok, "expanded_total": n_exp,
                             "added_member_precision": (n_ok / n_exp) if n_exp else np.nan})
                print(f"  seed {S} k={k}% {method:9s}: rings {len(rings):4d} F1 {m['ring_f1']:.3f} "
                      f"quiet {m['quiet_member_recall']:.3f} ({m['n_quiet_found']}/{m['n_quiet']}) "
                      f"added-member precision {rows[-1]['added_member_precision']:.3f} ({n_ok}/{n_exp})", flush=True)
    d = pd.DataFrame(rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(args.out, index=False)
    agg = d.groupby(["method", "seed_frac_pct"])[["ring_f1", "quiet_member_recall", "added_member_precision", "n_seed_edges"]].agg(["mean", "std"])
    Path(str(args.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
         "purpose": "robustness check only -- k* stays the val-chosen 0.1 % (configs/threshold_rule.yaml)",
         "seeds": args.seeds, "seed_fracs": args.seed_fracs, "window": "primary",
         "fixed_from_val": "policy, delta_t, p_min (R3 per seed) and the linkage cut (R4 per seed)",
         "summary": json.loads(agg.reset_index().to_json(orient="records")), "seconds": round(time.time() - t0, 1)}, indent=2),
        encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n== robustness (primary window, mean over seeds; k* stays 0.1 %) ==")
    print(agg.round(4).to_string())
    print(f"-> {args.out}")


if __name__ == "__main__":
    main()
