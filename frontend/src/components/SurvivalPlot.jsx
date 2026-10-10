import { useState } from "react";
import Plot from "./Plot.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { bandPair, fitLine } from "../plotTheme.js";
import "./NonParametric.css";

// The band choices (#85): pointwise holds at each time on its own; the two
// simultaneous bands hold for the whole curve at once.
const BANDS = [
  { value: "pointwise", label: "Each time", legend: "95% CI",
    title: "95% sure of the curve at each time on its own" },
  { value: "hall-wellner", label: "Whole curve", legend: "95% band, whole curve",
    title: "Hall-Wellner band: 95% sure the whole curve lies inside it, from the first failure to the last" },
  { value: "nair", label: "Whole curve (Nair)", legend: "95% band, whole curve (Nair)",
    title: "Nair's equal-precision band: 95% sure the whole curve lies inside it, over the middle of the data; "
      + "its width follows the pointwise bounds" },
];

// Step survival curve for a non-parametric estimate (KM/NA/FH/Turnbull),
// with a 95% confidence band where available. ``estimate.bands`` (fits from
// #85 on) adds the simultaneous bands, chosen under the chart.
export default function SurvivalPlot({ estimate, unit, download = null }) {
  const { x = [], R = [], cb_lower = [], cb_upper = [], bands = {} } = estimate || {};
  const [which, setWhich] = useState("pointwise");
  const options = BANDS.filter((b) => b.value === "pointwise" || bands[b.value]);
  const pick = options.find((b) => b.value === which) || options[0];
  const sim = pick.value !== "pointwise" ? bands[pick.value] : null;
  const hasBand = sim ? true : cb_lower.some((v) => v != null) && cb_upper.some((v) => v != null);

  const traces = [
    ...(sim
      ? bandPair(sim.x, sim.lower, sim.upper, { name: pick.legend, line: { shape: "hv" } })
      : hasBand ? bandPair(x, cb_lower, cb_upper, { name: pick.legend, line: { shape: "hv" } }) : []),
    fitLine({
      x, y: R, name: "R(t)", line: { shape: "hv" },
      hovertemplate: "%{x:,.4~g}: R=%{y:.3f}<extra></extra>",
    }),
  ];

  return (
    <>
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
      {options.length > 1 && (
        <div className="plot-option-row">
          <SegmentedControl
            size="sm"
            label="95% band"
            showLabel
            options={options.map(({ value, label, title }) => ({ value, label, title }))}
            value={pick.value}
            onChange={setWhich}
          />
        </div>
      )}
    </>
  );
}
