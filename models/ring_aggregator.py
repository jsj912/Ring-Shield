"""
Ring aggregation for RingShield (E7).

Turns per-transaction fraud scores into ring-level detections:

    score edges  ->  threshold  ->  connected components  ->  filter  ->  rings

Input is a predictions_with_ids.csv produced by score_test_set.py, which must
carry from_id, to_id, Timestamp and pred_prob. Ground truth follows
docs/RING_GROUND_TRUTH_DEFINITION.md.

    python models/ring_aggregator.py ^
        --preds experiments/E6_tgn/predictions_with_ids.csv ^
        --ring-gt data/processed/amlworld_ring_ground_truth.parquet ^
        --out experiments/E7/rings_gine.csv ^
        --top-pct 0.5 --min-size 3

Threshold: prefer --top-pct (keep the top N% of scored edges) over an absolute
--threshold. Per-seed optimal thresholds on this dataset range 0.46 to 0.71
even though F1 barely moves, so the score scale is not comparable across
seeds; a percentile cutoff is.

A note on density. FR04.6 suggests a min density of 0.4, where density for a
directed component is m / (n * (n-1)). Almost no real laundering topology
clears that: a 5-node CYCLE has density 0.25, and a 1-to-5 FAN-OUT has 0.167.
The default here is therefore 0.0, and density is reported rather than used as
a filter. If you enable it, check what it removes before trusting the result.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from evaluation.ring_metrics import evaluate_rings  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402


# ---------------------------------------------------------------------------
# Ground truth
# ---------------------------------------------------------------------------
def load_ground_truth(path: Path, t_min: float, t_max: float, policy: str):
    """Build {ring_id: member set} and {ring_id: pattern} for in-scope rings.

    A ring is in scope per D1 section 4. `policy` decides boundary rings:
        test_visible -- at least one transaction inside [t_min, t_max]; the
                        member set is the union of from_id/to_id over the
                        ring's transactions inside the window only (D1 default,
                        decided 2026-09-16)
        strict       -- every transaction inside [t_min, t_max]; full members
        majority     -- more than half its transactions inside; full members
        start        -- its earliest transaction inside; full members
    """
    gt = pd.read_parquet(path)
    for col in ("ring_id", "from_id", "to_id", "timestamp_int"):
        if col not in gt.columns:
            raise SystemExit(f"Ground truth is missing column '{col}'. "
                             f"Found: {list(gt.columns)}")

    inside = (gt["timestamp_int"] >= t_min) & (gt["timestamp_int"] <= t_max)
    gt = gt.assign(_in=inside)

    grp = gt.groupby("ring_id")
    frac = grp["_in"].mean()
    if policy == "test_visible":
        keep = frac[frac > 0].index
    elif policy == "strict":
        keep = frac[frac == 1.0].index
    elif policy == "majority":
        keep = frac[frac > 0.5].index
    elif policy == "start":
        starts = grp["timestamp_int"].min()
        keep = starts[(starts >= t_min) & (starts <= t_max)].index
    else:
        raise SystemExit(f"unknown scope policy: {policy}")

    sub = gt[gt["ring_id"].isin(keep)]
    if policy == "test_visible":
        sub = sub[sub["_in"]]  # scored members: only accounts seen in the window
    truth = {rid: set(g["from_id"]) | set(g["to_id"])
             for rid, g in sub.groupby("ring_id")}
    patterns = (sub.groupby("ring_id")["pattern_type"].first().to_dict()
                if "pattern_type" in sub.columns else {})

    n_total = gt["ring_id"].nunique()
    n_partial = int(((frac > 0) & (frac < 1)).sum())
    print(f"  Ground truth: {n_total} rings total, {len(truth)} in scope "
          f"(policy={policy})")
    print(f"    Rings straddling the split boundary: {n_partial}")
    if truth:
        sizes = [len(v) for v in truth.values()]
        print(f"    In-scope ring sizes: min {min(sizes)}, "
              f"median {int(np.median(sizes))}, max {max(sizes)}")
        n_tiny = sum(1 for s in sizes if s < 3)
        if n_tiny:
            print(f"    WARNING: {n_tiny} in-scope rings have <3 members and "
                  f"are undetectable under --min-size 3 (D1 section 6).")
    return truth, patterns


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def aggregate(
    preds: pd.DataFrame,
    threshold: float,
    min_size: int = 3,
    min_conf: float = 0.0,
    min_density: float = 0.0,
    max_gap_hours: float | None = None,
):
    """Threshold edges, group into components, filter, return ring records."""
    flagged = preds[preds["pred_prob"] >= threshold].copy()
    print(f"  Edges above cutoff: {len(flagged)} / {len(preds)} "
          f"({len(flagged) / len(preds) * 100:.3f}%)")
    if flagged.empty:
        return []

    G = nx.Graph()
    for f, t, ts, p in flagged[["from_id", "to_id", "Timestamp",
                                "pred_prob"]].itertuples(index=False):
        if G.has_edge(f, t):
            e = G[f][t]
            e["probs"].append(p)
            e["times"].append(ts)
        else:
            G.add_edge(f, t, probs=[p], times=[ts])

    components = list(nx.connected_components(G))
    print(f"  Raw connected components: {len(components)}")

    if max_gap_hours is not None:
        components = _split_by_time(G, components, max_gap_hours * 3600)
        print(f"  After time-window splitting: {len(components)}")

    rings, dropped = [], {"size": 0, "conf": 0, "density": 0}
    for members in components:
        n = len(members)
        if n < min_size:
            dropped["size"] += 1
            continue
        sub = G.subgraph(members)
        m = sub.number_of_edges()
        probs = [p for _, _, d in sub.edges(data=True) for p in d["probs"]]
        times = [t for _, _, d in sub.edges(data=True) for t in d["times"]]
        conf = float(np.mean(probs))
        density = m / (n * (n - 1)) if n > 1 else 0.0
        if conf < min_conf:
            dropped["conf"] += 1
            continue
        if density < min_density:
            dropped["density"] += 1
            continue
        rings.append({
            "members": set(members),
            "n_members": n,
            "n_edges": m,
            "confidence": round(conf, 4),
            "max_edge_prob": round(float(np.max(probs)), 4),
            "density": round(density, 4),
            "start_time": int(min(times)),
            "end_time": int(max(times)),
            "duration_hours": round((max(times) - min(times)) / 3600, 2),
        })

    print(f"  Dropped -- size:{dropped['size']} conf:{dropped['conf']} "
          f"density:{dropped['density']}")
    print(f"  Candidate rings: {len(rings)}")
    if rings:
        big = max(r["n_members"] for r in rings)
        if big > 100:
            print(f"  WARNING: largest candidate has {big} members. Components "
                  f"chain through shared accounts, so a few false-positive "
                  f"edges on a hub can merge many rings. Try --max-gap-hours.")
    rings.sort(key=lambda r: -r["confidence"])
    return rings


def _split_by_time(G, components, max_gap_seconds):
    """Re-cluster each component using only edges close in time.

    Laundering rings are short bursts. Dropping links between transactions far
    apart in time breaks the chains that merge unrelated rings through a busy
    shared account.
    """
    out = []
    for members in components:
        sub = G.subgraph(members)
        H = nx.Graph()
        H.add_nodes_from(members)
        for u, v, d in sub.edges(data=True):
            H.add_edge(u, v, t=float(np.median(d["times"])))
        # Union-find over edges sorted by time, joining only within the window.
        edges = sorted(H.edges(data=True), key=lambda e: e[2]["t"])
        K = nx.Graph()
        K.add_nodes_from(members)
        for i, (u, v, d) in enumerate(edges):
            K.add_edge(u, v)
            for u2, v2, d2 in edges[i + 1:]:
                if d2["t"] - d["t"] > max_gap_seconds:
                    break
                if u2 in (u, v) or v2 in (u, v):
                    K.add_edge(u2, v2)
        out.extend(nx.connected_components(K))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
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
                         "the module docstring before raising this")
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

    if args.top_pct is not None:
        threshold = float(np.percentile(preds["pred_prob"],
                                        100 - args.top_pct))
        print(f"  top {args.top_pct}% -> threshold {threshold:.4f}")
    else:
        threshold = args.threshold

    # Scope window in the LOADER time basis, taken from the split parquet. The
    # predictions CSV is legacy_csv_time_offset_s (10 s) lower and must not be
    # used here: it silently dropped ring 346 from the strict set (85 vs 86).
    paths = load_paths()
    test_parquet = args.test_parquet or paths["processed_dir"] / "amlworld_test.parquet"
    ts = pd.read_parquet(test_parquet, columns=["Timestamp"])["Timestamp"]
    t_min, t_max = int(ts.min()), int(ts.max())
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
    rings = aggregate(preds, threshold, args.min_size, args.min_conf,
                      args.min_density, args.max_gap_hours)

    print("\nEvaluating ...")
    metrics = evaluate_rings([r["members"] for r in rings], truth,
                             args.match_threshold, patterns)
    print(metrics)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, r in enumerate(rings):
        row = {k: v for k, v in r.items() if k != "members"}
        row["ring_idx"] = i
        row["members"] = "|".join(str(m) for m in sorted(r["members"]))
        rows.append(row)
    pd.DataFrame(rows).to_csv(args.out, index=False)
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
        **metrics.to_dict(),
    }, indent=2))
    print(f"Wrote metrics -> {meta}")


if __name__ == "__main__":
    main()
