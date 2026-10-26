import torch
from torch_geometric.data import Data, TemporalData
import pandas as pd

def build_amlworld_graph(trans_csv="data/raw/amlworld/HI-Small_Trans.csv"):
    # ---- 1. Load raw transactions ----
    df = pd.read_csv(trans_csv)

    # ---- 2. Build a composite node key: bank + account (see Section 0 decision) ----
    df["src_node"] = df["From Bank"].astype(str) + "_" + df["Account"].astype(str)
    df["dst_node"] = df["To Bank"].astype(str) + "_" + df["Account.1"].astype(str)

    # ---- 3. Assign every unique account a contiguous integer index ----
    all_nodes = pd.unique(pd.concat([df["src_node"], df["dst_node"]]))
    node_to_idx = {n: i for i, n in enumerate(all_nodes)}
    num_nodes = len(all_nodes)

    src_idx = df["src_node"].map(node_to_idx).values
    dst_idx = df["dst_node"].map(node_to_idx).values

    # ---- 4. Parse timestamps into integer Unix epoch seconds (required for
    #         temporal ordering — TGN and any time-based split downstream needs
    #         a sortable numeric time, not a string) ----
    timestamps = pd.to_datetime(df["Timestamp"])
    t = torch.tensor(timestamps.astype("int64").values // 10**9, dtype=torch.long)  # ns -> s

    # ---- 5. Encode Payment Format as an integer category (simple label encoding —
    #         fine for now since it's a small fixed vocabulary; revisit if Phase 5+
    #         modeling wants a learned embedding instead) ----
    payment_format_codes, payment_format_categories = pd.factorize(df["Payment Format"])

    # ---- 6. Build the edge feature ("message") tensor — deliberately EXCLUDES
    #         Is Laundering, since that is the prediction target, not an input feature ----
    amount = torch.tensor(df["Amount Paid"].values, dtype=torch.float).unsqueeze(1)
    payment_format = torch.tensor(payment_format_codes, dtype=torch.float).unsqueeze(1)
    msg = torch.cat([amount, payment_format], dim=1)   # shape [num_edges, 2] — extend later if needed

    # ---- 7. The label, kept SEPARATE from msg ----
    is_laundering = torch.tensor(df["Is Laundering"].values, dtype=torch.long)

    # ---- 8. Sort everything by timestamp — TemporalData and any TGN-style model
    #         assumes events arrive in chronological order ----
    order = torch.argsort(t)
    src_idx_t = torch.tensor(src_idx, dtype=torch.long)[order]
    dst_idx_t = torch.tensor(dst_idx, dtype=torch.long)[order]
    t_sorted = t[order]
    msg_sorted = msg[order]
    label_sorted = is_laundering[order]

    temporal_data = TemporalData(src=src_idx_t, dst=dst_idx_t, t=t_sorted, msg=msg_sorted)
    temporal_data.y = label_sorted   # not a standard TemporalData field, but convenient to carry along

    # ---- 9. Also save a static Data object (all edges, no time ordering) for anything
    #         that wants a plain graph view (e.g. the motif feature extractor, Section 3) ----
    static_edge_index = torch.stack([torch.tensor(src_idx, dtype=torch.long),
                                       torch.tensor(dst_idx, dtype=torch.long)])
    static_data = Data(edge_index=static_edge_index, num_nodes=num_nodes)
    static_data.edge_amount = amount.squeeze(1)
    static_data.edge_is_laundering = is_laundering

    return temporal_data, static_data, node_to_idx, payment_format_categories

if __name__ == "__main__":
    temporal_data, static_data, node_to_idx, payment_format_categories = build_amlworld_graph()

    torch.save(temporal_data, "data/processed/amlworld_temporal_data.pt")
    torch.save(static_data, "data/processed/amlworld_static_graph.pt")
    torch.save(node_to_idx, "data/processed/amlworld_node_to_idx.pt")

    print("num_nodes:", static_data.num_nodes)
    print("num_edges (transactions):", static_data.num_edges)
    print("num_laundering_edges:", static_data.edge_is_laundering.sum().item())
    print("timestamp range:", temporal_data.t.min().item(), "to", temporal_data.t.max().item())
    print("payment format categories:", list(payment_format_categories))