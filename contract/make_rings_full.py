"""rings.parquet **v2**: the `full` aggregator's rings with every contract field filled.

v1 was Step 8.4. v2 (Step 14) ADDS the currency-aware fields -- `conservation_closure_ccy`,
the `*_accounts_ccy` quartet including `undetermined_accounts_ccy`, `n_roles_changed_ccy`,
`n_accounts_ccy_undefined`, `n_currencies` -- and changes no v1 field: `conservation_closure`
and `confidence` remain raw cross-currency sums. See docs/MIGRATION.md.

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
from contract.schema import RINGS_ORDER, RINGS_SCHEMA_VERSION, TOPOLOGY_TYPES  # noqa: E402
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
from ringshield.roles import fill_currency_fields  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.typing.head import TypingHead  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

# Resolved through configs/paths.yaml (`experiments_dir`) rather than hardcoded to the checkout,
# so a worktree or a second dataset can point at another tree with $RINGSHIELD_PATHS. Default is
# unchanged: experiments_dir is `experiments` under the repo root.
_EXP = load_paths()["experiments_dir"]
R1 = _EXP / "R1_gine_causal"
R3 = _EXP / "R3_expansion"
R4 = _EXP / "R4_partition"
R5 = _EXP / "R5_typing"
R2 = _EXP / "R2_b0"
R6 = _EXP / "R6_full"
R6G = _EXP / "R6_gfpxgb_expand"
R6GP = _EXP / "R6_gfpxgb_partition"
R6M = _EXP / "R6_mega"
HEAD_DIR = [str(R5 / "head")]          # filled by main() with the val-chosen head, recorded in every log


# One entry per detector whose `full` run is being materialised into the contract. The fields are
# the only things that differ between them: everything after `build_scored_edges` is shared, so
# there is one field-filling path and not three.
#
# `run_dir` is the run whose output must be reproduced; `cell_from` says where the chosen cell is
# read from (gine kept the expansion cell and the linkage cut in two separate run configs, the R6
# runs record both in one). `embeddings` None means the detector has none -- which is not a gap but
# a property: the gfpxgb policy and affinity were TRAINED without them, so its affinity has 19
# features and no `cos_emb` (see ringshield.roles.missing_affinity_features).
DETECTORS = {
    "gine_causal": {
        "model_id": "gine_causal",
        "scores": lambda S: R1 / f"scores_test_seed{S}.parquet",
        "embeddings": lambda S: R1 / f"embeddings_test_seed{S}.parquet",
        "checkpoint": lambda S: R1 / f"model_best_seed{S}.pt",
        "policy_dir": R3 / "policy_proposed",
        "affinity_dir": R4 / "affinity",
        "cell_from": "split",                       # r3 run config + r4 run config
        "r3_config": lambda S: R3 / "runs" / "proposed" / f"seed{S}" / "config.yaml",
        "r4_config": lambda S: R4 / "runs" / "average" / f"seed{S}" / "config.yaml",
        "run_dir": lambda S: R4 / "runs" / "average" / f"seed{S}",
        "note": "the shipped detector; policy and affinity trained on its own embeddings",
    },
    "gfpxgb": {
        "model_id": "gfpxgb",
        "scores": lambda S: R2 / "gfpxgb_scores" / f"scores_test_seed{S}.parquet",
        "embeddings": None,                          # trained and run without embeddings
        "checkpoint": None,
        "policy_dir": R6G / "policy_gfpxgb",
        "affinity_dir": R6GP / "affinity_gfpxgb",
        "cell_from": "run",                          # one config carries the whole chosen cell
        "run_dir": lambda S: R6 / "gfpxgb" / f"seed{S}",
        "note": "GFP+XGBoost detector with its OWN policy and affinity, both trained WITHOUT "
                "embeddings: the affinity has 19 features and no cos_emb",
    },
    "mega": {
        "model_id": "mega",
        "scores": lambda S: R6M / f"scores_test_seed{S}.parquet",
        "embeddings": lambda S: R6M / f"embeddings_test_seed{S}.parquet",
        "checkpoint": lambda S: R6M / f"model_best_seed{S}.pt",
        "policy_dir": R3 / "policy_proposed",        # the GINE-trained policy
        "affinity_dir": R4 / "affinity",             # the GINE-trained affinity
        "cell_from": "run",
        "run_dir": lambda S: R6 / "mega" / f"seed{S}",
        "note": "MEGA-GNN detector read through the GINE-TRAINED policy and affinity, with MEGA's "
                "own embeddings supplying cos_emb -- so the affinity is applied to an embedding "
                "space it was not trained on (docs/FINDINGS.md, the embedding-space caveat)",
    },
}


def chosen_cell(det: dict, S: int) -> dict:
    """The val-chosen cell, from wherever this detector's run recorded it."""
    if det["cell_from"] == "split":
        r3 = yaml.safe_load(det["r3_config"](S).read_text(encoding="utf-8"))["chosen"]
        r4 = yaml.safe_load(det["r4_config"](S).read_text(encoding="utf-8"))["chosen"]
        return {"seed_frac_pct": float(r3["seed_frac_pct"]), "min_size": int(r3["min_size"]),
                "delta_t_h": float(r3["delta_t_h"]), "p_min": float(r3["p_min"]),
                "method": r4["method"], "cut": float(r4["cut"])}
    c = yaml.safe_load((det["run_dir"](S) / "config.yaml").read_text(encoding="utf-8"))["chosen"]
    return {"seed_frac_pct": float(c["seed_frac_pct"]), "min_size": int(c["min_size"]),
            "delta_t_h": float(c["delta_t_h"]), "p_min": float(c["p_min"]),
            "method": c["method"], "cut": float(c["cut"])}


