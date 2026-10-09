import Plot from "./Plot.jsx";
import { ACCENT, BAND_FILL, DANGER, DATA_INK, band, dataPoints, fitLine, referenceShape } from "../plotTheme.js";

// One tracked item's outlook: its measurements, the projected degradation
// path, the failure threshold, and the predicted crossing time with its 95%
// credible interval band.
export default function RulChart({ item, threshold, unit, measurementUnit }) {
  const pred = item.prediction || {};
  const meas = item.measurements || [];
  const xTitle = unit ? `Time (${unit})` : "Time";
  const yTitle = measurementUnit ? `Measurement (${measurementUnit})` : "Measurement";

  // Confidence of the crossing-time interval, from the prediction itself.
  const ciPct = pred.alpha_ci != null ? Math.round((1 - pred.alpha_ci) * 100) : 95;

  const traces = [];
  if (pred.projection?.lo && pred.projection?.hi) {
    // Credible band around the projected degradation path (posterior spread).
    traces.push(band({
      x: [...pred.projection.x, ...[...pred.projection.x].reverse()],
      y: [...pred.projection.hi, ...[...pred.projection.lo].reverse()],
      name: "Path credible band",
    }));
  }
  if (pred.projection) {
    traces.push(fitLine({ x: pred.projection.x, y: pred.projection.y, line: { dash: "dot" }, name: "Projected path" }));
  }
  traces.push(dataPoints({
    x: meas.map((m) => m.t), y: meas.map((m) => m.y), mode: "lines+markers",
    line: { color: DATA_INK, width: 1.25 },
    name: "Measurements",
  }));

  // The failure threshold: red, it is where the item has failed, and labelled.
  const shapes = [referenceShape({ y: threshold, line: { color: DANGER, width: 1.5 } })];
  const annotations = [];
  if (threshold != null) {
    annotations.push({
      xref: "paper", x: 0, y: threshold, xanchor: "left", yanchor: "bottom", showarrow: false,
      text: `Limit ${threshold}${measurementUnit ? ` ${measurementUnit}` : ""}`, font: { color: DANGER },
    });
  }

  const [lo, hi] = pred.failure_time_interval || [null, null];
  if (lo !== null && hi !== null) {
    shapes.push({
      type: "rect", yref: "paper", x0: lo, x1: hi, y0: 0, y1: 1,
      fillcolor: BAND_FILL, line: { width: 0 },
    });
    annotations.push({
      x: lo, yref: "paper", y: 0, yanchor: "top",
      text: `${ciPct}% interval`, showarrow: false, xanchor: "left",
    });
  }
  if (pred.failure_time !== null && pred.failure_time !== undefined) {
    shapes.push(referenceShape({ x: pred.failure_time, line: { color: ACCENT, width: 1.5 } }));
    annotations.push({
      x: pred.failure_time, yref: "paper", y: 1, yanchor: "top", xanchor: "left", xshift: 4,
      text: "Expected crossing", showarrow: false, font: { color: ACCENT },
    });
  }

  const layout = {
    height: 360,
    xaxis: { title: { text: xTitle }, rangemode: "tozero" },
    yaxis: { title: { text: yTitle }, rangemode: "tozero" },
    shapes,
    annotations,
  };

  return <Plot data={traces} layout={layout} />;
}
