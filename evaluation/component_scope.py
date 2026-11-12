"""Component-level scope as a third convention (deep-analysis #4). Evaluation only.

    python evaluation/component_scope.py --exp-root ../RS-e2e/experiments \
        --out results/tables/v36_component_scope.csv

The same shipped runs as evaluation/scope_sensitivity.py (C9), re-scored with no re-selection under:

    test_visible      reported convention: one target per in-scope ring, members = endpoints of its
                      in-window transactions
    component         each in-window CONNECTED PIECE of a test_visible ring is its own target
                      (pieces = edges joined when they share an account; the construction of
                      v3_diagnostics.edge_components / B13). A ring that is one piece is unchanged.
    component_ge3     the same, keeping only pieces with >= 3 accounts (the min_size a method can
                      emit), so 2-account pieces cannot inflate recall the way B3's Jaccard 0.3 does

Matching is unchanged (greedy one-to-one, Jaccard 0.5), so one prediction can match at most one piece.
Metrics per (policy, detector, method): ring P/R/F1 with a 1,000-resample bootstrap over targets
(seeds averaged inside), recall on targets >= 3 members, member coverage, STACK recall, and the
share of the test_visible loss (1 - recall) that disappears. Pass criterion (C9): the method
ordering b0 < b1b < proposed < full is preserved on ring-F1 for both detectors.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evaluation.ring_stats import metrics_from_evidence, ring_evidence  # noqa: E402
from evaluation.scope_sensitivity import boot  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from evaluation.v3_diagnostics import edge_components  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

RUNS = {("gine_causal", "b0"): ("R2_b0/gine_causal", "R1_gine_causal"),
        ("gine_causal", "b1b"): ("R3_expansion/runs/b1b", "R1_gine_causal"),
        ("gine_causal", "proposed"): ("R3_expansion/runs/proposed", "R1_gine_causal"),
        ("gine_causal", "full"): ("R4_partition/runs/average", "R1_gine_causal"),
        ("mega", "b0"): ("R6_b0/mega", "R6_mega"),
        ("mega", "proposed"): ("R6_full/mega/expand", "R6_mega"),
        ("mega", "full"): ("R6_full/mega", "R6_mega")}
ORDER = {"gine_causal": ["b0", "b1b", "proposed", "full"], "mega": ["b0", "proposed", "full"]}


def component_truth(truth: dict, patterns: dict, gt: pd.DataFrame, W, min_members: int = 1):
    """{(ring_id, k): accounts of piece k} over the in-window edges of each in-scope ring."""
    g = gt[gt["ring_id"].isin(truth) & W.mask(gt["timestamp_int"].to_numpy())].copy()
    g["edge_id"] = np.arange(len(g))
    out, pats, parent_of = {}, {}, {}
    for rid, e in g.groupby("ring_id"):
        comp = edge_components(e[["edge_id", "from_id", "to_id"]])
        pieces = defaultdict(set)
        for r in e.itertuples():
            pieces[comp[int(r.edge_id)]] |= {int(r.from_id), int(r.to_id)}
        pieces = sorted(pieces.values(), key=lambda s: (-len(s), min(s)))
        for k, accs in enumerate(pieces):
            accs = accs & truth[rid]
            if len(accs) >= min_members:
                out[(rid, k)] = accs
                pats[(rid, k)] = patterns.get(rid, "?")
                parent_of[(rid, k)] = rid
    return out, pats, parent_of


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exp-root", type=Path, default=REPO_ROOT / "experiments")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "v36_component_scope.csv")
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    W = load_windows()["primary"]
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")
    tv, pat = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds, "test_visible", verbose=False)
    comp, cpat, _ = component_truth(tv, pat, gt, W)
    comp3, cpat3, _ = component_truth(tv, pat, gt, W, min_members=3)
    assert set().union(*comp.values()) == set().union(*tv.values()), "pieces must partition the visible members"
    policies = {"test_visible": (tv, pat), "component": (comp, cpat), "component_ge3": (comp3, cpat3)}
    desc = {}
    for p, (t, pp) in policies.items():
        sz = [len(v) for v in t.values()]
        desc[p] = {"n_targets": len(t), "median_members": float(np.median(sz)), "n_ge3": int(sum(s >= 3 for s in sz)),
                   "n_rings_represented": len({k[0] if isinstance(k, tuple) else k for k in t}),
                   "n_stack": sum(1 for v in pp.values() if v == "STACK")}
        print(f"== {p}: {desc[p]}")
    n_multi = sum(1 for r in tv if (r, 1) in comp)
    print(f"   test_visible rings split into >= 2 pieces: {n_multi} of {len(tv)}")

    se_cache, rings_cache, rows = {}, {}, []
    for p, (truth, patterns) in policies.items():
        stack = [t for t, v in patterns.items() if v == "STACK"]
        for (det, meth), (rdir, sdir) in RUNS.items():
            root = a.exp_root / rdir
            seeds = [s for s in a.seeds if (root / f"seed{s}" / "rings.parquet").exists()]
            evs = []
            for s in seeds:
                if (sdir, s) not in se_cache:
                    se_cache[(sdir, s)] = build_scored_edges(a.exp_root / sdir / f"scores_test_seed{s}.parquet", "test",
                                                             model_id=det, seed=s, processed_dir=pdir)
                if (rdir, s) not in rings_cache:
                    rings_cache[(rdir, s)] = read_rings_any(root / f"seed{s}" / "rings.parquet")
                evs.append(ring_evidence(rings_cache[(rdir, s)], se_cache[(sdir, s)], truth, W, method=f"{det}/{meth}",
                                         seed=s, patterns=patterns, causal=True))
            ids = list(truth)
            f1, f1lo, f1hi = boot(evs, ids, "ring_f1", a.n_boot, 0)
            r, rlo, rhi = boot(evs, ids, "ring_recall", a.n_boot, 0)
            m = [metrics_from_evidence(e) for e in evs]
            st = [metrics_from_evidence(e, truth_ids=stack) for e in evs] if stack else []
            rows.append({"policy": p, "detector": det, "method": meth, "n_seeds": len(seeds), "n_targets": len(truth),
                         "ring_precision": float(np.mean([x["ring_precision"] for x in m])),
                         "ring_recall": r, "ring_recall_lo": rlo, "ring_recall_hi": rhi,
                         "ring_f1": f1, "ring_f1_lo": f1lo, "ring_f1_hi": f1hi,
                         "matched_per_seed": float(np.mean([x["n_matched"] for x in m])),
                         "ring_recall_ge3": float(np.nanmean([x["ring_recall_ge3"] for x in m])),
                         "member_coverage": float(np.mean([x["member_coverage"] for x in m])),
                         "stack_recall": float(np.mean([x["ring_recall"] for x in st])) if st else np.nan})
            print(f"  {p:14s} {det:12s} {meth:9s} P {rows[-1]['ring_precision']:.4f} R {r:.4f} F1 {f1:.4f} "
                  f"[{f1lo:.4f}, {f1hi:.4f}] | matched {rows[-1]['matched_per_seed']:.1f} | STACK {rows[-1]['stack_recall']:.3f}",
                  flush=True)
    d = pd.DataFrame(rows)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    order_ok = {}
    for p in policies:
        for det, ms in ORDER.items():
            f = d[(d.policy == p) & (d.detector == det)].set_index("method")["ring_f1"]
            order_ok[f"{p}/{det}"] = bool(all(f[ms[i]] < f[ms[i + 1]] for i in range(len(ms) - 1)))
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seeds": a.seeds, "window": W.as_dict(),
         "exp_root": str(a.exp_root), "targets": desc, "rings_split_into_pieces": n_multi, "ordering_preserved": order_ok,
         "rows": json.loads(d.to_json(orient="records"))}, indent=2), encoding="utf-8")
    print("\n== ring-F1 by policy ==")
    print(d.pivot_table(index=["detector", "method"], columns="policy", values="ring_f1").round(4).to_string())
    print("\n== ring recall by policy ==")
    print(d.pivot_table(index=["detector", "method"], columns="policy", values="ring_recall").round(4).to_string())
    print(f"\nordering preserved: {order_ok}\n-> {a.out}")


if __name__ == "__main__":
    main()
