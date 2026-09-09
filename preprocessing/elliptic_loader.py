"""
Elliptic dataset loader — time-based 70:30 split (RingShield Phase 1-4).

Usage:
    python elliptic_loader.py --raw-dir data/raw --out-dir data/processed --feature-set AF

Expects these files inside --raw-dir (standard Kaggle Elliptic Data Set release):
    elliptic_txs_features.csv   (no header: txId, time_step, feat_1 ... feat_165)
    elliptic_txs_classes.csv     (header: txId, class)   class in {'1','2','unknown'}
    elliptic_txs_edgelist.csv    (header: txId1, txId2)

Produces inside --out-dir:
    elliptic_train.parquet
    elliptic_test.parquet
    edges_train.parquet
    edges_test.parquet

And writes data/SPLIT_MANIFEST.md documenting the split.
"""

import argparse
import datetime
from pathlib import Path

import pandas as pd

TRAIN_CUTOFF = 34  # time_step <= 34 -> train
TEST_START = 35    # time_step >= 35 -> test

# Column layout of Elliptic's txs_features.csv (no header in the raw file)
# col 0 = txId, col 1 = time_step, col 2.. = 165 feature columns
# First 93 features (cols 2-94) = "local" features (LF)
# Remaining 72 features (cols 95-166) = one-hop aggregated neighbor features
N_LOCAL_FEATURES = 93


def load_raw(raw_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    feat_path = raw_dir / "elliptic_txs_features.csv"
    class_path = raw_dir / "elliptic_txs_classes.csv"
    edge_path = raw_dir / "elliptic_txs_edgelist.csv"

    n_feature_cols = 1 + 1 + (N_LOCAL_FEATURES) + (165 - N_LOCAL_FEATURES)
    col_names = ["txId", "time_step"] + [f"feat_{i}" for i in range(1, 166)]

    features = pd.read_csv(feat_path, header=None, names=col_names)
    classes = pd.read_csv(class_path)
    edges = pd.read_csv(edge_path)

    return features, classes, edges


def merge_features_classes(features: pd.DataFrame, classes: pd.DataFrame) -> pd.DataFrame:
    df = features.merge(classes, on="txId", how="left")
    # Normalize class labels: '1' -> illicit (1), '2' -> licit (0), 'unknown' -> -1
    df["label"] = df["class"].map({"1": 1, "2": 0, "unknown": -1, 1: 1, 2: 0})
    df = df.drop(columns=["class"])
    return df


def select_feature_columns(feature_set: str) -> list[str]:
    if feature_set.upper() == "LF":
        return [f"feat_{i}" for i in range(1, N_LOCAL_FEATURES + 1)]
    elif feature_set.upper() == "AF":
        return [f"feat_{i}" for i in range(1, 166)]
    else:
        raise ValueError("feature_set must be 'LF' or 'AF'")


def time_based_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    train = df[df["time_step"] <= TRAIN_CUTOFF].copy()
    test = df[df["time_step"] >= TEST_START].copy()
    return train, test


def filter_edges_within_split(edges: pd.DataFrame, node_ids: set) -> pd.DataFrame:
    mask = edges["txId1"].isin(node_ids) & edges["txId2"].isin(node_ids)
    return edges[mask].copy()


def write_manifest(
    out_manifest_path: Path,
    feature_set: str,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    train_edges: pd.DataFrame,
    test_edges: pd.DataFrame,
):
    n_train = len(train_df)
    n_test = len(test_df)
    n_train_illicit = int((train_df["label"] == 1).sum())
    n_train_licit = int((train_df["label"] == 0).sum())
    n_train_unknown = int((train_df["label"] == -1).sum())
    n_test_illicit = int((test_df["label"] == 1).sum())
    n_test_licit = int((test_df["label"] == 0).sum())
    n_test_unknown = int((test_df["label"] == -1).sum())

    content = f"""# Elliptic Split Manifest

Generated: {datetime.datetime.now().isoformat(timespec="seconds")}

## Split rule
Time-based split on `time_step` (NOT random — avoids future-leakage into training).

- Train: time_step 1 - {TRAIN_CUTOFF}
- Test:  time_step {TEST_START} - 49

## Feature set
**{feature_set.upper()}** ({"93 local features" if feature_set.upper() == "LF" else "165 features (93 local + 72 one-hop aggregated)"})

## Node counts

| Split | Total nodes | Illicit (1) | Licit (0) | Unknown (-1) |
|-------|-------------|-------------|-----------|--------------|
| Train | {n_train} | {n_train_illicit} | {n_train_licit} | {n_train_unknown} |
| Test  | {n_test} | {n_test_illicit} | {n_test_licit} | {n_test_unknown} |

## Edge counts (cross-split edges dropped)

| Split | Edges kept |
|-------|-----------|
| Train | {len(train_edges)} |
| Test  | {len(test_edges)} |

## Notes
- Illicit-class F1 (label == 1) is the headline metric, per Weber et al.
- "Unknown" labeled nodes are typically excluded from supervised train/eval loss
  but may still be used as graph structure (their features/edges still count).
- This split must be reused unchanged for every baseline (E1-E4) for a fair comparison.
"""
    out_manifest_path.write_text(content, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--out-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--feature-set", choices=["LF", "AF"], default="AF")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading raw files...")
    features, classes, edges = load_raw(args.raw_dir)

    print("Merging features + classes...")
    merged = merge_features_classes(features, classes)

    feature_cols = select_feature_columns(args.feature_set)
    keep_cols = ["txId", "time_step", "label"] + feature_cols
    merged = merged[keep_cols]

    print("Applying time-based 70:30 split (cutoff at timestep 34/35)...")
    train_df, test_df = time_based_split(merged)

    print("Filtering edge list to same-split edges only...")
    train_ids = set(train_df["txId"])
    test_ids = set(test_df["txId"])
    train_edges = filter_edges_within_split(edges, train_ids)
    test_edges = filter_edges_within_split(edges, test_ids)

    print("Saving parquet files...")
    train_df.to_parquet(args.out_dir / "elliptic_train.parquet", index=False)
    test_df.to_parquet(args.out_dir / "elliptic_test.parquet", index=False)
    train_edges.to_parquet(args.out_dir / "edges_train.parquet", index=False)
    test_edges.to_parquet(args.out_dir / "edges_test.parquet", index=False)

    manifest_path = Path("data/SPLIT_MANIFEST.md")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_manifest(manifest_path, args.feature_set, train_df, test_df, train_edges, test_edges)

    print(f"""
Done.
  Train nodes: {len(train_df)}  |  Test nodes: {len(test_df)}
  Train edges: {len(train_edges)}  |  Test edges: {len(test_edges)}
  Feature set: {args.feature_set}
  Manifest written to: {manifest_path}
""")


if __name__ == "__main__":
    main()