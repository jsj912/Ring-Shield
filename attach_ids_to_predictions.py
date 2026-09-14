"""
Attach EdgeID / from_id / to_id / Timestamp to a predictions CSV produced by
models/tgn.py or models/gatv2.py.

Those scripts save only [true_label, predicted_label, pred_prob], but rows are
emitted in te_inds order (test loaders use shuffle=False), so the identifiers
can be recovered by replaying the same day-based 60/20/20 split.

The label check below is the real proof of alignment: if every recovered
true label matches the saved one, row i of the predictions file is row
te_inds[i] of formatted_transactions.csv. If it fails, STOP -- do not
guess, re-run training with the fixed save block instead.

Usage:
    python attach_ids_to_predictions.py ^
        --raw-dir data/raw ^
        --pred experiments/E6_gatv2/predictions.csv ^
        --out experiments/E6_gatv2/predictions_with_ids.csv
"""

import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd


def compute_test_indices(df):
    """Replay the day-based 60/20/20 split from models/gatv2.py load_data()."""
    ts = df["Timestamp"].values - df["Timestamp"].values.min()
    n_days = int(ts.max() / 86400 + 1)

    daily_inds, daily_counts = [], []
    for day in range(n_days):
        lo, hi = day * 86400, (day + 1) * 86400
        di = np.where((ts >= lo) & (ts < hi))[0]
        daily_inds.append(di)
        daily_counts.append(len(di))

    d_ts = np.array(daily_counts)
    split_per = [0.6, 0.2, 0.2]
    best_score, best_ij = float("inf"), (0, 0)
    for i, j in itertools.combinations(range(len(d_ts)), 2):
        if j < i:
            continue
        st = [d_ts[:i].sum(), d_ts[i:j].sum(), d_ts[j:].sum()]
        total = sum(st)
        if total == 0:
            continue
        score = max(abs(v / total - t) / t for v, t in zip(st, split_per))
        if score < best_score:
            best_score, best_ij = score, (i, j)

    i, j = best_ij
    splits = [range(i), range(i, j), range(j, len(d_ts))]
    cat = [np.concatenate([daily_inds[d] for d in s]) for s in splits]
    return cat[0], cat[1], cat[2], best_ij


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    ap.add_argument("--pred", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    fmt_path = args.raw_dir / "formatted_transactions.csv"
    print(f"Loading {fmt_path} ...")
    df = pd.read_csv(fmt_path)

    tr_inds, val_inds, te_inds, (i, j) = compute_test_indices(df)
    print(f"  Split day boundaries: i={i}, j={j}")
    print(f"  Train {len(tr_inds)} | Val {len(val_inds)} | Test {len(te_inds)}")

    # Sanity: train indices must be a contiguous 0..n-1 block. The training
    # scripts index val_data.edge_index[:, val_inds] with GLOBAL indices, which
    # is only correct under this assumption.
    assert np.array_equal(tr_inds, np.arange(len(tr_inds))), (
        "tr_inds is not contiguous from 0 -- formatted_transactions.csv is "
        "probably not sorted by Timestamp. The training scripts' global-index "
        "slicing is unsafe in that case."
    )

    preds = pd.read_csv(args.pred)
    print(f"Loaded {len(preds)} predictions from {args.pred}")

    if len(preds) != len(te_inds):
        raise SystemExit(
            f"Row count mismatch: predictions={len(preds)} vs test edges="
            f"{len(te_inds)}. Alignment cannot be trusted."
        )

    recovered_labels = df["Is Laundering"].values[te_inds]
    if not np.array_equal(recovered_labels, preds["true_label"].values):
        n_bad = int((recovered_labels != preds["true_label"].values).sum())
        raise SystemExit(
            f"Label mismatch on {n_bad} rows. The predictions are NOT in "
            f"te_inds order. Re-run training with IDs saved directly."
        )

    print("  Label check passed -- alignment confirmed.")

    out = pd.DataFrame({
        "EdgeID": df["EdgeID"].values[te_inds],
        "from_id": df["from_id"].values[te_inds],
        "to_id": df["to_id"].values[te_inds],
        "Timestamp": df["Timestamp"].values[te_inds],
        "true_label": preds["true_label"].values,
        "predicted_label": preds["predicted_label"].values,
        "pred_prob": preds["pred_prob"].values,
    })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    print(f"Wrote {len(out)} rows -> {args.out}")
    print(f"  Flagged at saved threshold: {int(out['predicted_label'].sum())}")
    print(f"  True laundering: {int(out['true_label'].sum())}")


if __name__ == "__main__":
    main()
