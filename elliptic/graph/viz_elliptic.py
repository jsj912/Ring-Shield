import torch
import networkx as nx
import matplotlib.pyplot as plt

data = torch.load("data/processed/elliptic_graph.pt", weights_only=False)

# ---- Option A: one timestep's subgraph ----
timestep_to_view = 1  # try a few — some timesteps are denser than others
mask = data.time_step == timestep_to_view
node_ids = mask.nonzero(as_tuple=True)[0].tolist()
node_id_set = set(node_ids)

# keep only edges where BOTH endpoints are in this timestep
edge_index = data.edge_index
edge_mask = torch.isin(edge_index[0], torch.tensor(node_ids)) & torch.isin(edge_index[1], torch.tensor(node_ids))
sub_edges = edge_index[:, edge_mask].t().tolist()

G = nx.DiGraph()
G.add_nodes_from(node_ids)
G.add_edges_from(sub_edges)

# color by label: red=illicit, blue=licit, gray=unknown
color_map = []
for n in G.nodes():
    label = data.y[n].item()
    color_map.append("red" if label == 1 else "steelblue" if label == 0 else "lightgray")

plt.figure(figsize=(12, 10))
pos = nx.spring_layout(G, seed=42, k=0.3)
nx.draw(G, pos, node_color=color_map, node_size=40, edge_color="gray", arrows=True, arrowsize=6)
plt.title(f"Elliptic subgraph — timestep {timestep_to_view} "
          f"({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")
plt.savefig("results/figures/elliptic_timestep1_subgraph.png", dpi=150, bbox_inches="tight")
print("saved")

# ---- Option B: ego-network around a specific illicit node (often more visually
#      interesting — you can actually SEE why a transaction looks suspicious) ----
illicit_nodes = (data.y == 1).nonzero(as_tuple=True)[0]
center_node = illicit_nodes[0].item()   # pick the first illicit node; try others too

G_full = nx.DiGraph()
G_full.add_edges_from(data.edge_index.t().tolist())
ego = nx.ego_graph(G_full, center_node, radius=2)  # 2 hops out from the illicit node

color_map = []
for n in ego.nodes():
    label = data.y[n].item()
    if n == center_node:
        color_map.append("black")
    else:
        color_map.append("red" if label == 1 else "steelblue" if label == 0 else "lightgray")

plt.figure(figsize=(10, 8))
pos = nx.spring_layout(ego, seed=42)
nx.draw(ego, pos, node_color=color_map, node_size=60, edge_color="gray", arrows=True)
plt.title(f"2-hop neighborhood around illicit node {center_node}")
plt.savefig("results/figures/elliptic_illicit_ego_network.png", dpi=150, bbox_inches="tight")
print("saved")