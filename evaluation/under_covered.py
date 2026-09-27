"""Where the largest remaining loss actually is: the under-covered rings (Step 11 follow-up).

    python evaluation/under_covered.py
    python evaluation/under_covered.py --runs gine_full --dry-run

`evaluation/unmatched_rings.py` puts every unmatched truth ring into one class. On the primary
window the biggest of the touched-but-unmatched classes is **under-covered** — 6.8 rings per seed
for the shipped pipeline against 5.2 over-merged — and the partition stage cannot act on it by
construction: it re-cuts predictions that hold more than one ring, and an under-covered ring is one
the prediction did not reach far enough into.

This script asks what those rings look like, because "the residual is a partition problem" is only
true of the over-merged half. For every under-covered ring it records the best-overlapping
prediction and decomposes the Jaccard shortfall into its two directions:

    coverage  = |pred ∩ truth| / |truth|     how much of the ring the prediction found
    purity    = |pred ∩ truth| / |pred|      how much of the prediction belongs to the ring

    purity ≈ 1, coverage < 1   the prediction is a clean SUBSET -- members are missing, which is
                               expansion's job and nobody else's
    coverage ≈ 1, purity < 1   the prediction found the ring and dragged in strangers -- a
                               precision problem at the edge of the component
    both < 1                   partial overlap in both directions

and reports how far each ring sits from the Jaccard 0.5 bar, since a ring at 0.45 and a ring at
0.10 imply completely different work.

Outputs `results/tables/r_under_covered.csv` (one row per under-covered ring per seed per run) and
`.json` (the aggregate decomposition per run, which is what the report quotes).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_metrics import match_rings  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.unmatched_rings import classify  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.evaluate import restrict_rings  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RUNS = {
    "gine_full": {"root": REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average",
                  "scores": REPO_ROOT / "experiments" / "R1_gine_causal", "model_id": "gine_causal"},
    "gine_b2": {"root": REPO_ROOT / "experiments" / "R4_partition" / "runs" / "b2",
                "scores": REPO_ROOT / "experiments" / "R1_gine_causal", "model_id": "gine_causal"},
    "mega_full": {"root": REPO_ROOT / "experiments" / "R6_full" / "mega",
                  "scores": REPO_ROOT / "experiments" / "R6_mega", "model_id": "mega"},
}


def rows_for(run: str, spec: dict, seeds, truth, patterns, W, pdir) -> list[dict]:
    out = []
    for s in seeds:
        rp = spec["root"] / f"seed{s}" / "rings.parquet"
        if not rp.exists():
            continue
        se = build_scored_edges(spec["scores"] / f"scores_test_seed{s}.parquet", "test",
                                model_id=spec["model_id"], seed=s, processed_dir=pdir)
        rings = read_rings_any(rp)
        kl = classify(rings, se, truth, patterns, W).set_index("ring_id")

        ts = se.set_index("edge_id")["timestamp"]
        in_win = set(ts.index[W.mask(ts.values)].tolist())
        pred = restrict_rings(rings, se, W)
        kept = [i for i, r in enumerate(rings) if any(e in in_win for e in r.member_edges)]
        assert len(kept) == len(pred)
        matched_truth = {m.truth_id for m in match_rings(pred, truth, 0.5)[0]}

        mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
        seed_ids = set(se.loc[mask, "edge_id"]) & in_win
        ring_edges = pd.read_parquet(pdir / "amlworld_test.parquet", columns=["EdgeID", "ring_id"])
        ring_edges = {int(r): set(g["EdgeID"].astype(int)) for r, g in
                      ring_edges[ring_edges["ring_id"] > 0].groupby("ring_id")}

        for tid, accs in truth.items():
            if tid in matched_truth or kl.loc[tid, "klass"] != "c_under_covered":
                continue
            best_j, best = 0.0, None
            for P in pred:
                inter = len(P & accs)
                if inter == 0:
                    continue
                j = inter / len(P | accs)
                if j > best_j:
                    best_j, best = j, P
            if best is None:
                continue
            inter = len(best & accs)
            out.append({"run": run, "seed": s, "ring_id": int(tid),
                        "pattern": patterns.get(tid, "?"), "truth_members": len(accs),
                        "pred_members": len(best), "intersection": inter,
                        "coverage": inter / len(accs), "purity": inter / len(best),
                        "jaccard": best_j, "gap_to_bar": 0.5 - best_j,
                        "n_seed_edges_on_ring": len(ring_edges.get(int(tid), set()) & seed_ids)})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="*", default=list(RUNS))
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r_under_covered.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        a.seeds = a.seeds[:2]
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                        "test_visible", verbose=False)
    rows = []
    for run in a.runs:
        rows += rows_for(run, RUNS[run], a.seeds, truth, patterns, W, pdir)
        print(f"  {run}: {len([r for r in rows if r['run'] == run])} under-covered ring-instances", flush=True)
    d = pd.DataFrame(rows)
    if d.empty:
        print("no under-covered rings found")
        return d

    summary = {}
    for run, g in d.groupby("run"):
        n = len(g)
        subset = g["purity"] >= 0.999
        summary[run] = {
            "ring_instances": n, "per_seed": round(n / len(a.seeds), 2),
            "median_truth_members": float(g["truth_members"].median()),
            "median_pred_members": float(g["pred_members"].median()),
            "median_coverage": round(float(g["coverage"].median()), 4),
            "median_purity": round(float(g["purity"].median()), 4),
            "median_jaccard": round(float(g["jaccard"].median()), 4),
            "median_gap_to_bar": round(float(g["gap_to_bar"].median()), 4),
            "share_clean_subset_purity_1": round(float(subset.mean()), 4),
            "share_within_0.10_of_bar": round(float((g["gap_to_bar"] <= 0.10).mean()), 4),
            "share_within_0.20_of_bar": round(float((g["gap_to_bar"] <= 0.20).mean()), 4),
            "median_seed_edges_on_ring": float(g["n_seed_edges_on_ring"].median()),
            "rings_with_zero_seed_edges": int((g["n_seed_edges_on_ring"] == 0).sum()),
            "by_pattern": g.groupby("pattern").size().to_dict()}
        s = summary[run]
        print(f"\n== {run}: {s['per_seed']} under-covered rings/seed ==")
        print(f"   coverage {s['median_coverage']:.3f} | purity {s['median_purity']:.3f} | "
              f"Jaccard {s['median_jaccard']:.3f} (gap to bar {s['median_gap_to_bar']:.3f})")
        print(f"   clean subsets (purity 1.0): {s['share_clean_subset_purity_1']:.1%} | "
              f"within 0.10 of the bar: {s['share_within_0.10_of_bar']:.1%}")
        print(f"   truth {s['median_truth_members']:.0f} members vs prediction {s['median_pred_members']:.0f}; "
              f"seed edges on the ring: median {s['median_seed_edges_on_ring']:.0f}, "
              f"{s['rings_with_zero_seed_edges']} instances with none")

    if a.dry_run:
        print("\n[under_covered] DRY RUN -- nothing written")
        return d
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "window": a.window, "scope": "test_visible", "seeds": a.seeds,
         "definition": "truth rings classified c_under_covered: touched, best Jaccard < 0.5, and no "
                       "covering prediction holds a second truth ring",
         "decomposition": "coverage = |pred & truth| / |truth|; purity = |pred & truth| / |pred|",
         "summary": summary}, indent=2), encoding="utf-8")
    print(f"\n-> {a.out}")
    return d


if __name__ == "__main__":
    main()
