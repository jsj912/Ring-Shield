import torch, pandas as pd
data = torch.load("elliptic/data/processed/elliptic_graph.pt", weights_only = False)
df = pd.read_parquet("elliptic/data/processed/elliptic_all.parquet")

# pick 3 random edges and manually verify they correspond to real txId1,txId2 pairs
idx_to_txid = dict(enumerate(df["txId"]))
for i in [0, 1000, 100000]:
    s, d = data.edge_index[0, i].item(), data.edge_index[1, i].item()
    print(f"edge {i}: node {s} (txId={idx_to_txid[s]}) -> node {d} (txId={idx_to_txid[d]})")