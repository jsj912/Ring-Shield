"""
Ring aggregation CLI (E7 / B0). Since Step 4 this is a thin wrapper: the aggregation lives in
ringshield/aggregators/cc.py (aggregate_cc) and the ground truth in ringshield/truth.py; the
command line, its output CSV (E7_RING_CSV_COLUMNS, legacy CSV time basis) and the
.metrics.json beside it are unchanged so old commands still work.

    score edges  ->  threshold  ->  connected components  ->  filter  ->  rings

Input is a legacy predictions_with_ids.csv (E6; score_test_set.py is deleted), which must
carry EdgeID, from_id, to_id, Timestamp and pred_prob. Ground truth follows
docs/RING_GROUND_TRUTH_DEFINITION.md.

    python models/ring_aggregator.py ^
        --preds experiments/E6_tgn/predictions_with_ids.csv ^
        --ring-gt data/processed/amlworld_ring_ground_truth.parquet ^
        --out experiments/E7/rings_gine.csv ^
        --top-pct 0.5 --min-size 3

Threshold: prefer --top-pct (keep the top N% of scored edges) over an absolute
--threshold. Per-seed optimal thresholds on this dataset range 0.46 to 0.71
even though F1 barely moves, so the score scale is not comparable across
seeds; a percentile cutoff is. --min-conf / --min-density are applied to the
aggregator's rings afterwards (density is reported, not filtered, by default;
see ringshield/aggregators/cc.py on why 0.4 rejects real topologies).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from contract.schema import E7_RING_CSV_COLUMNS  # noqa: E402
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from preprocessing.account_bank import bank_of_series, load_account_bank_map, load_paths  # noqa: E402
from ringshield.aggregators.cc import aggregate_cc, threshold_for_pct  # noqa: E402
from ringshield.truth import load_ground_truth, split_window  # noqa: E402

# re-exported for callers that still import them from here
__all__ = ["aggregate_cc", "load_ground_truth", "legacy_preds_to_scored_edges", "main"]


def legacy_preds_to_scored_edges(preds: pd.DataFrame, offset_s: int) -> pd.DataFrame:
    """predictions_with_ids.csv rows -> the scored_edges columns aggregate_cc needs
    (timestamps moved to the loader basis, banks from the account map)."""
    bank_of = bank_of_series(load_account_bank_map())
    se = pd.DataFrame({
        "edge_id": preds["EdgeID"].to_numpy(np.int64),
        "from_id": preds["from_id"].to_numpy(np.int64),
        "to_id": preds["to_id"].to_numpy(np.int64),
        "timestamp": preds["Timestamp"].to_numpy(np.int64) + offset_s,
        "score_raw": preds["pred_prob"].to_numpy(float),
    })
    se["from_bank"] = bank_of.reindex(se["from_id"]).to_numpy()
    se["to_bank"] = bank_of.reindex(se["to_id"]).to_numpy()
    assert not se[["from_bank", "to_bank"]].isna().any().any(), "account without a bank in the account map"
    se[["from_bank", "to_bank"]] = se[["from_bank", "to_bank"]].astype(np.int64)
    return se


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preds", type=Path, required=True)
    ap.add_argument("--ring-gt", type=Path, required=True)
    ap.add_argument("--test-parquet", type=Path, default=None,
                    help="split parquet defining the scope window (loader time basis); "
                         "default <paths.yaml processed_dir>/amlworld_test.parquet")
    ap.add_argument("--out", type=Path, required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--threshold", type=float,
                   help="absolute probability cutoff (not seed-comparable)")
    g.add_argument("--top-pct", type=float,
                   help="keep the top N%% of scored edges (recommended)")
    ap.add_argument("--min-size", type=int, default=3)
    ap.add_argument("--min-conf", type=float, default=0.0)
    ap.add_argument("--min-density", type=float, default=0.0,
                    help="0.4 from FR04.6 rejects cycles and fan-outs; see "
                         "ringshield/aggregators/cc.py before raising this")
    ap.add_argument("--max-gap-hours", type=float, default=None)
    ap.add_argument("--match-threshold", type=float, default=0.5)
    ap.add_argument("--scope", choices=["test_visible", "strict", "majority", "start"],
                    default="test_visible")
    args = ap.parse_args()

    print(f"Loading {args.preds} ...")
    preds = pd.read_csv(args.preds)
    n_all = len(preds)
    preds = preds[preds["pred_prob"].notna()]
    if len(preds) < n_all:
        print(f"  {n_all - len(preds)} rows never scored (neighbour sampling); "
              f"excluded")
    print(f"  {len(preds)} scored transactions")

    scores = preds["pred_prob"].to_numpy(float)
    if args.top_pct is not None:
        threshold = threshold_for_pct(scores, args.top_pct)
        print(f"  top {args.top_pct}% -> threshold {threshold:.4f}")
    else:
        threshold = args.threshold

    # Scope window in the LOADER time basis, taken from the split parquet. The
    # predictions CSV is legacy_csv_time_offset_s (10 s) lower and must not be
    # used here: it silently dropped ring 346 from the strict set (85 vs 86).
    paths = load_paths()
    test_parquet = args.test_parquet or paths["processed_dir"] / "amlworld_test.parquet"
    t_min, t_max = split_window(test_parquet)
    offset = int(paths["legacy_csv_time_offset_s"])
    observed = int(preds["Timestamp"].min()) - t_min
    if observed != -offset:
        raise SystemExit(f"predictions Timestamp basis is off by {observed}s from the split "
                         f"parquet; expected -{offset}s (configs/paths.yaml legacy_csv_time_offset_s)")
    print(f"  scope window [{t_min}, {t_max}] from {test_parquet} (loader basis; "
          f"predictions CSV is {offset}s lower)")
    print(f"Loading {args.ring_gt} ...")
    truth, patterns = load_ground_truth(args.ring_gt, t_min, t_max, args.scope)
    if not truth:
        raise SystemExit("No ground-truth rings in scope -- check the scope "
                         "policy and that timestamp units match.")

    print("Aggregating ...")
    se = legacy_preds_to_scored_edges(preds, offset)
    seed_frac_pct = args.top_pct if args.top_pct is not None else 100.0 * float((scores >= threshold).mean())
    rings = aggregate_cc(se, seed_frac_pct, args.min_size, args.max_gap_hours,
                         threshold=threshold, verbose=True)
    n_before = len(rings)
    rings = [r for r in rings if r.confidence >= args.min_conf and r.density >= args.min_density]
    if len(rings) < n_before:
        print(f"  Dropped by --min-conf/--min-density: {n_before - len(rings)}")
    print(f"  Candidate rings: {len(rings)}")

    print("\nEvaluating ...")
    metrics = evaluate_rings([r.member_set for r in rings], truth,
                             args.match_threshold, patterns)
    print(metrics)

    # Legacy CSV: same columns and the legacy CSV time basis (offset removed again).
    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, r in enumerate(rings):
        rows.append({
            "n_members": r.n_members, "n_edges": r.n_edges,
            "confidence": round(r.confidence, 4), "max_edge_prob": round(r.max_edge_prob, 4),
            "density": round(r.density, 4),
            "start_time": r.start_time - offset, "end_time": r.end_time - offset,
            "duration_hours": round(r.duration_hours, 2),
            "ring_idx": i, "members": "|".join(str(m) for m in r.members),
        })
    pd.DataFrame(rows, columns=E7_RING_CSV_COLUMNS).to_csv(args.out, index=False)
    print(f"\nWrote {len(rows)} rings -> {args.out}")

    meta = args.out.with_suffix(".metrics.json")
    meta.write_text(json.dumps({
        "predictions": str(args.preds),
        "threshold": threshold,
        "top_pct": args.top_pct,
        "min_size": args.min_size,
        "min_conf": args.min_conf,
        "min_density": args.min_density,
        "max_gap_hours": args.max_gap_hours,
        "match_threshold": args.match_threshold,
        "scope_policy": args.scope,
        "scope_window": [t_min, t_max],
        "scope_window_source": str(test_parquet),
        "legacy_csv_time_offset_s": offset,
        "aggregator": "ringshield.aggregators.cc.aggregate_cc",
        **metrics.to_dict(),
    }, indent=2))
    print(f"Wrote metrics -> {meta}")


if __name__ == "__main__":
    main()
