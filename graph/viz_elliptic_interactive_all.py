import os
import torch
import networkx as nx
from pyvis.network import Network

data = torch.load("data/processed/elliptic_graph.pt", weights_only=False)

G_full = nx.DiGraph()
G_full.add_edges_from(data.edge_index.t().tolist())

illicit_nodes = (data.y == 1).nonzero(as_tuple=True)[0].tolist()
print(f"Total illicit nodes: {len(illicit_nodes)}")

# ---- Scan ALL illicit nodes this time (not just 300) to find genuinely dense ones ----
sizes = []
for n in illicit_nodes:
    sizes.append((n, nx.ego_graph(G_full, n, radius=2).number_of_nodes()))
sizes.sort(key=lambda x: -x[1])

print("Top 10 illicit nodes by 2-hop neighborhood size:")
for n, s in sizes[:10]:
    print(f"  node {n}: {s} nodes")

os.makedirs("results/figures", exist_ok=True)

def render_ego(node_id, filename, radius=2):
    ego = nx.ego_graph(G_full, node_id, radius=radius)
    net = Network(height="800px", width="100%", directed=True, notebook=False, bgcolor="#ffffff")
    net.barnes_hut()
    for n in ego.nodes():
        label = data.y[n].item()
        color = "black" if n == node_id else ("red" if label == 1 else "steelblue" if label == 0 else "lightgray")
        net.add_node(n, label=str(n), color=color,
                     title=f"node {n} | label={'illicit' if label==1 else 'licit' if label==0 else 'unknown'}")
    for u, v in ego.edges():
        net.add_edge(u, v)
    net.write_html(filename)
    print(f"saved: {filename} ({ego.number_of_nodes()} nodes)")

# ---- 1. The single densest illicit node found across the full search ----
render_ego(sizes[0][0], "results/figures/elliptic_densest_illicit_ego.html")

# ---- 2. A combined view: union of the top-8 illicit nodes' 2-hop neighborhoods.
#         This is usually far more informative than any single node — it shows
#         several fraud clusters (or lack thereof) side by side in one figure. ----
top_nodes = [n for n, s in sizes[:8]]
combined = nx.DiGraph()
for n in top_nodes:
    combined = nx.compose(combined, nx.ego_graph(G_full, n, radius=2))

net = Network(height="900px", width="100%", directed=True, notebook=False, bgcolor="#ffffff")
net.barnes_hut()
for n in combined.nodes():
    label = data.y[n].item()
    color = "black" if n in top_nodes else ("red" if label == 1 else "steelblue" if label == 0 else "lightgray")
    size = 25 if n in top_nodes else 10
    net.add_node(n, label=str(n), color=color, size=size,
                 title=f"node {n} | label={'illicit' if label==1 else 'licit' if label==0 else 'unknown'}")
for u, v in combined.edges():
    net.add_edge(u, v)
net.write_html("results/figures/elliptic_top8_illicit_combined.html")
print(f"saved combined view ({combined.number_of_nodes()} nodes, {combined.number_of_edges()} edges)")