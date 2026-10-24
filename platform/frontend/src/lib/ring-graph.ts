/**
 * The ring graph's logic, ported from platform/dashboard/ring_graph.py (FR-D30-34, D36).
 *
 * Nothing here computes a number for display. Node size and edge width are visual encodings of
 * the w_account and w_total values the API sends; the 60-node view keeps the 60 highest
 * w_account nodes (sorting by a supplied field). Roles carry a colour, a shape and a text label
 * (NFR-D22).
 */
import type { RingSubgraph, SubgraphEdge, SubgraphNode } from "@/api/types";
import { fmtAmount, fmtSeconds, fmtTimeUtc, fmtWeight } from "./formatters";

/** Colour and Cytoscape shape per role; six roles, each also named in the legend and on hover. */
export interface RoleStyle {
  colour: string;
  shape: string;
  hollow?: boolean;
  symbol: string;
}

export const ROLE_STYLE: Record<string, RoleStyle> = {
  source: { colour: "#1f77b4", shape: "ellipse", symbol: "●" },
  sink: { colour: "#d62728", shape: "rectangle", symbol: "■" },
  mule: { colour: "#ff7f0e", shape: "diamond", symbol: "◆" },
  holder: { colour: "#2ca02c", shape: "triangle", symbol: "▲" },
  peripheral: { colour: "#7f7f7f", shape: "ellipse", hollow: true, symbol: "○" },
  undetermined: { colour: "#9467bd", shape: "star", symbol: "★" },
};
export const UNKNOWN_ROLE: RoleStyle = { colour: "#bcbd22", shape: "hexagon", symbol: "⬢" };
export const NODE_CAP = 60;
export const FRAMES = 20;            // at most 20 slider stops; play runs over PLAY_MS (FR-D34)
export const PLAY_MS = 5000;
export const NODE_MIN_PX = 8;        // w_account 0 (or missing) draws at least an 8 px node
export const NODE_MAX_PX = 36;       // w_account 1.0 draws a 36 px node; Cytoscape applies the scale
export const EDGE_WIDTHS: [number, number][] = [[0.8, 6], [0.6, 4.5], [0.4, 3], [0.2, 2]];   // w_total at least -> width

export function roleStyle(role: string | null): RoleStyle {
  return (role && ROLE_STYLE[role]) || UNKNOWN_ROLE;
}

/** Line width from w_total by threshold (comparisons only, FR-D32). */
export function edgeWidth(wTotal: number | null | undefined): number {
  for (const [threshold, width] of EDGE_WIDTHS) {
    if (wTotal !== null && wTotal !== undefined && wTotal >= threshold) return width;
  }
  return 1;
}

/** Up to FRAMES evenly spaced positions in a list of `count` items (counting, not API values). */
export function frameIndices(count: number): number[] {
  if (count <= FRAMES) return Array.from({ length: count }, (_, index) => index);
  const picked = new Set<number>();
  for (let k = 0; k < FRAMES; k++) picked.add(Math.round((k * (count - 1)) / (FRAMES - 1)));
  return [...picked].sort((a, b) => a - b);
}

/** All nodes, or the NODE_CAP highest by w_account when the ring is larger (FR-D36). */
export function visibleNodes(subgraph: RingSubgraph, loadAll: boolean): SubgraphNode[] {
  const nodes = subgraph.nodes;
  if (loadAll || nodes.length <= NODE_CAP) return nodes;
  // Python sorts by (w_account is not None, w_account or 0) descending, stably.
  const ranked = [...nodes].sort((a, b) => {
    const aHas = a.w_account !== null, bHas = b.w_account !== null;
    if (aHas !== bHas) return aHas ? -1 : 1;
    const aw = a.w_account ?? 0, bw = b.w_account ?? 0;
    return aw === bw ? 0 : aw > bw ? -1 : 1;
  });
  return ranked.slice(0, NODE_CAP);
}

/** Edges between shown nodes; currency-conversion self-loops only when asked (change 2). */
export function visibleEdges(subgraph: RingSubgraph, nodeIds: Set<number>, showConversions: boolean): SubgraphEdge[] {
  return subgraph.edges.filter((edge) => nodeIds.has(edge.from_id) && nodeIds.has(edge.to_id)
    && (showConversions || !edge.is_conversion));
}

export function edgeKind(edge: SubgraphEdge): string {
  return edge.is_conversion ? "currency conversion" : edge.is_seed ? "seed" : "expanded";
}

/** Hover lines for a node (FR-D33). */
export function nodeHover(node: SubgraphNode): string[] {
  return [
    `Account ${node.account_id}`,
    `Bank: ${node.bank_label || "—"}`,
    `Role: ${node.role || "not stated"}`,
    `Inflow: ${fmtAmount(node.inflow)}`,
    `Outflow: ${fmtAmount(node.outflow)}`,
    `Hold time: ${fmtSeconds(node.hold_time_s)}`,
  ];
}

/** Hover lines for an edge (FR-D33). */
export function edgeHover(edge: SubgraphEdge): string[] {
  return [
    `Transaction ${edge.edge_id} (${edgeKind(edge)})`,
    `Amount: ${fmtAmount(edge.amount, edge.currency)}`,
    `Time: ${fmtTimeUtc(edge.timestamp)}`,
    `Payment format: ${edge.payment_format || "—"}`,
    `w_total ${fmtWeight(edge.w_total)} = w_score ${fmtWeight(edge.w_score)}, w_loo ${fmtWeight(edge.w_loo)}, w_flow ${fmtWeight(edge.w_flow)}`,
  ];
}

export function instant(value: string): number {
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value);
  return Date.parse(hasZone ? value : `${value}Z`);
}

/**
 * Time slider stops (FR-D34): the edges' own distinct times, at most FRAMES of them, so no
 * instant is computed from API values. Each stop keeps the edge's timestamp text for its label.
 */
export function sliderStops(edges: SubgraphEdge[]): { at: number; timestamp: string }[] {
  const byInstant = new Map<number, string>();
  for (const edge of edges) {
    const at = instant(edge.timestamp);
    if (!byInstant.has(at)) byInstant.set(at, edge.timestamp);
  }
  const times = [...byInstant.keys()].sort((a, b) => a - b);
  return frameIndices(times.length).map((index) => ({ at: times[index], timestamp: byInstant.get(times[index])! }));
}

const stopFormat = new Intl.DateTimeFormat("en-US", {
  timeZone: "UTC", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

/** "09 Sep 23:33", the stop's label in UTC (ring_graph.py: "%d %b %H:%M"). */
export function stopLabel(timestamp: string): string {
  const parts = Object.fromEntries(stopFormat.formatToParts(new Date(instant(timestamp))).map((p) => [p.type, p.value]));
  return `${parts.day} ${parts.month} ${parts.hour}:${parts.minute}`;
}
