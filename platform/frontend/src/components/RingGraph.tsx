/**
 * The ring graph (FR-D30-34, D36-38) drawn with Cytoscape.js from GET .../subgraph, using the
 * logic ported from ring_graph.py: node cap with "load all", the currency-conversion toggle,
 * edge width by w_total threshold, solid seed and dashed expanded edges, hover details, and a
 * time slider with play. Nodes can be dragged; the layout is deterministic for a ring (FR-D37).
 */
import { useEffect, useMemo, useRef, useState } from "react";
import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import { Download, Pause, Play } from "lucide-react";
import type { RingSubgraph } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import {
  NODE_MAX_PX, NODE_MIN_PX, PLAY_MS, ROLE_STYLE, UNKNOWN_ROLE, edgeHover, edgeWidth, instant, nodeHover, roleStyle,
  sliderStops, stopLabel, visibleEdges, visibleNodes,
} from "@/lib/ring-graph";

function useIsDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(document.documentElement.classList.contains("dark")));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

interface Hover {
  x: number;
  y: number;
  width: number;
  height: number;
  lines: string[];
}

export function RingGraph({ subgraph, showConversions, loadAll, ringId }: {
  subgraph: RingSubgraph; showConversions: boolean; loadAll: boolean; ringId: string;
}) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const dark = useIsDark();
  const [hover, setHover] = useState<Hover | null>(null);

  const { nodes, edges } = useMemo(() => {
    const shown = visibleNodes(subgraph, loadAll);
    const ids = new Set(shown.map((node) => node.account_id));
    return { nodes: shown, edges: visibleEdges(subgraph, ids, showConversions) };
  }, [subgraph, loadAll, showConversions]);

  const stops = useMemo(() => sliderStops(edges), [edges]);
  const [stop, setStop] = useState(Math.max(0, stops.length - 1));
  const [playing, setPlaying] = useState(false);
  useEffect(() => setStop(Math.max(0, stops.length - 1)), [stops]);

  const colours = dark
    ? { edge: "#9aa4b8", later: "#3a4152", label: "#c9d1e0", border: "#0b1020" }
    : { edge: "#4a4a4a", later: "#d9d9d9", label: "#334155", border: "#333333" };

  // Build the graph once per ring view; positions survive slider moves and theme changes.
  useEffect(() => {
    if (!container.current) return;
    const elements: ElementDefinition[] = [
      ...[...nodes].sort((a, b) => a.account_id - b.account_id).map((node) => {
        const style = roleStyle(node.role);
        return {
          group: "nodes" as const,
          data: {
            id: `n${node.account_id}`, w: node.w_account ?? 0, colour: style.colour, shape: style.shape,
            hollow: style.hollow ? 1 : 0, label: (node.role || "?").slice(0, 3), hover: nodeHover(node),
          },
        };
      }),
      ...edges.map((edge) => ({
        group: "edges" as const,
        data: {
          id: `e${edge.edge_id}`, source: `n${edge.from_id}`, target: `n${edge.to_id}`,
          width: edgeWidth(edge.w_total), dash: edge.is_seed ? "solid" : "dashed", at: instant(edge.timestamp),
          hover: edgeHover(edge),
        },
      })),
    ];
    const cy = cytoscape({
      container: container.current, elements, minZoom: 0.2, maxZoom: 4,
      boxSelectionEnabled: false,
    });
    cyRef.current = cy;
    // Deterministic: start from a circle in account-id order, then a non-random force layout.
    cy.layout({ name: "circle", animate: false }).run();
    cy.layout({
      name: "cose", randomize: false, animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 90,
      padding: 24, fit: true,
    } as cytoscape.LayoutOptions).run();
    if (cy.zoom() > 1.4) {                    // a small ring would otherwise fill the panel
      cy.zoom(1.4);
      cy.center();
    }

    cy.on("mouseover", "node, edge", (event) => {
      const position = event.renderedPosition ?? event.target.renderedMidpoint?.() ?? { x: 0, y: 0 };
      setHover({ x: position.x, y: position.y, width: cy.width(), height: cy.height(), lines: event.target.data("hover") as string[] });
    });
    cy.on("mouseout", "node, edge", () => setHover(null));
    cy.on("drag pan zoom", () => setHover(null));
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges]);

  // Style follows the theme without rebuilding the graph.
  useEffect(() => {
    cyRef.current?.style([
      {
        selector: "node",
        style: {
          "background-color": "data(colour)", shape: "data(shape)" as never,
          width: `mapData(w, 0, 1, ${NODE_MIN_PX}, ${NODE_MAX_PX})`, height: `mapData(w, 0, 1, ${NODE_MIN_PX}, ${NODE_MAX_PX})`,
          "border-width": 1, "border-color": colours.border, label: "data(label)", "font-size": 9,
          color: colours.label, "text-valign": "top", "text-margin-y": -3,
        },
      },
      { selector: "node[hollow = 1]", style: { "background-opacity": 0, "border-width": 2, "border-color": "data(colour)" } },
      { selector: "node:grabbed", style: { "overlay-opacity": 0.12 } },
      {
        selector: "edge",
        style: {
          width: "data(width)", "line-color": colours.edge, "target-arrow-color": colours.edge,
          "target-arrow-shape": "triangle", "arrow-scale": 0.9, "curve-style": "bezier", "line-style": "data(dash)" as never,
          "line-dash-pattern": [6, 4],
        },
      },
      { selector: "edge.later", style: { "line-color": colours.later, "target-arrow-color": colours.later, opacity: 0.45 } },
      { selector: "edge:loop", style: { "loop-direction": "-45deg", "loop-sweep": "-60deg", "control-point-step-size": 30 } },
    ]);
  }, [colours.border, colours.edge, colours.label, colours.later, nodes, edges]);

  // Edges after the slider position are greyed (comparisons only).
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const limit = stops[stop]?.at;
    cy.batch(() => {
      cy.edges().forEach((edge) => {
        edge.toggleClass("later", limit !== undefined && (edge.data("at") as number) > limit);
      });
    });
  }, [stop, stops, nodes, edges]);

  useEffect(() => {
    if (!playing) return;
    if (stops.length < 2) {
      setPlaying(false);
      return;
    }
    let index = 0;
    setStop(0);
    const timer = window.setInterval(() => {
      index += 1;
      if (index >= stops.length) {
        window.clearInterval(timer);
        setPlaying(false);
        return;
      }
      setStop(index);
    }, Math.floor(PLAY_MS / stops.length));
    return () => window.clearInterval(timer);
  }, [playing, stops]);

  const downloadPng = () => {
    const cy = cyRef.current;
    if (!cy) return;
    const link = document.createElement("a");
    link.href = cy.png({ full: true, scale: 2, bg: dark ? "#141a2b" : "#ffffff" });
    link.download = `${ringId}-graph.png`;
    link.click();
  };

  // Every role always has its legend entry (FR-D31); "role not stated" only when a node has none.
  const roles: (string | null)[] = [...Object.keys(ROLE_STYLE),
    ...(nodes.some((node) => !node.role || !ROLE_STYLE[node.role]) ? [null] : [])];

  return (
    <div className="space-y-2">
      <div className="bg-background/40 relative h-[460px] overflow-hidden rounded-md border">
        <div ref={container} className="h-full w-full" data-testid="ring-graph" onMouseLeave={() => setHover(null)} />
        {hover ? (
          <div className="bg-popover text-popover-foreground pointer-events-none absolute z-10 max-w-xs rounded-md border px-2.5 py-1.5 text-xs shadow-md"
            style={{   // open toward the panel's middle so the box stays inside it
              ...(hover.x > hover.width / 2 ? { right: hover.width - hover.x + 12 } : { left: hover.x + 12 }),
              ...(hover.y > hover.height / 2 ? { bottom: hover.height - hover.y + 12 } : { top: hover.y + 12 }),
            }} role="tooltip">
            {hover.lines.map((line, index) => (
              <div key={index} className={index === 0 ? "font-semibold" : "text-muted-foreground"}>{line}</div>
            ))}
          </div>
        ) : null}
        <Button size="xs" variant="outline" className="absolute top-2 right-2" onClick={downloadPng} aria-label="Download graph as PNG">
          <Download /> PNG
        </Button>
      </div>
      {stops.length ? (
        <div className="flex items-center gap-3">
          <Button size="xs" variant="outline" onClick={() => setPlaying((value) => !value)} disabled={stops.length < 2}>
            {playing ? <Pause /> : <Play />} {playing ? "Pause" : "Play"}
          </Button>
          <Slider min={0} max={Math.max(0, stops.length - 1)} step={1} value={[stop]} onValueChange={([value]) => {
            setPlaying(false);
            setStop(value);
          }} aria-label="Time slider" disabled={stops.length < 2} />
          <span className="text-muted-foreground w-44 shrink-0 text-right text-xs tabular-nums" data-testid="graph-stop">
            Up to (UTC): {stopLabel(stops[stop]?.timestamp ?? stops[stops.length - 1].timestamp)}
          </span>
        </div>
      ) : null}
      <div className="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs" aria-label="Legend">
        {roles.map((role) => {
          const style = role ? ROLE_STYLE[role] : UNKNOWN_ROLE;
          return (
            <span key={role ?? "none"} className="inline-flex items-center gap-1" data-testid="legend-role">
              <span style={{ color: style.colour }} aria-hidden>{style.symbol}</span>
              {role ?? "role not stated"}
            </span>
          );
        })}
        <span className="inline-flex items-center gap-1.5"><span className="inline-block w-6 border-t-2 border-current" /> seed transaction</span>
        <span className="inline-flex items-center gap-1.5"><span className="inline-block w-6 border-t-2 border-dashed border-current" /> expanded transaction</span>
        <span>Width: w_total · size: w_account · drag nodes to rearrange</span>
      </div>
    </div>
  );
}
