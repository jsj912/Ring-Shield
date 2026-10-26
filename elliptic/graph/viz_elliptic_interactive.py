import os
import torch
import networkx as nx
from pyvis.network import Network

data = torch.load("elliptic/data/processed/elliptic_graph.pt", weights_only=False)

G_full = nx.DiGraph()
G_full.add_edges_from(data.edge_index.t().tolist())

# ---- Find a more interesting illicit node than a random pick ----
# node 907 (your last run) sat in a near-isolated chain — this searches a sample
# of illicit nodes for one with a larger, more informative 2-hop neighborhood.
illicit_nodes = (data.y == 1).nonzero(as_tuple=True)[0].tolist()

best_node, best_size = None, 0
for n in illicit_nodes[:300]:   # checking all ~4,545 is slow; 300 is enough to find a good one
    ego = nx.ego_graph(G_full, n, radius=2)
    if ego.number_of_nodes() > best_size:
        best_node, best_size = n, ego.number_of_nodes()

print(f"Best illicit node found: {best_node} ({best_size} nodes in its 2-hop neighborhood)")
ego = nx.ego_graph(G_full, best_node, radius=2)

os.chdir(os.path.dirname(os.path.abspath(__file__)))   # pyvis links the HTML to ./lib/ (elliptic/graph/lib/)

# ---- Build the interactive graph ----
net = Network(height="800px", width="100%", directed=True, notebook=False, bgcolor="#ffffff")
net.barnes_hut()   # physics engine — spreads nodes out automatically, draggable after

for n in ego.nodes():
    label = data.y[n].item()
    if n == best_node:
        color = "black"
    elif label == 1:
        color = "red"
    elif label == 0:
        color = "steelblue"
    else:
        color = "lightgray"
    net.add_node(n, label=str(n), color=color,
                 title=f"node {n} | label={'illicit' if label==1 else 'licit' if label==0 else 'unknown'}")

for u, v in ego.edges():
    net.add_edge(u, v)

out_path = "elliptic_illicit_ego_network_interactive.html"
net.write_html(out_path)
print("saved:", out_path)