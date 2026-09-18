"""Step 3b-x (2): how tightly are ring transactions clustered in time?

    python preprocessing/ring_time_spread.py                # -> docs/ring_time_spread.json

For every pair of transactions in the same ring (data/processed/amlworld_ring_ground_truth.parquet,
all 370 rings, every split) take |t_i - t_j| and report, overall and per pattern type, the
fraction of pairs under 300 s, 1,800 s, 1 h, 6 h and 24 h, plus the median / p90 gap and
the per-ring span (max - min). Rings with a single transaction contribute no pairs and are
counted separately. This is the ground-truth side of the residual-leak question: if most
same-ring pairs are closer than the causal window W, in-window future neighbours can carry
ring signal.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

GT_PATH = REPO_ROOT / "data" / "processed" / "amlworld_ring_ground_truth.parquet"
OUT_PATH = REPO_ROOT / "docs" / "ring_time_spread.json"
BINS_S = {"300s": 300, "1800s": 1800, "1h": 3600, "6h": 21600, "24h": 86400}


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


def pair_gaps(ts: np.ndarray) -> np.ndarray:
    """|t_i - t_j| over all unordered pairs of a ring."""
    ts = np.sort(ts.astype(np.int64))
    i, j = np.triu_indices(len(ts), k=1)
    return ts[j] - ts[i]


def summarise(gaps: np.ndarray, spans: np.ndarray, n_rings: int, n_single: int) -> dict:
    out = {"n_rings": int(n_rings), "n_rings_single_txn": int(n_single), "n_pairs": int(len(gaps))}
    if len(gaps):
        out["frac_pairs_under"] = {k: float((gaps < v).mean()) for k, v in BINS_S.items()}
        out["gap_s"] = {"median": float(np.median(gaps)), "p90": float(np.percentile(gaps, 90)),
                        "max": float(gaps.max())}
    else:
        out["frac_pairs_under"] = {k: None for k in BINS_S}
        out["gap_s"] = None
    if len(spans):
        out["ring_span_s"] = {"median": float(np.median(spans)), "p90": float(np.percentile(spans, 90)),
                              "max": float(spans.max()),
                              "frac_rings_under": {k: float((spans < v).mean()) for k, v in BINS_S.items()}}
    return out


def compute(gt: pd.DataFrame) -> dict:
    per_pattern: dict[str, dict] = {}
    all_gaps, all_spans = [], []
    n_single_all = 0
    for pat, g in gt.groupby("pattern_type"):
        gaps, spans, n_single = [], [], 0
        for _, r in g.groupby("ring_id"):
            ts = r["timestamp_int"].to_numpy()
            if len(ts) < 2:
                n_single += 1
                continue
            gaps.append(pair_gaps(ts))
            spans.append(int(ts.max() - ts.min()))
        gaps = np.concatenate(gaps) if gaps else np.array([], dtype=np.int64)
        spans = np.array(spans, dtype=np.int64)
        per_pattern[pat] = summarise(gaps, spans, g["ring_id"].nunique(), n_single)
        all_gaps.append(gaps)
        all_spans.append(spans)
        n_single_all += n_single
    gaps = np.concatenate(all_gaps)
    spans = np.concatenate(all_spans)
    return {"all_patterns": summarise(gaps, spans, gt["ring_id"].nunique(), n_single_all),
            "per_pattern": per_pattern}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ground-truth", type=Path, default=GT_PATH)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)

    gt = pd.read_parquet(args.ground_truth)
    for col in ("ring_id", "pattern_type", "timestamp_int"):
        assert col in gt.columns, f"ground truth missing {col}: {gt.columns.tolist()}"
    res = compute(gt)
    res = {
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "ground_truth": str(args.ground_truth), "n_rows": int(len(gt)),
        "definition": "for every unordered pair of transactions in the same ring, gap = |t_i - t_j| in seconds "
                      "(timestamp_int, loader basis; the basis cancels in differences). frac_pairs_under[b] = "
                      "share of pairs with gap < b. ring_span_s = max - min timestamp of a ring. Rings with one "
                      "transaction contribute no pairs.",
        "bins_s": BINS_S,
        **res,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=2), encoding="utf-8")

    a = res["all_patterns"]
    print(f"[ring_time_spread] {a['n_rings']} rings ({a['n_rings_single_txn']} single-txn), {a['n_pairs']:,} pairs")
    hdr = f"{'pattern':16s} {'rings':>5s} {'pairs':>7s} " + " ".join(f"{k:>7s}" for k in BINS_S) + \
          f" {'med gap':>9s} {'p90 gap':>9s} {'med span':>9s}"
    print(hdr)
    rows = [("ALL", a)] + sorted(res["per_pattern"].items())
    for name, r in rows:
        fr = r["frac_pairs_under"]
        cells = " ".join(f"{(fr[k] if fr[k] is not None else float('nan')):7.3f}" for k in BINS_S)
        gap = r["gap_s"] or {"median": float("nan"), "p90": float("nan")}
        span = r.get("ring_span_s", {"median": float("nan")})
        print(f"{name:16s} {r['n_rings']:5d} {r['n_pairs']:7d} {cells} {gap['median']:9.0f} {gap['p90']:9.0f} "
              f"{span['median']:9.0f}")
    print(f"-> {args.out}")
    return res


if __name__ == "__main__":
    main()
