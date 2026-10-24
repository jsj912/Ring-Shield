/** react-plotly.js over the basic Plotly bundle (bar and scatter), themed for light and dark. */
import { useEffect, useState, type ComponentType } from "react";
import Plotly from "plotly.js-basic-dist-min";
import createPlotlyComponent from "react-plotly.js/factory";
import type { PlotParams } from "react-plotly.js";

const PlotlyPlot = createPlotlyComponent(Plotly) as ComponentType<PlotParams>;

function useIsDark(): boolean {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const observer = new MutationObserver(() => setDark(document.documentElement.classList.contains("dark")));
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

export function Plot({ data, layout, height = 320, testId }: {
  data: PlotParams["data"]; layout?: PlotParams["layout"]; height?: number; testId?: string;
}) {
  const dark = useIsDark();
  const ink = dark ? "#c9d1e0" : "#334155";
  const grid = dark ? "rgba(255,255,255,0.08)" : "rgba(15,23,42,0.08)";
  return (
    <div data-testid={testId}>
      <PlotlyPlot
        data={data}
        layout={{
          height, autosize: true, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
          font: { color: ink, size: 11, family: "Inter, system-ui, sans-serif" },
          margin: { l: 10, r: 10, t: 10, b: 10 },
          ...layout,
          xaxis: { gridcolor: grid, zerolinecolor: grid, automargin: true, ...layout?.xaxis },
          yaxis: { gridcolor: grid, zerolinecolor: grid, automargin: true, ...layout?.yaxis },
        }}
        config={{ displaylogo: false, responsive: true }}
        useResizeHandler
        style={{ width: "100%" }}
      />
    </div>
  );
}
