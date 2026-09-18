"""Unsupervised density detector (Step 4.4, model_id 'density') -- a GARG-AML-style density proxy.

    python models/density_detector.py --out-dir experiments/R2_b0/density_scores
    python models/density_detector.py --out-dir experiments/R2_b0/density_scores --dry-run

No labels anywhere. For an edge e = (u -> v) at time t the six raw signals are

    1. sender_out_count_24h   # transactions u SENT in [t - 24 h, t)
    2. sender_out_sum_24h     sum of 'Amount Sent' of those
    3. receiver_in_count_24h  # transactions v RECEIVED in [t - 24 h, t)
    4. receiver_in_sum_24h    sum of 'Amount Received' of those
    5. scatter_gather         GFP column (2-hop u -> w -> v paths before t)
    6. temporal_cycle         GFP column (trailing closes_cycle, Step 3b-z)

all trailing (edges strictly before t; the window counts are computed by bisect on per-account
timestamp-sorted arrays in the same layout as graph/motif_features.py's adjacency, built once
from train + val + test edges -- a transaction at t never reads an edge at or after t).
Each signal is z-scored with mean / std fit on the TRAIN period only, clipped at 0 from below
(only unusually HIGH activity counts as density), averaged, and the mean is rank-normalised to
[0, 1] within the split (average ranks, so exact ties stay exact ties -- the strict quantile cut
in ringshield/aggregators/cc.py excludes a boundary plateau). The detector is deterministic:
one 'seed'. Five identical scores_<split>_seed{1..5}.parquet files are written so the ring
pipeline is uniform; config.yaml says so.

Rationale (GARG-AML, Deprez et al. 2024, "Network analytics for anti-money laundering -- a
systematic literature review and experimental evaluation", ring-density features): laundering
rings are short bursts of unusually dense flow through a few accounts; local 24-hour in/out
density plus the two motif counts is the label-free reading of that.
"""
from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from contract.make_scored_edges import load_paths  # noqa: E402

WINDOW_S = 86_400
SIGNALS = ["sender_out_count_24h", "sender_out_sum_24h", "receiver_in_count_24h", "receiver_in_sum_24h",
           "scatter_gather", "temporal_cycle"]
KEY_SHIFT = 1 << 22  # timestamps < 2^22 (max 1,527,490 < 4,194,304); composite key = node * KEY_SHIFT + ts


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except Exception:  # pragma: no cover
        return "unknown"


class WindowIndex:
    """Per-account timestamp-sorted arrays (one side: out-edges keyed by sender, or in-edges keyed by
    receiver) with a cumulative amount, queried as count / sum over [t - w, t) by bisect."""

    def __init__(self, node: np.ndarray, ts: np.ndarray, amount: np.ndarray):
        order = np.lexsort((ts, node))
        self.key = node[order].astype(np.int64) * KEY_SHIFT + ts[order].astype(np.int64)
        self.cum = np.concatenate([[0.0], np.cumsum(amount[order].astype(np.float64))])
        assert np.all(np.diff(self.key) >= 0)

    def query(self, node: np.ndarray, t: np.ndarray, w: int = WINDOW_S):
        base = node.astype(np.int64) * KEY_SHIFT
        lo = np.searchsorted(self.key, base + np.maximum(t.astype(np.int64) - w, 0), side="left")
        hi = np.searchsorted(self.key, base + t.astype(np.int64), side="left")   # strictly before t
        return (hi - lo).astype(np.float64), self.cum[hi] - self.cum[lo]


