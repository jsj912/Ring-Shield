"""Step 14 item 4: how much of a ring-level result is the scope convention? (evaluation only)

    python evaluation/scope_sensitivity.py --dry-run
    python evaluation/scope_sensitivity.py

No model is re-run and no parameter is re-chosen. The **same shipped runs** are re-scored under two
scope policies:

    test_visible     (default, reported) a ring is in scope for the window if it has >= 1
                     transaction there, and its member set is the accounts of *those* transactions
    full_membership  (sensitivity only)  same in-scope rule, but the member set is ALL of the ring's
                     accounts across the dataset

`test_visible` scores a method only against evidence it could have seen, and makes long patterns
structurally unmatchable whenever the split cuts them (`FINDINGS.md` B13/B16). `full_membership`
keeps rings intact and describes the laundering attempt better, but scores a method against members
it had no way to observe — a perfect in-window method is still penalised. Neither is obviously
right; **the gap between the two rows is the size of the convention's effect**, and that is the only
thing this table is for. The `full_membership` row never becomes a headline.

Output: `results/tables/r14_scope_sensitivity.csv` (+ `.json`).
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

from evaluation.ring_stats import metrics_from_evidence, ring_evidence  # noqa: E402
from evaluation.step9_tables import read_rings_any  # noqa: E402
from preprocessing.account_bank import load_paths  # noqa: E402
from ringshield.aggregators.cc import SELECT_COL, seed_mask_for_pct  # noqa: E402
from ringshield.run_rings import _git_commit  # noqa: E402
from ringshield.scored_edges import build_scored_edges  # noqa: E402
from ringshield.truth import load_ground_truth  # noqa: E402
from ringshield.windows import load_windows  # noqa: E402

R1 = REPO_ROOT / "experiments" / "R1_gine_causal"
R6M = REPO_ROOT / "experiments" / "R6_mega"
RUNS = {
    ("gine_causal", "b0"): (REPO_ROOT / "experiments" / "R2_b0" / "gine_causal", R1, "gine_causal"),
    ("gine_causal", "b1b"): (REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "b1b", R1, "gine_causal"),
    ("gine_causal", "proposed"): (REPO_ROOT / "experiments" / "R3_expansion" / "runs" / "proposed", R1, "gine_causal"),
    ("gine_causal", "full"): (REPO_ROOT / "experiments" / "R4_partition" / "runs" / "average", R1, "gine_causal"),
    ("mega", "b0"): (REPO_ROOT / "experiments" / "R6_b0" / "mega", R6M, "mega"),
    ("mega", "proposed"): (REPO_ROOT / "experiments" / "R6_full" / "mega" / "expand", R6M, "mega"),
    ("mega", "full"): (REPO_ROOT / "experiments" / "R6_full" / "mega", R6M, "mega"),
}
POLICIES = ["test_visible", "full_membership"]


def boot(evs, ids, metric, n, seed):
    ids = list(ids)
    if not ids:
        return float("nan"), float("nan"), float("nan")
    point = float(np.nanmean([metrics_from_evidence(e, truth_ids=ids)[metric] for e in evs]))
    rng = np.random.default_rng(seed)
    d = np.empty(n)
    for b in range(n):
        r = [ids[i] for i in rng.integers(0, len(ids), len(ids))]
        d[b] = np.nanmean([metrics_from_evidence(e, truth_ids=r)[metric] for e in evs])
    return point, float(np.nanpercentile(d, 2.5)), float(np.nanpercentile(d, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    ap.add_argument("--window", default="primary")
    ap.add_argument("--n-boot", type=int, default=1000)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables" / "r14_scope_sensitivity.csv")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        a.seeds, a.n_boot = a.seeds[:2], 50
    pdir = load_paths()["processed_dir"]
    W = load_windows()[a.window]
    gt = pd.read_parquet(pdir / "amlworld_ring_ground_truth.parquet")

    rows = []
    for policy in POLICIES:
        truth, patterns = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                            policy, verbose=False)
        stack_ids = [t for t in truth if patterns.get(t) == "STACK"]
        sizes = [len(v) for v in truth.values()]
        print(f"\n== {policy}: {len(truth)} rings in scope | median members {int(np.median(sizes))} | "
              f">=3 members {sum(1 for s in sizes if s >= 3)} | STACK {len(stack_ids)}")
        se_cache = {}
        for (det, meth), (root, sdir, mid) in RUNS.items():
            seeds = [s for s in a.seeds if (root / f"seed{s}" / "rings.parquet").exists()]
            if not seeds:
                continue
            evs = []
            for s in seeds:
                if (mid, s) not in se_cache:
                    se_cache[(mid, s)] = build_scored_edges(sdir / f"scores_test_seed{s}.parquet", "test",
                                                            model_id=mid, seed=s, processed_dir=pdir)
                se = se_cache[(mid, s)]
                mask = seed_mask_for_pct(se[SELECT_COL].to_numpy(float), 0.1)
                evs.append(ring_evidence(read_rings_any(root / f"seed{s}" / "rings.parquet"), se, truth, W,
                                         method=f"{det}/{meth}", seed=s, seed_mask=mask,
                                         patterns=patterns, causal=True, truth_edges=gt))
            ids = list(truth)
            f1, f1lo, f1hi = boot(evs, ids, "ring_f1", a.n_boot, 0)
            r, rlo, rhi = boot(evs, ids, "ring_recall", a.n_boot, 0)
            m = [metrics_from_evidence(e) for e in evs]
            st = [metrics_from_evidence(e, truth_ids=stack_ids) for e in evs] if stack_ids else []
            rows.append({
                "policy": policy, "detector": det, "method": meth, "n_seeds": len(seeds),
                "n_truth_rings": len(truth), "median_members": int(np.median(sizes)),
                "ring_precision": float(np.mean([x["ring_precision"] for x in m])),
                "ring_recall": r, "ring_recall_lo": rlo, "ring_recall_hi": rhi,
                "ring_f1": f1, "ring_f1_lo": f1lo, "ring_f1_hi": f1hi,
                "ring_recall_ge3": float(np.nanmean([x["ring_recall_ge3"] for x in m])),
                "member_coverage": float(np.mean([x["member_coverage"] for x in m])),
                "stack_recall": float(np.mean([x["ring_recall"] for x in st])) if st else np.nan,
                "stack_n_rings": len(stack_ids)})
            print(f"   {det:12s} {meth:9s} F1 {f1:.4f} [{f1lo:.4f}, {f1hi:.4f}] | R {r:.4f} | "
                  f"R>=3 {rows[-1]['ring_recall_ge3']:.4f} | cov {rows[-1]['member_coverage']:.4f} | "
                  f"STACK {rows[-1]['stack_recall']:.4f}", flush=True)

    d = pd.DataFrame(rows)
    piv = d.pivot_table(index=["detector", "method"], columns="policy", values="ring_f1")
    if set(POLICIES) <= set(piv.columns):
        piv["gap"] = piv["full_membership"] - piv["test_visible"]
        print("\n== the convention's effect (ring-F1: full_membership - test_visible) ==")
        print(piv.round(4).to_string())
    if a.dry_run:
        print("\n[scope] DRY RUN -- nothing written")
        return d
    a.out.parent.mkdir(parents=True, exist_ok=True)
    d.to_csv(a.out, index=False)
    Path(str(a.out).replace(".csv", ".json")).write_text(json.dumps(
        {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
         "step": "14 item 4 (scope sensitivity)", "window": a.window, "seeds": a.seeds,
         "policies": {"test_visible": "DEFAULT and reported; member set = accounts of the ring's "
                                      "in-window transactions only",
                      "full_membership": "SENSITIVITY ONLY, never a headline; member set = all of the "
                                         "ring's accounts across the dataset"},
         "reading": "the gap between the two rows is the size of the scope convention's effect; it is "
                    "not a result about any method",
         "no_model_rerun": True, "no_parameter_rechosen": True,
         "rows": json.loads(d.to_json(orient="records"))}, indent=2), encoding="utf-8")
    print(f"\n-> {a.out}")
    return d


if __name__ == "__main__":
    main()
