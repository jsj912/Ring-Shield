"""rings.parquet **v1**: the `full` aggregator's rings with every contract field filled (Step 8.4).

    python contract/make_rings_full.py --seeds 1 2 3 4 5

For each detector seed S: the R1 scores, the R3 expansion policy at the seed's val-chosen
(delta_t, p_min), the R4 affinity with the val-chosen linkage cut, the Step 8 roles and the
typing head -> `contract/out/rings_full_gine_causal_<S>.parquet` (RINGS_COLUMNS, contract order)
plus a `.log.json` recording every input, the field counts and the primary-window metrics.

Nothing is chosen here: every parameter comes from a val-chosen config written in an earlier
step. The run asserts that filling the new fields changed no membership -- the primary-window
ring precision / recall / F1 must equal the R4 `average` run of the same seed to 1e-9.
"""
from __future__ import annotations

import argparse
import json
import math
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
from contract.schema import RINGS_ORDER, TOPOLOGY_TYPES  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.aggregators.expand import expand_all  # noqa: E402
from ringshield.aggregators.full import (component_pairs, expansion_probs, included_from_trajectories,  # noqa: E402
                                         partition_labels, rings_from_edge_clusters)
from ringshield.evaluate import evaluate_blocks  # noqa: E402
from ringshield.expand.context import build_context  # noqa: E402
from ringshield.expand.policy import Policy  # noqa: E402
from ringshield.partition.affinity import Affinity  # noqa: E402
from ringshield.partition.pairs import components_of  # noqa: E402
from ringshield.rings import write_rings_parquet  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.typing.head import TypingHead  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R3 = REPO_ROOT / "experiments" / "R3_expansion"
R4 = REPO_ROOT / "experiments" / "R4_partition"
R5 = REPO_ROOT / "experiments" / "R5_typing"
HEAD_DIR = [str(R5 / "head")]          # filled by main() with the val-chosen head, recorded in every log


