"""The ring graph panel (FR-D30-34, D36): a directed Plotly figure built from the API's Subgraph.

Nothing here computes a number for display. Node size and edge width are visual encodings of the
w_account and w_total values the API sends; the 60-node view keeps the 60 highest w_account nodes
(sorting by a supplied field). Roles carry a colour, a marker shape and a text label (NFR-D22).
"""

from __future__ import annotations

from datetime import datetime, timezone

import networkx as nx
import plotly.graph_objects as go

from formatters import fmt_amount, fmt_seconds, fmt_time_utc, fmt_weight

ROLE_STYLE = {   # colour, marker symbol: six roles, each also named in the legend and on hover
    "source": ("#1f77b4", "circle"),
    "sink": ("#d62728", "square"),
    "mule": ("#ff7f0e", "diamond"),
    "holder": ("#2ca02c", "triangle-up"),
    "peripheral": ("#7f7f7f", "circle-open"),
    "undetermined": ("#9467bd", "x"),
}
UNKNOWN_ROLE = ("#bcbd22", "hexagon")
NODE_CAP = 60
LATER_COLOUR = "#d9d9d9"
EDGE_COLOUR = "#4a4a4a"
FRAMES = 20                     # at most 20 slider stops; play runs over PLAY_MS (FR-D34)
PLAY_MS = 5000
NODE_SIZEREF = 1 / 36           # w_account 1.0 draws a 36 px node; Plotly applies the scale
EDGE_WIDTHS = ((0.8, 6), (0.6, 4.5), (0.4, 3), (0.2, 2))       # w_total at least -> line width


def _edge_width(w_total) -> float:
    """Line width from w_total by threshold (comparisons only, FR-D32)."""
    for threshold, width in EDGE_WIDTHS:
        if w_total is not None and w_total >= threshold:
            return width
    return 1


def _frame_indices(count: int) -> list[int]:
    """Up to FRAMES evenly spaced positions in a list of `count` items (counting, not API values)."""
    if count <= FRAMES:
        return list(range(count))
    return sorted({round(k * (count - 1) / (FRAMES - 1)) for k in range(FRAMES)})


def _parse(value) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def visible_nodes(subgraph: dict, *, load_all: bool) -> list[dict]:
    """All nodes, or the NODE_CAP highest by w_account when the ring is larger (FR-D36)."""
    nodes = subgraph["nodes"]
    if load_all or len(nodes) <= NODE_CAP:
        return nodes
    ranked = sorted(nodes, key=lambda node: (node["w_account"] is not None, node["w_account"] or 0), reverse=True)
    return ranked[:NODE_CAP]


def visible_edges(subgraph: dict, node_ids: set[int], *, show_conversions: bool) -> list[dict]:
    """Edges between shown nodes; currency-conversion self-loops only when asked (change 2)."""
    return [edge for edge in subgraph["edges"]
            if edge["from_id"] in node_ids and edge["to_id"] in node_ids
            and (show_conversions or not edge["is_conversion"])]


def _node_hover(node: dict) -> str:
    return (f"Account {node['account_id']}<br>Bank: {node['bank_label'] or '—'}<br>"
            f"Role: {node['role'] or 'not stated'}<br>Inflow: {fmt_amount(node['inflow'])}<br>"
            f"Outflow: {fmt_amount(node['outflow'])}<br>Hold time: {fmt_seconds(node['hold_time_s'])}")


def _edge_hover(edge: dict) -> str:
    kind = "currency conversion" if edge["is_conversion"] else ("seed" if edge["is_seed"] else "expanded")
    return (f"Transaction {edge['edge_id']} ({kind})<br>Amount: {fmt_amount(edge['amount'], edge['currency'])}<br>"
            f"Time: {fmt_time_utc(edge['timestamp'])}<br>Payment format: {edge['payment_format'] or '—'}<br>"
            f"w_total {fmt_weight(edge['w_total'])} = w_score {fmt_weight(edge['w_score'])}, "
            f"w_loo {fmt_weight(edge['w_loo'])}, w_flow {fmt_weight(edge['w_flow'])}")


