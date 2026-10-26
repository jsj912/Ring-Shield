import torch
from torch_geometric.data import Data
import pandas as pd
import yaml

def build_elliptic_graph(full_parquet="elliptic/data/processed/elliptic_all.parquet",
                          edgelist_csv="elliptic/data/raw/elliptic/elliptic_txs_edgelist.csv",
                          split_cfg_path="elliptic/configs/elliptic_split.yaml"):
    # ---- 1. Load the full node table (all 203,769 rows, labeled + unlabeled) ----
    df = pd.read_parquet(full_parquet)
    edges = pd.read_csv(edgelist_csv)
    split_cfg = yaml.safe_load(open(split_cfg_path))

    # ---- 2. Map each txId to a contiguous integer index (0..N-1) ----
    # PyG needs integer node indices, not the raw txId values, to build edge_index.
    txid_to_idx = {tx: i for i, tx in enumerate(df["txId"])}

    # ---- 3. Assemble node features and labels ----
    feat_cols = [c for c in df.columns if c.startswith("feat_")]
    x = torch.tensor(df[feat_cols].values, dtype=torch.float)
    y = torch.tensor(df["label"].values, dtype=torch.long)   # -1 = unknown, 0 = licit, 1 = illicit

    # ---- 4. Build edge_index from the edge list, dropping any edge referencing
    #         a txId not present in the feature table (shouldn't happen, but cheap to guard) ----
    src = edges["txId1"].map(txid_to_idx)
    dst = edges["txId2"].map(txid_to_idx)
    valid = src.notna() & dst.notna()
    n_dropped = (~valid).sum()
    if n_dropped > 0:
        print(f"WARNING: dropped {n_dropped} edges referencing unknown txIds — investigate before trusting this graph")
    edge_index = torch.tensor(
        [src[valid].astype(int).values, dst[valid].astype(int).values], dtype=torch.long
    )

    # ---- 5. Build train/test masks from the chronological split — labels only,
    #         graph structure (edge_index) is untouched by this mask ----
    time_step = torch.tensor(df["time_step"].values, dtype=torch.long)
    train_lo, train_hi = split_cfg["train_timesteps"]
    test_lo, test_hi = split_cfg["test_timesteps"]

    train_mask = (time_step >= train_lo) & (time_step <= train_hi) & (y != -1)
    test_mask = (time_step >= test_lo) & (time_step <= test_hi) & (y != -1)

    data = Data(x=x, edge_index=edge_index, y=y)
    data.train_mask = train_mask
    data.test_mask = test_mask
    data.time_step = time_step
    return data

if __name__ == "__main__":
    data = build_elliptic_graph()
    torch.save(data, "elliptic/data/processed/elliptic_graph.pt")

    print(data)
    print("num_nodes:", data.num_nodes, "(expected: 203,769)")
    print("num_edges:", data.num_edges, "(expected: 234,355)")
    print("train nodes:", data.train_mask.sum().item())
    print("test nodes:", data.test_mask.sum().item())
    print("x.shape:", data.x.shape, "| edge_index.shape:", data.edge_index.shape)