def build_for_seed(S: int, *, head, policy, affinity, out_dir: Path, scope: str = "test_visible",
                   detector: str = "gine_causal") -> dict:
    t0 = time.time()
    det = DETECTORS[detector]
    paths = load_paths()
    pdir = paths["processed_dir"]
    cell = chosen_cell(det, S)
    k_pct, min_size = cell["seed_frac_pct"], cell["min_size"]
    delta_t_h, p_min, cut = cell["delta_t_h"], cell["p_min"], cell["cut"]
    r4 = {"method": cell["method"], "cut": cut}
    se = build_scored_edges(det["scores"](S), "test", model_id=det["model_id"], seed=S, processed_dir=pdir)
    emb_path = det["embeddings"](S) if det["embeddings"] else None
    ckpt_path = det["checkpoint"](S) if det["checkpoint"] else None
    ctx = build_context(se, gfp_parquet=pdir / "amlworld_gfp_features_test.parquet",
                        embeddings_parquet=emb_path, checkpoint=ckpt_path)
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
        r.ring_id = f"full-{det['model_id']}-{S}-{i}"
        first = min(r.seed_edges, key=lambda e: (int(se.set_index('edge_id').loc[e, 'timestamp']), e))
        r.tenant_id = int(se.set_index("edge_id").loc[first, "from_bank"])
    # schema v2: the currency-aware companions. v1 fields (closure, confidence, role arrays) are
    # left exactly as rings_from_edge_clusters produced them -- raw cross-currency sums.
    ccy = fill_currency_fields(rings, se)
    out = out_dir / f"rings_full_{det['model_id']}_{S}.parquet"
    write_rings_parquet(rings, out)

    ring_gt = pdir / "amlworld_ring_ground_truth.parquet"
    W = load_windows()
    blocks = evaluate_blocks(rings, se, ring_gt, scope, {k: w for k, w in W.items() if w.split == "test"}, 0.5, [0.3, 0.7])
    prim = blocks["primary"]
    run_dir = det["run_dir"](S)
    ref = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))["blocks"]["primary"]
    METRICS = ("ring_precision", "ring_recall", "ring_f1", "mean_jaccard", "member_coverage")
    # The reference metrics are stored at different precisions by run: R4 writes full floats, the
    # R6 runs round to 4 dp. Comparing a full float to a rounded one at 1e-9 would fail on a
    # correct rebuild, so the tolerance is taken FROM THE REFERENCE -- the number of decimals it
    # actually recorded - rather than fixed at 1e-9 and quietly loosened.
    dec = max((len(str(ref[m]).split(".")[-1]) for m in METRICS if "." in str(ref[m])), default=9)
    tol = 1e-9 if dec >= 9 else 0.5 * 10.0 ** -dec
    same = {m: (abs(prim[m] - ref[m]) <= tol) for m in METRICS}
    same_counts = {m: int(prim[m]) == int(ref[m]) for m in ("n_predicted", "n_truth", "n_matched") if m in ref}
    assert all(same.values()) and all(same_counts.values()), (
        f"{detector} seed {S}: metrics differ from the run (tol {tol:g}): {prim} vs {ref}")

    # Stronger, and precision-independent: the run saved its rings, so membership is compared
    # directly. This is the assertion that actually pins "same rings"; the metric check above only
    # pins "same score".
    membership_exact = None
    run_rings = run_dir / "rings.parquet"
    if run_rings.exists():
        # Read with pandas, not read_rings_parquet: a run's rings.parquet predates some contract
        # columns (the R4/R6 runs have no expanded_edge_probs), and only member_edges is needed.
        ref_rings = pd.read_parquet(run_rings, columns=["member_edges"])["member_edges"]
        # Sorted TUPLES, not frozensets: `sorted()` on frozensets compares with `<`, which is the
        # SUBSET relation -- a partial order -- so the arrangement is arbitrary and two identical
        # collections can compare unequal. This silently reported a mismatch on the gine rebuild.
        mine = sorted(tuple(sorted(int(e) for e in r.member_edges)) for r in rings)
        theirs = sorted(tuple(sorted(int(e) for e in m)) for m in ref_rings)
        membership_exact = mine == theirs
        assert membership_exact, (
            f"{detector} seed {S}: member-edge sets differ from {run_rings} "
            f"({len(rings)} rebuilt vs {len(ref_rings)} in the run)")
    probs_ok = all(len(r.expanded_edge_probs) == len(r.expanded_edges) for r in rings)
    topo = pd.Series([r.topology_type for r in rings]).value_counts().to_dict()
    log = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
           "contract_version": f"rings.parquet v{RINGS_SCHEMA_VERSION} (v1 Step 8; v2 Step 14 currency fields)", "detector_seed": S, "aggregator": "full",
           "detector": det["model_id"], "detector_note": det["note"],
           "inputs": {"scores": str(det["scores"](S)),
                      "embeddings": str(emb_path) if emb_path else None,
                      "checkpoint": str(ckpt_path) if ckpt_path else None,
                      "gfp": str(pdir / "amlworld_gfp_features_test.parquet"),
                      "policy": str(det["policy_dir"]), "affinity": str(det["affinity_dir"]),
                      "affinity_features": list(getattr(affinity, "features", [])),
                      "affinity_uses_embeddings": "cos_emb" in set(getattr(affinity, "features", [])),
                      "typing_head": str(HEAD_DIR[0]), "roles_config": "configs/roles.yaml",
                      "reproduced_run": str(run_dir)},
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
                                               "mean_non_nan": float(np.nanmean([r.conservation_closure for r in rings]))},
                      "currency_v2": ccy},
           "primary_window": {m: prim[m] for m in ("n_predicted", "n_truth", "n_matched", "ring_precision", "ring_recall", "ring_f1",
                                                   "mean_jaccard", "member_coverage", "ring_recall_ge3")},
           "reproduces_run": {"run_dir": str(run_dir), "metrics": same, "counts": same_counts,
                              "reference_decimals": dec, "tolerance": tol,
                              "member_edge_sets_identical": membership_exact},
           "reproduces_r4_average_run": same,           # kept: the gine logs have carried this key
           "seconds": round(time.time() - t0, 1), "out": str(out)}
    Path(str(out) + ".log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(f"[rings v{RINGS_SCHEMA_VERSION}] {detector} seed {S}: {len(rings)} rings | P {prim['ring_precision']:.4f} R {prim['ring_recall']:.4f} F1 {prim['ring_f1']:.4f} "
          f"(reproduces run: metrics {all(same.values())}, membership {membership_exact}) | expanded {log['fields']['n_expanded_edges']} with probs | "
          f"closure NaN {log['fields']['conservation_closure']['n_nan']} | topology {topo} | {log['seconds']}s -> {out.name}")
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--head-dir", type=Path, default=None, help="default: the val-chosen head (experiments/R5_typing/chosen_head.json)")
    ap.add_argument("--detector", default="gine_causal", choices=sorted(DETECTORS),
                    help="which detector's `full` run to materialise into the contract")
    ap.add_argument("--policy-dir", type=Path, default=None, help="default: the detector's own")
    ap.add_argument("--affinity-dir", type=Path, default=None, help="default: the detector's own")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "contract" / "out")
    args = ap.parse_args(argv)
    head_dir = args.head_dir or (REPO_ROOT / json.loads((R5 / "chosen_head.json").read_text(encoding="utf-8"))["chosen_dir"])
    print(f"[rings v{RINGS_SCHEMA_VERSION}] typing head: {head_dir}")
    head = TypingHead.load(head_dir)
    HEAD_DIR[0] = str(head_dir)
    det = DETECTORS[args.detector]
    policy = Policy.load(args.policy_dir or det["policy_dir"])
    affinity = Affinity.load(args.affinity_dir or det["affinity_dir"])
    print(f"[rings v{RINGS_SCHEMA_VERSION}] detector {args.detector}: policy {args.policy_dir or det['policy_dir']}, "
          f"affinity {args.affinity_dir or det['affinity_dir']} "
          f"({len(affinity.features)} features, cos_emb: {'cos_emb' in set(affinity.features)})")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    logs = [build_for_seed(S, head=head, policy=policy, affinity=affinity, out_dir=args.out_dir,
                           detector=args.detector) for S in args.seeds]
    f1 = [l["primary_window"]["ring_f1"] for l in logs]
    print(f"[rings v{RINGS_SCHEMA_VERSION}] {len(logs)} files for {args.detector}; primary ring-F1 "
          f"{np.mean(f1):.4f} +/- {np.std(f1, ddof=1):.4f}")


if __name__ == "__main__":
    main()
