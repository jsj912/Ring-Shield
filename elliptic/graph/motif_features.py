import torch
import networkx as nx
import pandas as pd

def build_motif_features(static_graph_path="elliptic/data/processed/amlworld_static_graph.pt",
                          node_to_idx_path="elliptic/data/processed/amlworld_node_to_idx.pt",
                          fan_threshold=5,
                          max_cycle_length=4):
    # ---- 1. Load the static graph and rebuild a NetworkX DiGraph from it ----
    data = torch.load(static_graph_path, weights_only=False)
    node_to_idx = torch.load(node_to_idx_path, weights_only=False)
    idx_to_node = {v: k for k, v in node_to_idx.items()}

    G = nx.DiGraph()
    G.add_nodes_from(range(data.num_nodes))
    edge_list = data.edge_index.t().tolist()
    G.add_edges_from(edge_list)

    # ---- 2. Fan-in / fan-out: simple in-degree / out-degree counts, plus a
    #         boolean flag at a configurable threshold (mirrors FR04.6's
    #         "minimum candidate edge density" style thresholding concept) ----
    in_deg = dict(G.in_degree())
    out_deg = dict(G.out_degree())

    # ---- 3. Short-cycle participation — full cycle enumeration is exponential
    #         on a graph this size, so we cap cycle length (length_bound) to keep
    #         this tractable. This is a deliberate approximation: it will miss
    #         long money-laundering cycles, but catches the short ones (2-4 hops)
    #         that are both the most common pattern and the cheapest to detect. ----
    print(f"Enumerating cycles up to length {max_cycle_length} (this may take a while on the full graph)...")
    nodes_in_cycle = set()
    cycle_count_per_node = {n: 0 for n in G.nodes()}
    for cycle in nx.simple_cycles(G, length_bound=max_cycle_length):
        for n in cycle:
            nodes_in_cycle.add(n)
            cycle_count_per_node[n] += 1

    # ---- 4. Simple scatter-gather approximation: for each node with high
    #         out-degree, check how many DISTINCT 2-hop-forward nodes it reaches —
    #         a low distinct-count relative to out-degree suggests fan-out funneling
    #         into a small set of receiving accounts (the "gather" side of scatter-gather).
    #         This is a simplification of the true scatter-gather pattern, not an
    #         exact detector — documented as such. ----
    scatter_gather_ratio = {}
    for n in G.nodes():
        if out_deg.get(n, 0) < fan_threshold:
            scatter_gather_ratio[n] = 0.0
            continue
        two_hop_targets = set()
        for mid in G.successors(n):
            two_hop_targets.update(G.successors(mid))
        distinct_2hop = len(two_hop_targets)
        scatter_gather_ratio[n] = 1.0 - (distinct_2hop / max(out_deg[n], 1))  # closer to 1 = more "funneled"

    # ---- 5. Assemble into a feature table, one row per account ----
    rows = []
    for n in G.nodes():
        rows.append({
            "node_idx": n,
            "account_key": idx_to_node.get(n, "unknown"),
            "in_degree": in_deg.get(n, 0),
            "out_degree": out_deg.get(n, 0),
            "fan_in_flag": int(in_deg.get(n, 0) >= fan_threshold),
            "fan_out_flag": int(out_deg.get(n, 0) >= fan_threshold),
            "cycle_count": cycle_count_per_node.get(n, 0),
            "in_short_cycle": int(n in nodes_in_cycle),
            "scatter_gather_ratio": scatter_gather_ratio.get(n, 0.0),
        })
    return pd.DataFrame(rows)

if __name__ == "__main__":
    features = build_motif_features()
    features.to_parquet("elliptic/data/processed/amlworld_motif_features.parquet")

    print(features.describe())
    print("\nNodes flagged fan_in:", features["fan_in_flag"].sum())
    print("Nodes flagged fan_out:", features["fan_out_flag"].sum())
    print("Nodes in a short cycle:", features["in_short_cycle"].sum())