def raw_signals(df: pd.DataFrame, out_idx: WindowIndex, in_idx: WindowIndex, gfp: pd.DataFrame) -> pd.DataFrame:
    u, v, t = (df[c].to_numpy(np.int64) for c in ("from_id", "to_id", "Timestamp"))
    c_out, s_out = out_idx.query(u, t)
    c_in, s_in = in_idx.query(v, t)
    g = gfp.set_index("EdgeID").reindex(df["EdgeID"].to_numpy())
    assert not g[["scatter_gather", "temporal_cycle"]].isna().any().any(), "GFP rows missing for some EdgeIDs"
    return pd.DataFrame({"sender_out_count_24h": c_out, "sender_out_sum_24h": s_out,
                         "receiver_in_count_24h": c_in, "receiver_in_sum_24h": s_in,
                         "scatter_gather": g["scatter_gather"].to_numpy(np.float64),
                         "temporal_cycle": g["temporal_cycle"].to_numpy(np.float64)})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "experiments" / "R2_b0" / "density_scores")
    ap.add_argument("--seeds", "--seed", dest="seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5],
                    help="file copies only; the detector is deterministic")
    ap.add_argument("--window-hours", type=float, default=24.0)
    ap.add_argument("--dry-run", action="store_true", help="score a 1%% sample of val / test (stats still fit on all of train)")
    args = ap.parse_args(argv)
    data_dir = args.data_dir or load_paths()["processed_dir"]
    w = int(round(args.window_hours * 3600))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Amount Sent", "Amount Received"]
    splits = {s: pd.read_parquet(data_dir / f"amlworld_{s}.parquet", columns=cols) for s in ("train", "val", "test")}
    gfp = {s: pd.read_parquet(data_dir / f"amlworld_gfp_features_{s}.parquet", columns=["EdgeID", "scatter_gather", "temporal_cycle"])
           for s in splits}
    all_e = pd.concat(splits.values(), ignore_index=True)
    out_idx = WindowIndex(all_e["from_id"].to_numpy(), all_e["Timestamp"].to_numpy(), all_e["Amount Sent"].to_numpy())
    in_idx = WindowIndex(all_e["to_id"].to_numpy(), all_e["Timestamp"].to_numpy(), all_e["Amount Received"].to_numpy())
    print(f"[density] indices over {len(all_e):,} edges in {time.time() - t0:.0f}s")

    # 1. z-score statistics on the TRAIN period only
    raw_train = raw_signals(splits["train"], out_idx, in_idx, gfp["train"])
    mu, sd = raw_train.mean(), raw_train.std(ddof=0).replace(0, 1.0)
    stats = {c: {"mean": float(mu[c]), "std": float(sd[c])} for c in SIGNALS}

    per_split = {}
    for split in ("train", "val", "test"):
        df = splits[split]
        if args.dry_run and split != "train":
            df = df.sample(frac=0.01, random_state=args.seeds[0]).sort_values("EdgeID").reset_index(drop=True)
        raw = raw_train if (split == "train" and not args.dry_run) else raw_signals(df, out_idx, in_idx, gfp[split])
        z = (raw - mu) / sd
        mean_clipped = z.clip(lower=0).mean(axis=1).to_numpy()
        score = rankdata(mean_clipped, method="average") / len(mean_clipped)      # (0, 1], ties stay ties
        n_zero = int((mean_clipped == 0).sum())
        per_split[split] = {"n_edges": int(len(df)), "n_all_six_below_train_mean": n_zero,
                            "share_all_six_below_train_mean": float(n_zero / len(df)),
                            "score_min": float(score.min()), "n_unique_scores": int(len(np.unique(score))),
                            "raw_means": {c: float(raw[c].mean()) for c in SIGNALS},
                            "z_clipped_share_positive": {c: float((z[c] > 0).mean()) for c in SIGNALS}}
        if split == "train":
            continue
        out = pd.DataFrame({"edge_id": df["EdgeID"].to_numpy(np.int64), "timestamp": df["Timestamp"].to_numpy(np.int64),
                            "score_raw": score.astype(np.float64)}).sort_values("edge_id").reset_index(drop=True)
        for seed in args.seeds:
            out.to_parquet(args.out_dir / f"scores_{split}_seed{seed}{'_dryrun' if args.dry_run else ''}.parquet", index=False)
        print(f"[density] {split}: {len(out):,} edges scored; {n_zero:,} ({100 * n_zero / len(df):.1f}%) sit on the "
              f"score-zero plateau; {per_split[split]['n_unique_scores']:,} distinct rank scores")

    config = {
        "experiment": args.out_dir.name, "model_id": "density", "step": "4.4 (R2 unsupervised density detector)",
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "git_commit": _git_commit(),
        "labels_used": False, "deterministic": True,
        "seeds": [int(s) for s in args.seeds],
        "seeds_note": "the detector has no randomness; the five scores_<split>_seed<S>.parquet files are byte-identical "
                      "copies written so ringshield/run_rings.py and evaluation/aggregate_results.py treat it like the "
                      "other detectors (mean over 'seeds' = the single value, std = 0)",
        "signals": SIGNALS, "window_s": w,
        "definition": "z-score each signal with train-period mean/std, clip at 0 from below, average the six, "
                      "rank-normalise within the split (average ranks -> exact ties kept); score in (0, 1]",
        "trailing": "window counts use edges strictly before t via bisect on per-account sorted arrays "
                    "(same layout as graph/motif_features.py); scatter_gather and temporal_cycle are the trailing "
                    "Step 3b-z GFP columns",
        "train_stats": stats, "per_split": per_split, "feature_set": "trailing_closescycle",
        "reference": "GARG-AML style ring-density proxy (Deprez et al. 2024, network analytics for AML)",
        "dry_run": bool(args.dry_run), "seconds": round(time.time() - t0, 1),
    }
    (args.out_dir / "config.yaml").write_text(yaml.dump(config, sort_keys=False), encoding="utf-8")
    (args.out_dir / "metrics.json").write_text(json.dumps({"per_split": per_split, "train_stats": stats,
                                                           "note": "unsupervised; edge / ring metrics come from "
                                                                   "evaluation/edge_metrics.py and ringshield/run_rings.py"},
                                                          indent=2), encoding="utf-8")
    env = [f"python: {sys.version}", f"platform: {platform.platform()}", f"git_commit: {_git_commit()}"]
    try:
        env.append("\n# pip freeze\n" + subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    except Exception:  # pragma: no cover
        pass
    (args.out_dir / "environment.txt").write_text("\n".join(env), encoding="utf-8")
    print(f"[density] -> {args.out_dir} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
