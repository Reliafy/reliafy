import Plot from "./Plot.jsx";
import { bandPair, fitLine } from "../plotTheme.js";

// Step survival curve for a non-parametric estimate (KM/NA/FH/Turnbull),
// with a 95% confidence band where available.
export default function SurvivalPlot({ estimate, unit, download = null }) {
  const { x = [], R = [], cb_lower = [], cb_upper = [] } = estimate || {};
  const hasBand = cb_lower.some((v) => v != null) && cb_upper.some((v) => v != null);

  const traces = [
    ...(hasBand ? bandPair(x, cb_lower, cb_upper, { name: "95% CI", line: { shape: "hv" } }) : []),
    fitLine({
      x, y: R, name: "R(t)", line: { shape: "hv" },
      hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra></extra>",
    }),
  ];

  return (
    <Plot
      data={traces}
      layout={{
        height: 340,
        xaxis: { title: { text: unit ? `Time (${unit})` : "Time" }, rangemode: "tozero" },
        yaxis: { title: { text: "Reliability, R(t)" }, range: [0, 1.02] },
        showlegend: hasBand,
      }}
      download={download}
    />
  );
}
