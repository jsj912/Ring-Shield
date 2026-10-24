import { describe, expect, it } from "vitest";
import big from "../../../dashboard/fixtures/rings/1001_full-gine_causal-1-8.json";
import small from "../../../dashboard/fixtures/rings/1001_full-gine_causal-1-9.json";
import type { RingSubgraph } from "@/api/types";
import { FRAMES, NODE_CAP, edgeHover, edgeWidth, frameIndices, nodeHover, sliderStops, stopLabel, visibleEdges, visibleNodes } from "./ring-graph";

const bigGraph = big.subgraph as unknown as RingSubgraph;
const smallGraph = small.subgraph as unknown as RingSubgraph;

describe("ring graph logic (ring_graph.py)", () => {
  it("caps a large ring at the 60 highest w_account nodes, and loads all on request", () => {
    expect(bigGraph.n_accounts).toBe(120);
    const shown = visibleNodes(bigGraph, false);
    expect(shown).toHaveLength(NODE_CAP);
    const lowestShown = Math.min(...shown.map((node) => node.w_account ?? 0));
    const hidden = bigGraph.nodes.filter((node) => !shown.includes(node));
    expect(Math.max(...hidden.map((node) => node.w_account ?? 0))).toBeLessThanOrEqual(lowestShown);
    expect(visibleNodes(bigGraph, true)).toHaveLength(120);
  });

  it("hides currency-conversion edges unless asked", () => {
    const ids = new Set(smallGraph.nodes.map((node) => node.account_id));
    const hidden = visibleEdges(smallGraph, ids, false);
    const shown = visibleEdges(smallGraph, ids, true);
    expect(hidden.some((edge) => edge.is_conversion)).toBe(false);
    expect(shown.length).toBeGreaterThan(hidden.length);
  });

  it("sets edge width by w_total threshold", () => {
    expect([edgeWidth(0.85), edgeWidth(0.8), edgeWidth(0.61), edgeWidth(0.4), edgeWidth(0.2), edgeWidth(0.1), edgeWidth(null)])
      .toEqual([6, 6, 4.5, 3, 2, 1, 1]);
  });

  it("picks at most 20 evenly spaced slider stops", () => {
    expect(frameIndices(5)).toEqual([0, 1, 2, 3, 4]);
    const many = frameIndices(159);
    expect(many).toHaveLength(FRAMES);
    expect(many[0]).toBe(0);
    expect(many.at(-1)).toBe(158);
    const stops = sliderStops(smallGraph.edges);
    expect(stops.map((stop) => stop.at)).toEqual([...stops.map((stop) => stop.at)].sort((a, b) => a - b));
    expect(stopLabel("2022-09-10T11:16:54Z")).toBe("10 Sep 11:16");
  });

  it("puts every required field in the hover text (FR-D33)", () => {
    const node = nodeHover(smallGraph.nodes[0]).join(" ");
    for (const label of ["Account", "Bank", "Role", "Inflow", "Outflow", "Hold time"]) expect(node).toContain(label);
    const edge = edgeHover(smallGraph.edges[0]).join(" ");
    for (const label of ["Amount", "Time", "Payment format", "w_total", "w_score", "w_loo", "w_flow"]) expect(edge).toContain(label);
  });
});
