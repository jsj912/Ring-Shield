import os
import torch
import pandas as pd
import networkx as nx
from pyvis.network import Network

# ---- 1. Load the structural graph (fast — no attributes, just connectivity) ----
static_data = torch.load("data/processed/amlworld_static_graph.pt", weights_only=False)
node_to_idx = torch.load("data/processed/amlworld_node_to_idx.pt", weights_only=False)
idx_to_node = {v: k for k, v in node_to_idx.items()}

G_struct = nx.DiGraph()
G_struct.add_edges_from(static_data.edge_index.t().tolist())

# ---- 2. Load raw transactions — needed for the rich columns (amount, currency,
#         payment format, timestamp) that the saved static graph doesn't carry ----
df = pd.read_csv("data/raw/amlworld/HI-Small_Trans.csv")
df["src_node"] = df["From Bank"].astype(str) + "_" + df["Account"].astype(str)
df["dst_node"] = df["To Bank"].astype(str) + "_" + df["Account.1"].astype(str)
df["src_idx"] = df["src_node"].map(node_to_idx)
df["dst_idx"] = df["dst_node"].map(node_to_idx)

# ---- 3. Find the accounts most frequently involved in KNOWN laundering
#         transactions — this is our "interesting" starting point, the AMLworld
#         equivalent of the illicit nodes we searched for in Elliptic ----
laundering_df = df[df["Is Laundering"] == 1]
print(f"Laundering transactions: {len(laundering_df)}")

account_counts = pd.concat([laundering_df["src_idx"], laundering_df["dst_idx"]]).value_counts()
top_accounts = account_counts.head(6).index.tolist()
print("Top laundering-involved accounts (node idx):", top_accounts)
print(account_counts.head(6))

# ---- 4. Build a combined 2-hop neighborhood around these accounts, STRUCTURE ONLY
#         (fast — this is just graph traversal, no attribute lookups yet) ----
combined_nodes = set()
for acc in top_accounts:
    if acc in G_struct:
        combined_nodes.update(nx.ego_graph(G_struct, acc, radius=2).nodes())
print(f"Combined subgraph node count: {len(combined_nodes)}")

# ---- 5. NOW filter the full 5M-row transaction table down to just the rows
#         inside this subgraph — this recovers full per-transaction detail
#         without ever building a 5-million-edge attributed graph in memory ----
sub_df = df[df["src_idx"].isin(combined_nodes) & df["dst_idx"].isin(combined_nodes)]
print(f"Transactions within subgraph: {len(sub_df)}")

# cap for readability — pyvis becomes unreadable past a few hundred edges;
# ALWAYS keep every laundering edge, only sample down the normal ones
MAX_EDGES = 300
if len(sub_df) > MAX_EDGES:
    laundering_sub = sub_df[sub_df["Is Laundering"] == 1]
    other_sub = sub_df[sub_df["Is Laundering"] == 0].sample(
        n=max(MAX_EDGES - len(laundering_sub), 0), random_state=42
    )
    sub_df = pd.concat([laundering_sub, other_sub])
    print(f"Capped to {len(sub_df)} edges for readability (all {len(laundering_sub)} laundering edges kept)")

# ---- 6. Build the rich, attributed, TWO-NODE-TYPE graph for rendering ----
net = Network(height="900px", width="100%", directed=True, notebook=False, bgcolor="#ffffff")
net.barnes_hut()

account_nodes = set(sub_df["src_idx"]).union(sub_df["dst_idx"])
bank_nodes = set()

for n in account_nodes:
    account_key = idx_to_node.get(n, "unknown")
    bank_id = account_key.split("_")[0]
    is_hot = n in top_accounts
    net.add_node(
        f"acct_{n}", label=account_key, shape="dot",
        color="black" if is_hot else "steelblue",
        size=25 if is_hot else 12,
        title=f"Account node\nComposite key: {account_key}\nBank: {bank_id}"
             + ("\n[Frequently laundering-involved]" if is_hot else ""),
    )
    bank_nodes.add(bank_id)

# ---- Bank nodes — second entity type, so this is genuinely heterogeneous
#      (2 node types), even though it's smaller than RingShield's full
#      5-7 type design (this dataset only populates Account and Bank) ----
for b in bank_nodes:
    net.add_node(f"bank_{b}", label=f"Bank {b}", shape="triangle", color="orange", size=18,
                 title=f"Bank node\nBank ID: {b}")

for n in account_nodes:
    account_key = idx_to_node.get(n, "unknown")
    bank_id = account_key.split("_")[0]
    net.add_edge(f"acct_{n}", f"bank_{bank_id}", color="#eeeeee", width=1,
                 title="belongs_to", arrows="")

# ---- Transaction edges, with the full column set in the tooltip ----
for _, row in sub_df.iterrows():
    is_laundering = row["Is Laundering"] == 1
    tooltip = (
        f"Timestamp: {row['Timestamp']}\n"
        f"Amount Paid: {row['Amount Paid']:.2f} {row['Payment Currency']}\n"
        f"Amount Received: {row['Amount Received']:.2f} {row['Receiving Currency']}\n"
        f"Payment Format: {row['Payment Format']}\n"
        f"Is Laundering: {'YES' if is_laundering else 'No'}"
    )
    net.add_edge(
        f"acct_{int(row['src_idx'])}", f"acct_{int(row['dst_idx'])}",
        color="red" if is_laundering else "#cccccc",
        width=3 if is_laundering else 1,
        title=tooltip,
    )

os.makedirs("results/figures", exist_ok=True)
out_path = "results/figures/amlworld_laundering_subgraph_interactive.html"
net.write_html(out_path)
print("saved:", out_path)