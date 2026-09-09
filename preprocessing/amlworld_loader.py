"""
AMLworld HI-Small loader — Phase 5+ (RingShield roadmap).

Reads the output of format_kaggle_files.py (formatted_transactions.csv) plus
the raw HI-Small_Patterns.txt to produce:
  - Chronological 70:30 train/test split (roadmap §11)
  - Per-transaction tabular features for E5a (LR/RF/XGBoost baselines)
  - Ring-level ground truth mapping for E7+ (ring aggregation evaluation)

Usage:
    python preprocessing/amlworld_loader.py \
        --raw-dir data/raw \
        --out-dir data/processed \
        --patterns data/raw/HI-Small_Patterns.txt

Expects inside --raw-dir:
    formatted_transactions.csv   (from format_kaggle_files.py)
    HI-Small_Trans.csv           (original Kaggle file — needed to rebuild
                                  account mapping for pattern matching)

Produces inside --out-dir:
    amlworld_train.parquet       (per-transaction features + labels, train split)
    amlworld_test.parquet        (per-transaction features + labels, test split)
    amlworld_edges_train.parquet (from_id, to_id, timestamp for train-period edges)
    amlworld_edges_test.parquet  (same, test-period)
    amlworld_ring_ground_truth.parquet  (ring_id, pattern_type, from_id, to_id,
                                         timestamp — for E7 ring-level evaluation)

Also appends AMLworld section to data/SPLIT_MANIFEST.md.
"""

import argparse
import re
import datetime
from pathlib import Path
from datetime import datetime as dt_class

import numpy as np
import pandas as pd


# ============================================================================
# 1. Pattern file parser
# ============================================================================
def parse_patterns(patterns_path: Path, account_map: dict, first_ts: float):
    """Parse HI-Small_Patterns.txt into a DataFrame of ring-labeled transactions.

    Each transaction inside a BEGIN/END block gets assigned a ring_id (sequential)
    and pattern_type (FAN-IN, FAN-OUT, CYCLE, etc.). To match these back to
    formatted_transactions.csv, we rebuild the same account_map and timestamp
    conversion that format_kaggle_files.py used.

    Returns a DataFrame with columns:
        ring_id, pattern_type, from_id, to_id, timestamp_int, amount_paid
    """
    rings = []
    ring_id = 0

    with open(patterns_path, "r", encoding="utf-8") as f:
        current_pattern = None
        for line in f:
            line = line.strip()
            if not line:
                continue

            if line.startswith("BEGIN LAUNDERING ATTEMPT"):
                # Extract pattern type: everything between "- " and ":"
                match = re.match(r"BEGIN LAUNDERING ATTEMPT - ([A-Z\-]+)", line)
                if match:
                    current_pattern = match.group(1)
                ring_id += 1
                continue

            if line.startswith("END LAUNDERING ATTEMPT"):
                current_pattern = None
                continue

            if current_pattern is None:
                continue

            # Parse transaction line
            # Format: Timestamp,FromBank,FromAccount,ToBank,ToAccount,AmtPaid,CurrPaid,AmtRecv,CurrRecv,PayFmt,IsLaund
            parts = line.split(",")
            if len(parts) < 11:
                continue

            timestamp_str = parts[0]
            from_bank = parts[1]
            from_account = parts[2]
            to_bank = parts[3]
            to_account = parts[4]
            amount_paid = float(parts[5])

            # Rebuild the same composite key format_kaggle_files.py used.
            # Pandas reads bank IDs as int when they look numeric, stripping
            # leading zeros. str(int("021174")) = "21174". We must do the same
            # normalization here so keys match the account_map.
            def normalize_id(val):
                """Match pandas str(read_csv_value) behavior: if it looks like
                an int, convert to int then back to str (strips leading zeros).
                If it has hex chars, leave as-is (pandas reads it as str)."""
                try:
                    return str(int(val))
                except ValueError:
                    return val

            from_acc_str = normalize_id(from_bank) + normalize_id(from_account)
            to_acc_str = normalize_id(to_bank) + normalize_id(to_account)

            # Look up in the account_map (built from the raw Trans CSV)
            from_id = account_map.get(from_acc_str)
            to_id = account_map.get(to_acc_str)

            # Convert timestamp using same logic as format_kaggle_files.py
            try:
                dt_obj = dt_class.strptime(timestamp_str, "%Y/%m/%d %H:%M")
                ts_int = int(dt_obj.timestamp() - first_ts)
            except ValueError:
                continue

            if from_id is not None and to_id is not None:
                rings.append({
                    "ring_id": ring_id,
                    "pattern_type": current_pattern,
                    "from_id": from_id,
                    "to_id": to_id,
                    "timestamp_int": ts_int,
                    "amount_paid": amount_paid,
                })

    df_rings = pd.DataFrame(rings)
    print(f"  Parsed {ring_id} rings, {len(df_rings)} pattern transactions")
    if len(df_rings) > 0:
        print(f"  Pattern types: {df_rings['pattern_type'].value_counts().to_dict()}")
    else:
        print("  WARNING: 0 pattern transactions matched — check account map key format")
    return df_rings


