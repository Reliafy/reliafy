import Plot from "react-plotly.js";

// Step survival curve for a non-parametric estimate (KM/NA/FH/Turnbull),
// with a 95% confidence band where available.
export default function SurvivalPlot({ estimate, unit }) {
  const { x = [], R = [], cb_lower = [], cb_upper = [] } = estimate || {};
  const hasBand = cb_lower.some((v) => v != null) && cb_upper.some((v) => v != null);

  const traces = [];
  if (hasBand) {
    traces.push(
      { x, y: cb_upper, mode: "lines", line: { width: 0, shape: "hv" }, hoverinfo: "skip", showlegend: false },
      {
        x, y: cb_lower, mode: "lines", line: { width: 0, shape: "hv" },
        fill: "tonexty", fillcolor: "rgba(47,109,246,0.12)",
        hoverinfo: "skip", name: "95% CI", showlegend: true,
      }
    );
  }
  traces.push({
    x, y: R, mode: "lines", line: { color: "#2f6df6", width: 2, shape: "hv" },
    name: "R(t)", hovertemplate: "%{x:.4g}: R=%{y:.3f}<extra></extra>",
  });

  return (
    <Plot
      data={traces}
      layout={{
        height: 340,
        margin: { l: 52, r: 16, t: 8, b: 44 },
        xaxis: { title: { text: unit ? `time (${unit})` : "time" }, rangemode: "tozero" },
        yaxis: { title: { text: "reliability R(t)" }, range: [0, 1.02] },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        showlegend: hasBand,
        legend: { orientation: "h", y: 1.08 },
      }}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: "100%" }}
    />
  );
}
