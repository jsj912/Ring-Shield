"""How many scored cells change if the ring matcher breaks equal-Jaccard ties deterministically.

    CUDA_VISIBLE_DEVICES="" python -m evaluation.matcher_tiebreak_audit --out results/tables/matcher_tiebreak_audit.csv

For every rings.parquet under experiments/ and ../RS-e2e/experiments/ (the runs behind r9, r14, v39-v45,
the sb2048 rows and m1_primary are a subset), on the test split, for each window (primary, whole, tail),
truth convention (test_visible, full_membership, component, component_ge3) and tau (0.3, 0.5, 0.7):
predictions are restricted exactly as the scorer does (score_external.load_predictions -> restrict_rings),
and evaluation.ring_metrics.match_rings is run with tie_break="file_order" (shipped) and "deterministic".
Recorded per cell: matched count under each rule, whether the matched truth set differs, ring-F1 under each.
Read-only: nothing is rescored into any table.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from evaluation.ring_metrics import match_rings  # noqa: E402

ROOTS = [REPO_ROOT / "experiments", REPO_ROOT.parent / "RS-e2e" / "experiments"]
WINDOWS, CONVS, TAUS = ["primary", "whole", "tail"], ["test_visible", "full_membership", "component", "component_ge3"], [0.3, 0.5, 0.7]


def f1(m, n_pred, n_truth):
    p = m / n_pred if n_pred else 0.0
    r = m / n_truth if n_truth else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=0, help="first N files only (smoke test)")
    a = ap.parse_args(argv)
    from preprocessing.account_bank import load_paths
    from evaluation.score_external import build_targets, load_predictions, load_split_edges
    from ringshield.evaluate import restrict_rings
    from ringshield.windows import load_windows
    sys.stdout.reconfigure(encoding="utf-8")
    pdir = load_paths()["processed_dir"]
    Ws = load_windows()
    edges = load_split_edges("test", pdir)
    targets = {w: build_targets(pdir / "amlworld_ring_ground_truth.parquet", Ws[w])[0] for w in WINDOWS}
    files = sorted(p for r in ROOTS for p in r.rglob("rings.parquet"))
    if a.limit:
        files = files[: a.limit]
    rows, t0 = [], time.time()
    for i, f in enumerate(files):
        try:
            recs = load_predictions(f, edges, 3)[0]
        except Exception as e:  # noqa: BLE001 -- val-split or other schema; recorded, not scored
            rows.append({"file": str(f), "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        for w in WINDOWS:
            P = restrict_rings(recs, edges, Ws[w])
            for conv in CONVS:
                truth = targets[w][conv][0]
                for tau in TAUS:
                    out = {}
                    for rule in ("file_order", "deterministic"):
                        m, _, _ = match_rings(P, truth, threshold=tau, tie_break=rule)
                        out[rule] = {r.truth_id for r in m}
                    a_, b_ = len(out["file_order"]), len(out["deterministic"])
                    rows.append({"file": str(f), "window": w, "convention": conv, "tau": tau, "n_pred": len(P),
                                 "n_truth": len(truth), "matched_file_order": a_, "matched_deterministic": b_,
                                 "matched_set_differs": out["file_order"] != out["deterministic"],
                                 "ring_f1_file_order": f1(a_, len(P), len(truth)),
                                 "ring_f1_deterministic": f1(b_, len(P), len(truth))})
        print(f"[{i + 1}/{len(files)}] {time.time() - t0:.0f}s {f}", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(a.out, index=False)
    ok = df[df.get("error").isna()] if "error" in df else df
    print(f"-> {a.out}: {len(ok)} cells, count changes {int((ok.matched_file_order != ok.matched_deterministic).sum())}, "
          f"matched-set changes {int(ok.matched_set_differs.sum())}")


if __name__ == "__main__":
    main()