def rebuild_account_map(raw_trans_path: Path):
    """Re-read the raw HI-Small_Trans.csv and rebuild the exact account_map
    and first_ts that format_kaggle_files.py used, so pattern transactions
    can be matched to formatted_transactions.csv by (from_id, to_id, Timestamp).
    """
    print("  Rebuilding account map from raw Trans CSV (this may take a moment)...")
    raw = pd.read_csv(raw_trans_path)

    account_map = {}
    first_ts = None

    for i, row in raw.iterrows():
        dt_obj = dt_class.strptime(str(row["Timestamp"]), "%Y/%m/%d %H:%M")
        if first_ts is None:
            start_time = dt_class(dt_obj.year, dt_obj.month, dt_obj.day)
            first_ts = start_time.timestamp() - 10

        # Must match format_kaggle_files.py exactly: str(row["From Bank"]) + str(row.iloc[2])
        # pandas may read bank IDs as int (stripping leading zeros) or str depending
        # on the column dtype — str() on an int strips leading zeros, which is fine
        # as long as the pattern parser does the same normalization.
        from_acc = str(row["From Bank"]) + str(row.iloc[2])
        to_acc = str(row["To Bank"]) + str(row.iloc[4])

        if from_acc not in account_map:
            account_map[from_acc] = len(account_map)
        if to_acc not in account_map:
            account_map[to_acc] = len(account_map)

    print(f"  Account map rebuilt: {len(account_map)} unique accounts")
    return account_map, first_ts


# ============================================================================
# 2. Feature engineering (account-level, fit on train only)
# ============================================================================
def engineer_account_features(df: pd.DataFrame, train_mask: np.ndarray):
    """Compute per-account aggregate features from TRAIN-period transactions only,
    then join back to every transaction (train + test) as sender/receiver features.

    Features per account (computed from train period):
        - in_degree, out_degree, total_degree
        - in_txn_amount_mean, in_txn_amount_std, in_txn_amount_max
        - out_txn_amount_mean, out_txn_amount_std, out_txn_amount_max
        - in_volume_total, out_volume_total

    These are joined as sender_* and receiver_* columns on each transaction.
    """
    train_df = df[train_mask]

    # --- Outgoing stats (sender side) ---
    out_stats = train_df.groupby("from_id").agg(
        out_degree=("to_id", "count"),
        out_amount_mean=("Amount Sent", "mean"),
        out_amount_std=("Amount Sent", "std"),
        out_amount_max=("Amount Sent", "max"),
        out_volume_total=("Amount Sent", "sum"),
    ).fillna(0)

    # --- Incoming stats (receiver side) ---
    in_stats = train_df.groupby("to_id").agg(
        in_degree=("from_id", "count"),
        in_amount_mean=("Amount Received", "mean"),
        in_amount_std=("Amount Received", "std"),
        in_amount_max=("Amount Received", "max"),
        in_volume_total=("Amount Received", "sum"),
    ).fillna(0)

    # Join as sender features
    df = df.join(out_stats, on="from_id", rsuffix="_sender")
    df = df.rename(columns={c: f"sender_{c}" for c in out_stats.columns})

    # Join as receiver features
    df = df.join(in_stats, on="to_id", rsuffix="_receiver")
    df = df.rename(columns={c: f"receiver_{c}" for c in in_stats.columns})

    # Fill NaN for accounts unseen in train period
    for col in df.columns:
        if col.startswith("sender_") or col.startswith("receiver_"):
            df[col] = df[col].fillna(0)

    return df