def build_figure(subgraph: dict, *, show_conversions: bool = False, load_all: bool = False) -> go.Figure:
    nodes = visible_nodes(subgraph, load_all=load_all)
    node_ids = {node["account_id"] for node in nodes}
    edges = visible_edges(subgraph, node_ids, show_conversions=show_conversions)
    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(node_ids))
    graph.add_edges_from((edge["from_id"], edge["to_id"]) for edge in edges if edge["from_id"] != edge["to_id"])
    position = nx.spring_layout(graph, seed=7)          # deterministic for a given ring

    figure = go.Figure()
    edge_traces = []
    for edge in edges:
        (x0, y0), (x1, y1) = position[edge["from_id"]], position[edge["to_id"]]
        if edge["from_id"] == edge["to_id"]:              # a conversion self-loop: a small ring
            xs = [x0, x0 + 0.04, x0 + 0.06, x0 + 0.04, x0]
            ys = [y0, y0 + 0.05, y0, y0 - 0.05, y0]
        else:
            xs, ys = [x0, x1], [y0, y1]
        width = _edge_width(edge["w_total"])
        edge_traces.append(len(figure.data))
        figure.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines", hoverinfo="skip", showlegend=False,
            line={"width": width, "color": EDGE_COLOUR, "dash": "solid" if edge["is_seed"] else "dash"},
        ))
    figure.add_trace(go.Scatter(                        # hover targets at edge midpoints
        x=[(position[e["from_id"]][0] + position[e["to_id"]][0]) / 2 for e in edges],
        y=[(position[e["from_id"]][1] + position[e["to_id"]][1]) / 2 for e in edges],
        mode="markers", marker={"size": 9, "color": "rgba(0,0,0,0)"}, showlegend=False,
        hovertext=[_edge_hover(e) for e in edges], hoverinfo="text"))
    for role in [*ROLE_STYLE, None]:
        members = [node for node in nodes if (node["role"] if node["role"] in ROLE_STYLE else None) == role]
        if not members:
            continue
        colour, symbol = ROLE_STYLE.get(role, UNKNOWN_ROLE)
        figure.add_trace(go.Scatter(
            x=[position[n["account_id"]][0] for n in members], y=[position[n["account_id"]][1] for n in members],
            mode="markers+text", name=role or "role not stated", text=[(role or "?")[:3] for _ in members],
            textposition="top center", textfont={"size": 9},
            marker={"color": colour, "symbol": symbol, "line": {"width": 1, "color": "#333"},
                    "size": [n["w_account"] or 0 for n in members],          # Plotly scales: sizeref
                    "sizemode": "diameter", "sizeref": NODE_SIZEREF, "sizemin": 8},
            hovertext=[_node_hover(n) for n in members], hoverinfo="text"))
    for label, dash in (("seed transaction", "solid"), ("expanded transaction", "dash")):
        figure.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=label,
                                    line={"color": EDGE_COLOUR, "dash": dash, "width": 2}))

    arrows = [dict(x=position[e["to_id"]][0], y=position[e["to_id"]][1], ax=position[e["from_id"]][0],
                   ay=position[e["from_id"]][1], xref="x", yref="y", axref="x", ayref="y", showarrow=True,
                   arrowhead=3, arrowsize=1.2, arrowwidth=1.2, arrowcolor=EDGE_COLOUR, standoff=8, text="")
              for e in edges if e["from_id"] != e["to_id"]]
    arrow_edges = [e for e in edges if e["from_id"] != e["to_id"]]

    # Time slider (FR-D34): positions run from the ring's first to its last transaction; edges
    # after the slider are greyed. Comparisons only; no value is computed for display.
    times = sorted({_parse(e["timestamp"]) for e in edges}) if edges else []
    if times:
        # Slider stops are the transactions' own times (at most FRAMES of them), so no instant
        # is computed from API values.
        stops = [times[index] for index in _frame_indices(len(times))]
        frames, steps = [], []
        for k, stop in enumerate(stops):
            colours = [EDGE_COLOUR if _parse(e["timestamp"]) <= stop else LATER_COLOUR for e in edges]
            frame_arrows = [{**a, "arrowcolor": EDGE_COLOUR if _parse(e["timestamp"]) <= stop else LATER_COLOUR}
                            for a, e in zip(arrows, arrow_edges)]
            frames.append(go.Frame(name=str(k), traces=edge_traces,
                                   data=[go.Scatter(line={"color": c}) for c in colours],
                                   layout={"annotations": frame_arrows}))
            steps.append({"label": stop.strftime("%d %b %H:%M"), "method": "animate",
                          "args": [[str(k)], {"mode": "immediate", "frame": {"duration": 0, "redraw": True}}]})
        figure.frames = frames
        figure.update_layout(
            sliders=[{"active": len(stops) - 1, "steps": steps, "currentvalue": {"prefix": "Up to (UTC): "},
                      "pad": {"t": 30}}],
            updatemenus=[{"type": "buttons", "showactive": False, "x": 0, "y": -0.08, "xanchor": "left",
                          "buttons": [{"label": "▶ Play", "method": "animate",
                                       "args": [None, {"frame": {"duration": PLAY_MS // len(stops), "redraw": True},
                                                       "fromcurrent": False, "transition": {"duration": 0}}]}]}],
        )
    figure.update_layout(annotations=arrows, height=520, margin={"l": 10, "r": 10, "t": 10, "b": 10},
                         xaxis={"visible": False}, yaxis={"visible": False},
                         legend={"orientation": "h", "y": -0.25}, hovermode="closest")
    return figure
