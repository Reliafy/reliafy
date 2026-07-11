import Plot from "react-plotly.js";

// One tracked item's outlook: its measurements, the projected degradation
// path, the failure threshold, and the predicted crossing time with its 95%
// credible interval band.
export default function RulChart({ item, threshold, unit, measurementUnit }) {
  const pred = item.prediction || {};
  const meas = item.measurements || [];
  const xTitle = unit ? `Time (${unit})` : "Time";
  const yTitle = measurementUnit ? `Measurement (${measurementUnit})` : "Measurement";

  const traces = [];
  if (pred.projection?.lo && pred.projection?.hi) {
    // 95% credible band around the projected path (posterior uncertainty).
    traces.push({
      x: [...pred.projection.x, ...[...pred.projection.x].reverse()],
      y: [...pred.projection.hi, ...[...pred.projection.lo].reverse()],
      fill: "toself",
      fillcolor: "rgba(47, 109, 246, 0.10)",
      line: { color: "rgba(0,0,0,0)" },
      hoverinfo: "skip",
      name: "95% credible band",
      type: "scatter",
    });
  }
  if (pred.projection) {
    traces.push({
      x: pred.projection.x, y: pred.projection.y, mode: "lines", type: "scatter",
      line: { color: "#2f6df6", width: 2, dash: "dot" }, name: "Projected path",
    });
  }
  traces.push({
    x: meas.map((m) => m.t), y: meas.map((m) => m.y),
    mode: "lines+markers", type: "scatter",
    line: { color: "#2f6df6", width: 1.4 },
    marker: { color: "#2f6df6", size: 8, line: { color: "#fff", width: 1.2 } },
    name: "Measurements",
  });

  const shapes = [{
    type: "line", xref: "paper", x0: 0, x1: 1, y0: threshold, y1: threshold,
    line: { color: "#d05a5a", width: 1.6, dash: "dash" },
  }];
  const annotations = [];

  const [lo, hi] = pred.failure_time_interval || [null, null];
  if (lo !== null && hi !== null) {
    shapes.push({
      type: "rect", yref: "paper", x0: lo, x1: hi, y0: 0, y1: 1,
      fillcolor: "rgba(47, 109, 246, 0.08)", line: { width: 0 },
    });
  }
  if (pred.failure_time !== null && pred.failure_time !== undefined) {
    shapes.push({
      type: "line", yref: "paper", x0: pred.failure_time, x1: pred.failure_time, y0: 0, y1: 1,
      line: { color: "#2f6df6", width: 1.4, dash: "dash" },
    });
    annotations.push({
      x: pred.failure_time, yref: "paper", y: 1, yanchor: "bottom",
      text: "predicted crossing", showarrow: false, font: { color: "#2f6df6", size: 10 },
    });
  }

  const layout = {
    autosize: true,
    height: 360,
    margin: { l: 60, r: 20, t: 28, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#6c727c", family: "IBM Plex Mono, monospace", size: 11 },
    legend: { orientation: "h", y: -0.2 },
    xaxis: { title: { text: xTitle, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
    yaxis: { title: { text: yTitle, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
    shapes,
    annotations,
  };

  return (
    <Plot data={traces} layout={layout} config={{ displayModeBar: false, responsive: true }} style={{ width: "100%" }} useResizeHandler />
  );
}