def add_transaction_features(df: pd.DataFrame):
    """Add simple per-transaction temporal features (no leakage — derived
    from the transaction's own timestamp, not from future data)."""
    # Timestamp is in seconds from dataset start
    df["hour_of_day"] = (df["Timestamp"] // 3600) % 24
    df["day_of_week"] = (df["Timestamp"] // (3600 * 24)) % 7
    df["day_index"] = df["Timestamp"] // (3600 * 24)
    return df


# ============================================================================
# 3. Split + save
# ============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--patterns", type=Path, default=Path("data/raw/HI-Small_Patterns.txt"))
    parser.add_argument("--split-ratio", type=float, default=0.7,
                        help="Train fraction (chronological). Default 0.7 per roadmap.")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load formatted transactions ---
    fmt_path = args.raw_dir / "formatted_transactions.csv"
    print(f"Loading {fmt_path} ...")
    df = pd.read_csv(fmt_path)
    print(f"  {len(df)} transactions, columns: {df.columns.tolist()}")

    # --- Parse pattern ground truth ---
    print("Parsing pattern ground truth...")
    raw_trans_path = args.raw_dir / "HI-Small_Trans.csv"
    account_map, first_ts = rebuild_account_map(raw_trans_path)
    df_rings = parse_patterns(args.patterns, account_map, first_ts)

    # Match ring transactions to formatted_transactions by (from_id, to_id, Timestamp)
    ring_key = df_rings[["from_id", "to_id", "timestamp_int", "ring_id", "pattern_type"]].copy()
    ring_key = ring_key.rename(columns={"timestamp_int": "Timestamp"})
    df = df.merge(ring_key, on=["from_id", "to_id", "Timestamp"], how="left")
    df["ring_id"] = df["ring_id"].fillna(-1).astype(int)
    df["pattern_type"] = df["pattern_type"].fillna("NONE")

    n_matched = (df["ring_id"] != -1).sum()
    n_pattern_txns = len(df_rings)
    print(f"  Matched {n_matched}/{n_pattern_txns} pattern transactions to formatted data "
          f"({n_matched/n_pattern_txns*100:.1f}% match rate)")

    # --- Chronological 70:30 split ---
    print(f"Applying chronological {args.split_ratio:.0%} / {1-args.split_ratio:.0%} split...")
    sorted_ts = df["Timestamp"].sort_values()
    cutoff_idx = int(len(sorted_ts) * args.split_ratio)
    cutoff_ts = sorted_ts.iloc[cutoff_idx]

    train_mask = df["Timestamp"] < cutoff_ts
    test_mask = df["Timestamp"] >= cutoff_ts

    n_train, n_test = train_mask.sum(), test_mask.sum()
    n_train_laund = df.loc[train_mask, "Is Laundering"].sum()
    n_test_laund = df.loc[test_mask, "Is Laundering"].sum()
    print(f"  Train: {n_train} txns ({n_train_laund} laundering, "
          f"IR={n_train_laund/n_train*100:.2f}%)")
    print(f"  Test:  {n_test} txns ({n_test_laund} laundering, "
          f"IR={n_test_laund/n_test*100:.2f}%)")
    print(f"  Cutoff timestamp: {cutoff_ts}")

    # --- Feature engineering ---
    print("Engineering account-level features (fit on train only)...")
    df = add_transaction_features(df)
    df = engineer_account_features(df, train_mask.values)

    # Define feature columns for tabular baselines (E5a)
    txn_features = ["Amount Sent", "Sent Currency", "Amount Received",
                    "Received Currency", "Payment Format",
                    "hour_of_day", "day_of_week", "day_index"]
    account_features = [c for c in df.columns if c.startswith("sender_") or c.startswith("receiver_")]
    all_features = txn_features + account_features
    meta_cols = ["EdgeID", "from_id", "to_id", "Timestamp", "Is Laundering",
                 "ring_id", "pattern_type"]

    keep_cols = meta_cols + all_features
    df_out = df[keep_cols].copy()

    # --- Save ---
    print("Saving parquet files...")
    train_df = df_out[train_mask.values].reset_index(drop=True)
    test_df = df_out[test_mask.values].reset_index(drop=True)

    train_df.to_parquet(args.out_dir / "amlworld_train.parquet", index=False)
    test_df.to_parquet(args.out_dir / "amlworld_test.parquet", index=False)

    # Edge lists (for graph construction in E5b / E6)
    edge_cols = ["from_id", "to_id", "Timestamp", "Amount Received",
                 "Received Currency", "Payment Format"]
    df[edge_cols][train_mask.values].to_parquet(
        args.out_dir / "amlworld_edges_train.parquet", index=False)
    df[edge_cols][test_mask.values].to_parquet(
        args.out_dir / "amlworld_edges_test.parquet", index=False)

    # Ring ground truth (for E7+ ring-level evaluation)
    ring_gt = df_rings.copy()
    ring_gt.to_parquet(args.out_dir / "amlworld_ring_ground_truth.parquet", index=False)

    # --- Update SPLIT_MANIFEST.md ---
    manifest_path = Path("data/SPLIT_MANIFEST.md")
    n_rings_train = train_df[train_df["ring_id"] != -1]["ring_id"].nunique()
    n_rings_test = test_df[test_df["ring_id"] != -1]["ring_id"].nunique()

    amlworld_section = f"""

---

# AMLworld HI-Small Split Manifest

Generated: {datetime.datetime.now().isoformat(timespec="seconds")}

## Split rule
Chronological split at {args.split_ratio:.0%} of transactions sorted by timestamp.

- Train: Timestamp < {cutoff_ts}
- Test:  Timestamp >= {cutoff_ts}

## Transaction counts

| Split | Total txns | Laundering | Illicit ratio | Unique rings |
|-------|-----------|------------|---------------|--------------|
| Train | {n_train} | {n_train_laund} | {n_train_laund/n_train*100:.2f}% | {n_rings_train} |
| Test  | {n_test} | {n_test_laund} | {n_test_laund/n_test*100:.2f}% | {n_rings_test} |

## Feature set
Transaction-level: {', '.join(txn_features)}
Account-level (fit on train only): {', '.join(account_features)}
Total feature dim: {len(all_features)}

## Pattern types in ground truth
{df_rings['pattern_type'].value_counts().to_string()}

## Notes
- Account-level features (degree, amount stats) computed ONLY from train-period
  transactions to prevent future leakage.
- Ring ground truth saved separately in amlworld_ring_ground_truth.parquet for E7+.
- Pattern matching rate: {n_matched}/{n_pattern_txns} ({n_matched/n_pattern_txns*100:.1f}%)
"""
    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(amlworld_section)

    print(f"""
Done.
  Train txns:  {n_train}  |  Test txns:  {n_test}
  Train laund: {n_train_laund}  |  Test laund: {n_test_laund}
  Feature dim: {len(all_features)} ({len(txn_features)} txn + {len(account_features)} account)
  Rings total: {df_rings['ring_id'].nunique()} ({n_rings_train} in train, {n_rings_test} in test)
  Pattern match rate: {n_matched}/{n_pattern_txns} ({n_matched/n_pattern_txns*100:.1f}%)
  Manifest appended to: {manifest_path}
  Files written to: {args.out_dir}/
""")


if __name__ == "__main__":
    main()