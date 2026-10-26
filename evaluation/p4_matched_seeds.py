# -*- coding: utf-8 -*-
"""P4 - matched-seed containment test. CONTROLLED DIAGNOSTIC WITH LABEL-DERIVED SEEDS.

    RINGSHIELD_PATHS=... python evaluation/p4_matched_seeds.py --dataset HI-Medium --stage b0

**This is never a detector result.** The seed sets are built from the ground truth, exactly as
registered in `docs/V3_HIMEDIUM_PREREG.md` Amendment 4, so that both datasets receive a seed set
of *identical quality* and the only thing that differs is what the ring layer does with it. No
number produced here is comparable to anything a real detector produces, on either dataset.

Construction, identical on both releases, on each one's primary window:

  1. sample illicit edges uniformly at recall 0.28;
  2. add licit edges sampled uniformly from licit edges incident to at least one account of an
     illicit edge, until precision 0.93;
  3. 10 draws per dataset.

Then B0 (`ringshield.aggregators.cc`) with each dataset's own val-chosen `min_size`, swapping
only the seed set. Reported per draw and as a mean with a bootstrap CI over draws: ring recall,
Ring-Recall>=3 and the under-covered share.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
from contract.schema import TEST_PARQUET_RENAMES                      # noqa: E402
from evaluation.ring_metrics import evaluate_rings                    # noqa: E402
from evaluation.unmatched_rings import classify                       # noqa: E402
from preprocessing.account_bank import load_paths                     # noqa: E402
from ringshield.aggregators.cc import rings_from_masks                # noqa: E402
from ringshield.truth import load_ground_truth                        # noqa: E402
from ringshield.windows import load_windows                           # noqa: E402

RECALL, PRECISION, N_DRAWS = 0.28, 0.93, 10
COLS = ["EdgeID", "from_id", "to_id", "from_bank", "to_bank", "Timestamp", "Amount Received",
        "Is Laundering"]


def window_frame(pdir: Path, eval_window: Path, split: str = "test"):
    W = load_windows(eval_window)["primary"]
    df = pd.read_parquet(pdir / f"amlworld_{split}.parquet", columns=COLS).rename(
        columns=TEST_PARQUET_RENAMES)
    df = df.rename(columns={"Is Laundering": "is_laundering"})
    df = df[W.mask(df["timestamp"].to_numpy())].reset_index(drop=True)
    # B0 only needs the contract columns plus a score column; the seeds are given explicitly, so
    # the score is a constant -- nothing here may depend on a detector.
    df["score_raw"] = 1.0
    df["amount"] = df["amount_received"]
    truth, pat = load_ground_truth(pdir / "amlworld_ring_ground_truth.parquet", *W.bounds,
                                   "test_visible", verbose=False)
    return df, truth, pat, W


def draw_seeds(df: pd.DataFrame, rng) -> np.ndarray:
    """Boolean mask over df: 28 % of illicit edges, padded with licit edges incident to an
    illicit-edge account until precision is 0.93."""
    y = df["is_laundering"].to_numpy()
    pos = np.flatnonzero(y == 1)
    n_pos = int(round(RECALL * len(pos)))
    take_pos = rng.choice(pos, n_pos, replace=False)
    ill_accounts = set(df["from_id"].to_numpy()[pos].tolist()) | set(df["to_id"].to_numpy()[pos].tolist())
    licit = np.flatnonzero(y == 0)
    inc = licit[np.isin(df["from_id"].to_numpy()[licit], list(ill_accounts))
                | np.isin(df["to_id"].to_numpy()[licit], list(ill_accounts))]
    n_neg = int(round(n_pos * (1 - PRECISION) / PRECISION))
    assert len(inc) >= n_neg, f"licit pool {len(inc)} < needed {n_neg}"
    take_neg = rng.choice(inc, n_neg, replace=False)
    mask = np.zeros(len(df), dtype=bool)
    mask[np.concatenate([take_pos, take_neg])] = True
    return mask, n_pos, n_neg, len(pos), len(inc)


def one_draw(df, truth, pat, W, min_size, rng):
    mask, n_pos, n_neg, n_ill, pool = draw_seeds(df, rng)
    rings = rings_from_masks(df, mask, None, min_size, None, conf_col="score_raw")
    m = evaluate_rings([r.member_set for r in rings], truth, 0.5, pat)
    big = {t for t, v in truth.items() if len(v) >= 3}
    matched = {x.truth_id for x in __import__("evaluation.ring_metrics", fromlist=["match_rings"])
               .match_rings([r.member_set for r in rings], truth, 0.5)[0]}
    kl = classify(rings, df.rename(columns={"is_laundering": "y"}), truth, pat, W)
    n_truth = len(truth)
    return {"n_seeds": int(mask.sum()), "n_seed_illicit": n_pos, "n_seed_licit": n_neg,
            "seed_precision": n_pos / (n_pos + n_neg), "seed_recall": n_pos / n_ill,
            "licit_pool": pool, "n_rings": len(rings),
            "ring_precision": m.ring_precision, "ring_recall": m.ring_recall, "ring_f1": m.ring_f1,
            "ring_recall_ge3": len(matched & big) / len(big) if big else np.nan,
            "under_covered": int((kl["klass"] == "c_under_covered").sum()),
            "under_covered_share": int((kl["klass"] == "c_under_covered").sum()) / n_truth,
            "class_b": int((kl["klass"] == "b_untouched").sum()),
            "class_b_share": int((kl["klass"] == "b_untouched").sum()) / n_truth,
            "n_truth_rings": n_truth}


def boot_ci(x, n=2000, seed=0):
    x = np.asarray(x, float); r = np.random.default_rng(seed)
    d = np.array([r.choice(x, len(x), replace=True).mean() for _ in range(n)])
    return float(x.mean()), float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--eval-window", type=Path, required=True)
    ap.add_argument("--min-size", type=int, required=True, help="the dataset's VAL-CHOSEN value")
    ap.add_argument("--draws", type=int, default=N_DRAWS)
    ap.add_argument("--rng", type=int, default=20261003)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "results" / "tables")
    a = ap.parse_args(argv)
    pdir = load_paths()["processed_dir"]
    df, truth, pat, W = window_frame(pdir, a.eval_window)
    print(f"[p4] {a.dataset}: primary days {W.day_lo}-{W.day_hi}, {len(df):,} edges, "
          f"{int(df['is_laundering'].sum()):,} illicit, {len(truth)} in-scope rings, "
          f"min_size={a.min_size} (val-chosen)")
    rows = []
    for d in range(a.draws):
        rng = np.random.default_rng(a.rng + d)
        r = one_draw(df, truth, pat, W, a.min_size, rng)
        r.update({"dataset": a.dataset, "draw": d, "min_size": a.min_size})
        rows.append(r)
        print(f"  draw {d}: seeds {r['n_seeds']:,} (P {r['seed_precision']:.3f} R {r['seed_recall']:.3f}) "
              f"-> rings {r['n_rings']:,} | recall {r['ring_recall']:.4f} | R>=3 {r['ring_recall_ge3']:.4f} "
              f"| under-cov {r['under_covered_share']:.4f}", flush=True)
    g = pd.DataFrame(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    p = a.out / f"v33_p4_b0_{a.dataset}.csv"; g.to_csv(p, index=False)
    print(f"\n== {a.dataset} B0 over {a.draws} draws ==")
    for k in ("ring_recall", "ring_recall_ge3", "under_covered_share", "class_b_share", "ring_precision"):
        m, lo, hi = boot_ci(g[k]); print(f"  {k:22s} {m:.4f}  [{lo:.4f}, {hi:.4f}]")
    print(f"-> {p}")
    return g


if __name__ == "__main__":
    main()