def build_for_seed(S: int, *, head, policy, affinity, out_dir: Path, scope: str = "test_visible") -> dict:
    t0 = time.time()
    paths = load_paths()
    pdir = paths["processed_dir"]
    r3 = yaml.safe_load((R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    r4 = yaml.safe_load((R4 / "runs" / "average" / f"seed{S}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    k_pct, min_size = float(r3["seed_frac_pct"]), int(r3["min_size"])
    delta_t_h, p_min, cut = float(r3["delta_t_h"]), float(r3["p_min"]), float(r4["cut"])
    se = build_scored_edges(R1 / f"scores_test_seed{S}.parquet", "test", model_id="gine_causal", seed=S, processed_dir=pdir)
    ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                        embeddings_parquet=R1 / f"embeddings_test_seed{S}.parquet", checkpoint=R1 / f"model_best_seed{S}.pt")
    mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), k_pct)
    trajs = expand_all(se, mask, policy, ctx, delta_t_h=delta_t_h, p_floor=p_min)
    inc_pos, is_seed = included_from_trajectories(se, mask, trajs, p_min)
    comp = components_of(ctx.idx, inc_pos)
    P = component_pairs(ctx, inc_pos, is_seed, comp, affinity)
    lab = partition_labels(ctx, inc_pos, is_seed, comp, method=r4["method"], pairs=P, cut=cut, min_members=min_size)
    report: dict = {}
    rings = rings_from_edge_clusters(se, ctx.idx, inc_pos, is_seed, lab, min_size, aggregator_id="full",
                                     probs=expansion_probs(trajs, p_min), head=head, report=report)
    for i, r in enumerate(rings):                                   # contract ring_id / tenant rule (Step 5)
        r.ring_id = f"full-gine_causal-{S}-{i}"
        first = min(r.seed_edges, key=lambda e: (int(se.set_index('edge_id').loc[e, 'timestamp']), e))
        r.tenant_id = int(se.set_index("edge_id").loc[first, "from_bank"])
    out = out_dir / f"rings_full_gine_causal_{S}.parquet"
    write_rings_parquet(rings, out)

    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()
    blocks = evaluate_blocks(rings, se, ring_gt, scope, {k: w for k, w in W.items() if w.split == "test"}, 0.5, [0.3, 0.7])
    prim = blocks["primary"]
    ref = json.loads((R4 / "runs" / "average" / f"seed{S}" / "metrics.json").read_text(encoding="utf-8"))["blocks"]["primary"]
    same = {m: (abs(prim[m] - ref[m]) < 1e-9) for m in ("ring_precision", "ring_recall", "ring_f1", "mean_jaccard", "member_coverage")}
    assert all(same.values()), f"seed {S}: filling the contract fields changed membership: {prim} vs {ref}"
    probs_ok = all(len(r.expanded_edge_probs) == len(r.expanded_edges) for r in rings)
    topo = pd.Series([r.topology_type for r in rings]).value_counts().to_dict()
    log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "contract_version": "rings.parquet v1 (Step 8)", "detector_seed": S, "aggregator": "full",
           "inputs": {"scores": str(R1 / f"scores_test_seed{S}.parquet"), "embeddings": str(R1 / f"embeddings_test_seed{S}.parquet"),
                      "policy": str(R3 / "policy_proposed"), "affinity": str(R4 / "affinity"), "typing_head": str(HEAD_DIR[0]),
                      "roles_config": "configs/roles.yaml"},
           "params": {"seed_frac_pct": k_pct, "min_size": min_size, "delta_t_h": delta_t_h, "p_min": p_min,
                      "partition": r4["method"], "cut": cut, "max_events_per_query": 500},
           "n_rings": len(rings), "columns": RINGS_ORDER,
           "fields": {"n_seed_edges": int(sum(len(r.seed_edges) for r in rings)),
                      "n_expanded_edges": int(sum(len(r.expanded_edges) for r in rings)),
                      "n_member_edges": int(sum(len(r.member_edges) for r in rings)),
                      "expanded_edge_probs_aligned": probs_ok,
                      "n_rings_with_expansion": int(sum(1 for r in rings if r.expanded_edges)),
                      "n_rings_closure_nan": report.get("n_rings_closure_nan"),
                      "n_rings_with_source": int(sum(1 for r in rings if r.source_accounts)),
                      "n_rings_with_sink": int(sum(1 for r in rings if r.sink_accounts)),
                      "n_rings_with_mule": int(sum(1 for r in rings if r.mule_accounts)),
                      "n_accounts_by_role": {"source": int(sum(len(r.source_accounts) for r in rings)),
                                             "sink": int(sum(len(r.sink_accounts) for r in rings)),
                                             "mule_or_holder": int(sum(len(r.mule_accounts) for r in rings))},
                      "topology_counts": topo, "n_topology_unknown": int(topo.get("UNKNOWN", 0)),
                      "confidence": {"min": float(min(r.confidence for r in rings)), "max": float(max(r.confidence for r in rings)),
                                     "mean": float(np.mean([r.confidence for r in rings]))},
                      "conservation_closure": {"n_nan": int(sum(1 for r in rings if math.isnan(r.conservation_closure))),
                                               "mean_non_nan": float(np.nanmean([r.conservation_closure for r in rings]))}},
           "primary_window": {m: prim[m] for m in ("n_predicted", "n_truth", "n_matched", "ring_precision", "ring_recall", "ring_f1",
                                                   "mean_jaccard", "member_coverage", "ring_recall_ge3")},
           "reproduces_r4_average_run": same, "seconds": round(time.time() - t0, 1), "out": str(out)}
    Path(str(out) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[rings v1] seed {S}: {len(rings)} rings | P {prim['ring_precision']:.4f} R {prim['ring_recall']:.4f} F1 {prim['ring_f1']:.4f} "
          f"(reproduces R4 average: {all(same.values())}) | expanded {log['fields']['n_expanded_edges']} with probs | "
          f"closure NaN {log['fields']['conservation_closure']['n_nan']} | topology {topo} | {log['seconds']}s -> {out.name}")
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--head-dir", type=Path, default=None, help="default: the val-chosen head (experiments/R5_typing/chosen_head.json)")
    ap.add_argument("--policy-dir", type=Path, default=R3 / "policy_proposed")
    ap.add_argument("--affinity-dir", type=Path, default=R4 / "affinity")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    args = ap.parse_args(argv)
    head_dir = args.head_dir or (REPO_ROOT / json.loads((R5 / "chosen_head.json").read_text(encoding="utf-8"))["chosen_dir"])
    print(f"[rings v1] typing head: {head_dir}")
    head = TypingHead.load(head_dir)
    HEAD_DIR[0] = str(head_dir)
    policy = Policy.load(args.policy_dir)
    affinity = Affinity.load(args.affinity_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    logs = [build_for_seed(S, head=head, policy=policy, affinity=affinity, out_dir=args.out_dir) for S in args.seeds]
    f1 = [l["primary_window"]["ring_f1"] for l in logs]
    print(f"[rings v1] {len(logs)} files; primary ring-F1 {np.mean(f1):.4f} +/- {np.std(f1, ddof=1):.4f} "
          f"(R4 'average' row: 0.589 +/- 0.037)")


if __name__ == "__main__":
    main()
