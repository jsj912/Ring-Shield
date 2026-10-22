"""14.5a: what are the class (b) untouched rings made of? (description, not a detector)

    python evaluation/class_b_composition.py --dry-run
    python evaluation/class_b_composition.py

Class (b) is the largest single block of the ceiling after `min_size`: truth rings with >= 3 visible
members that **no included edge of any prediction touches** — 33.2 per seed for the shipped
pipeline, 24.0 for MEGA (`FINDINGS.md` B8). B16 established that history does not reconnect them.
This asks a different question: *what do they look like*, and is there a structural shape a
seed-free miner could key on.

Two parts:

1. **Composition** — class (b) by pattern, against each pattern's share of the 174 in-scope rings,
   so over- and under-representation is visible; and which patterns account for the 9.2-ring gap
   between the two detectors.
2. **Shape in the primary window** — per class (b) ring: visible members, longest directed path,
   whether a directed chain of >= 3 hops exists whose consecutive edges fall inside the run's own
   val-chosen delta_t and conserve amount within the roles tolerance, and whether a complete
   bipartite block of >= 2x2 exists among its visible edges.

**This step builds no miner and tunes nothing.** It describes the targets so that a later decision
about whether a structural seeder has anything to aim at is made on measurement.

Output: `results/tables/r14_class_b_composition.csv` (+ `.json`) and `docs/CLASS_B_COMPOSITION.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RUNS = {
    "gine_causal": (REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average",
                    REPO_ROOT / "experiments" / "R1_gine_causal", "gine_causal"),
    "mega": (REPO_ROOT / "experiments" / "R6_full" / "mega",
             REPO_ROOT / "experiments" / "R6_mega", "mega"),
}
TAU_AMOUNT = 0.25          # the roles.py conservation tolerance, reused unchanged


def longest_directed_path(edges: pd.DataFrame) -> int:
    """Longest simple directed path (in hops) over the account graph of `edges`. Small graphs only."""
    adj = defaultdict(set)
    for r in edges.itertuples():
        adj[r.from_id].add(r.to_id)
    best = 0

    def walk(node, seen, depth):
        nonlocal best
        best = max(best, depth)
        for nxt in adj.get(node, ()):
            if nxt not in seen and depth < 24:
                walk(nxt, seen | {nxt}, depth + 1)

    for start in list(adj):
        walk(start, {start}, 0)
    return best


def has_conserving_chain(edges: pd.DataFrame, delta_s: int, min_hops: int = 3) -> bool:
    """A directed path of >= min_hops whose consecutive edges are within delta_s and conserve amount."""
    by_src = defaultdict(list)
    for r in edges.itertuples():
        by_src[r.from_id].append(r)

    def extend(edge, seen, hops):
        if hops >= min_hops:
            return True
        for nxt in by_src.get(edge.to_id, ()):
            if nxt.to_id in seen or nxt.EdgeID == edge.EdgeID:
                continue
            dt = int(nxt.Timestamp) - int(edge.Timestamp)
            if dt < 0 or dt > delta_s:
                continue
            a, b = float(edge.amount), float(nxt.amount)
            if max(a, b) > 0 and abs(a - b) / max(a, b) > TAU_AMOUNT:
                continue
            if extend(nxt, seen | {nxt.to_id}, hops + 1):
                return True
        return False

    return any(extend(e, {e.from_id, e.to_id}, 1) for e in edges.itertuples())


def has_bipartite_block(edges: pd.DataFrame, k: int = 2) -> bool:
    """A complete directed bipartite block of >= k x k among the visible edges."""
    pairs = {(int(r.from_id), int(r.to_id)) for r in edges.itertuples()}
    if len(pairs) < k * k:
        return False
    srcs = sorted({s for s, _ in pairs})
    tgt_of = {s: {t for ss, t in pairs if ss == s} for s in srcs}
    for a, b in combinations(srcs, k):
        shared = tgt_of[a] & tgt_of[b]
        if len(shared) >= k:
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / "results" / "tables" / "r14_class_b_composition.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        a.seeds = a.seeds[:2]
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    te = pd.read_parquet(pdir / "amlworld_test.parquet",
                         columns=["EdgeID", "from_id", "to_id", "Timestamp", "Amount Received", "ring_id"])
    te = te.rename(columns={"Amount Received": "amount"})
    ring_edges = {int(r): g for r, g in te[te.ring_id > 0].groupby("ring_id")}

    base = pd.Series({p: 0 for p in sorted(set(patterns.values()))}, dtype=float)
    for t in truth:
        base[patterns[t]] += 1
    rows, shape_rows = [], []
    for det, (root, sdir, mid) in RUNS.items():
        counts = defaultdict(list)
        for s in a.seeds:
            rp = root / f"seed{s}" / "rings.parquet"
            if not rp.exists():
                continue
            cfg = yaml.safe_load((root / f"seed{s}" / "config.yaml").read_text(encoding="utf-8"))["chosen"]
            delta_s = int(round(float(cfg.get("delta_t_h", 24)) * 3600))
            se = build_scored_edges(sdir / f"scores_test_seed{s}.parquet", "test",
                                    model_id=mid, seed=s, processed_dir=pdir)
            kl = classify(read_rings_any(rp), se, truth, patterns, W)
            ts = se.set_index("edge_id")["timestamp"]
            in_win = set(ts.index[W.mask(ts.values)].tolist())
            b = kl[kl["klass"] == "b_untouched"]
            per = defaultdict(int)
            for tid in b["ring_id"]:
                pat = patterns.get(tid, "?")
                per[pat] += 1
                g = ring_edges.get(int(tid))
                if g is None:
                    continue
                vis = g[g["EdgeID"].isin(in_win)]
                if vis.empty:
                    continue
                accs = set(vis["from_id"]) | set(vis["to_id"])
                shape_rows.append({
                    "detector": det, "seed": s, "ring_id": int(tid), "pattern": pat,
                    "visible_members": len(accs), "visible_edges": len(vis),
                    "longest_directed_path": longest_directed_path(vis),
                    "has_conserving_chain_3hop": has_conserving_chain(vis, delta_s),
                    "has_bipartite_2x2": has_bipartite_block(vis),
                    "delta_t_h": cfg.get("delta_t_h")})
            for pat in base.index:
                counts[pat].append(per.get(pat, 0))
        n_seeds = max((len(v) for v in counts.values()), default=0)
        tot = sum(np.mean(v) for v in counts.values()) if counts else 0.0
        for pat in base.index:
            m = float(np.mean(counts[pat])) if counts[pat] else 0.0
            rows.append({"detector": det, "pattern": pat, "class_b_per_seed": m,
                         "share_of_class_b": (m / tot) if tot else np.nan,
                         "n_in_scope_rings": int(base[pat]),
                         "share_of_in_scope": float(base[pat] / len(truth)),
                         "over_representation": ((m / tot) / (base[pat] / len(truth)))
                         if tot and base[pat] else np.nan,
                         "n_seeds": n_seeds})
        print(f"{det}: class (b) {tot:.1f} per seed over {n_seeds} seeds")

    d = pd.DataFrame(rows)
    shp = pd.DataFrame(shape_rows)
    print("\n== composition by pattern (mean rings per seed) ==")
    piv = d.pivot_table(index="pattern", columns="detector", values="class_b_per_seed")
    piv["in_scope"] = [int(base[p]) for p in piv.index]
    piv["gine_share_%"] = (piv.get("gine_causal", 0) / piv.get("gine_causal", pd.Series()).sum() * 100).round(1)
    piv["diff_gine_minus_mega"] = (piv.get("gine_causal", 0) - piv.get("mega", 0)).round(2)
    print(piv.round(2).to_string())
    if len(shp):
        print("\n== shape of class (b) rings in the primary window ==")
        g = shp.groupby(["detector", "pattern"]).agg(
            n=("ring_id", "size"), members=("visible_members", "median"),
            longest_path=("longest_directed_path", "median"),
            chain3=("has_conserving_chain_3hop", "mean"), bip=("has_bipartite_2x2", "mean"))
        print(g.round(3).to_string())
    if a.dry_run:
        print("\n[class_b] DRY RUN -- nothing written")
        return d, shp
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    shp.to_csv(str(a.out).replace(".csv", "_shape.csv"), index=False)
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "window": a.window, "scope": "test_visible", "seeds": a.seeds,
         "note": "description of the class (b) targets; no miner is built or tuned in this step",
         "amount_tolerance": TAU_AMOUNT,
         "composition": json.loads(d.to_json(orient="records")),
         "shape_summary": json.loads(shp.groupby(["detector", "pattern"]).agg(
             n=("ring_id", "size"), median_members=("visible_members", "median"),
             median_longest_path=("longest_directed_path", "median"),
             share_conserving_chain=("has_conserving_chain_3hop", "mean"),
             share_bipartite=("has_bipartite_2x2", "mean")).reset_index().to_json(orient="records"))
         if len(shp) else []}, indent=2), encoding="utf-8")
    print(f"\n-> {a.out}")
    return d, shp


if __name__ == "__main__":
    main()
