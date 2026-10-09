import Plot from "./Plot.jsx";
import { GRID, band, dataPoints, fitLine } from "../plotTheme.js";

// Renders a probability plot from the backend payload. The backend has already
// linearised both axes with the distribution's own probability-paper
// transforms, so here we draw on plain linear axes and just position the
// supplied tick values/labels.
export default function ProbabilityPlot({ plot, unit, download = null }) {
  const { scatter, line, bounds, x_range, y_range, x_ticks, y_ticks } = plot;
  const xTitle = unit ? `Time (${unit})` : "Time";

  const traces = [
    // Confidence bounds, when the fit produced a covariance matrix. A mixture
    // fit doesn't, so it draws without a band rather than not at all.
    ...(bounds ? [band({
      x: [...bounds.x, ...[...bounds.x].reverse()],
      y: [...bounds.upper, ...[...bounds.lower].reverse()],
      name: "95% CI",
    })] : []),
    fitLine({ x: line.x, y: line.y, name: "Fit" }),
    dataPoints({ x: scatter.x, y: scatter.y, name: "Data" }),
  ];

  const layout = {
    height: 480,
    // The legend sits inside the plot, top left: on probability paper the
    // points run from bottom left to top right, so that corner is empty.
    legend: {
      orientation: "v",
      x: 0.015,
      xanchor: "left",
      y: 0.985,
      yanchor: "top",
      bgcolor: "rgba(255,255,255,0.85)",
    },
    xaxis: {
      title: { text: xTitle },
      type: "linear",
      range: x_range,
      tickvals: x_ticks.vals,
      ticktext: x_ticks.labels,
      // Probability paper: both grids carry meaning.
      showgrid: true,
      gridcolor: GRID,
    },
    yaxis: {
      title: { text: "Unreliability, F(t)" },
      range: y_range,
      tickvals: y_ticks.vals,
      ticktext: y_ticks.labels,
    },
  };

  return <Plot data={traces} layout={layout} download={download} />;
}
