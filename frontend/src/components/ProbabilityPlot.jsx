import Plot from "react-plotly.js";

// Renders a probability plot from the backend payload. The backend has already
// linearised both axes with the distribution's own probability-paper
// transforms, so here we draw on plain linear axes and just position the
// supplied tick values/labels.
export default function ProbabilityPlot({ plot, unit }) {
  const { scatter, line, bounds, x_range, y_range, x_ticks, y_ticks } = plot;
  const xTitle = unit ? `Time (${unit})` : "Time";

  const traces = [
    {
      // Confidence bounds drawn as a shaded band.
      x: [...bounds.x, ...[...bounds.x].reverse()],
      y: [...bounds.upper, ...[...bounds.lower].reverse()],
      fill: "toself",
      fillcolor: "rgba(47, 109, 246, 0.10)",
      line: { color: "rgba(0,0,0,0)" },
      hoverinfo: "skip",
      name: "95% CI",
      type: "scatter",
    },
    {
      x: line.x,
      y: line.y,
      mode: "lines",
      line: { color: "#2f6df6", width: 2 },
      name: "Fit",
      type: "scatter",
    },
    {
      x: scatter.x,
      y: scatter.y,
      mode: "markers",
      marker: { color: "#7fa9f7", size: 7, line: { color: "#ffffff", width: 1.2 } },
      name: "Data",
      type: "scatter",
    },
  ];

  const layout = {
    autosize: true,
    height: 480,
    margin: { l: 60, r: 20, t: 20, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#6c727c", family: "IBM Plex Mono, monospace", size: 11 },
    legend: { orientation: "h", y: -0.15 },
    xaxis: {
      title: { text: xTitle, standoff: 12 },
      automargin: true,
      type: "linear",
      range: x_range,
      tickvals: x_ticks.vals,
      ticktext: x_ticks.labels,
      gridcolor: "#eceae4",
      linecolor: "#cdcbc3",
      zeroline: false,
    },
    yaxis: {
      title: { text: "Unreliability, F(t)", standoff: 12 },
      automargin: true,
      range: y_range,
      tickvals: y_ticks.vals,
      ticktext: y_ticks.labels,
      gridcolor: "#eceae4",
      linecolor: "#cdcbc3",
      zeroline: false,
    },
  };

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ displayModeBar: true, responsive: true }}
      style={{ width: "100%" }}
      useResizeHandler
    />
  );
}
