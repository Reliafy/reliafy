import Plot from "./Plot.jsx";
import { fitLine, optimumMarker, referenceLine } from "../plotTheme.js";

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

// Presentational renderer for an optimal-replacement result — used by the live
// tool and by saved analyses (which render the stored payload without refetch).
export default function ReplacementResult({ result, name = null }) {
  const u = result?.unit ? ` (${result.unit})` : "";
  const c = result.curve;
  const traces = [fitLine({ x: c.t, y: c.cost_rate, name: "Cost rate", connectgaps: false })];
  if (result.run_to_failure_cost_rate != null) {
    traces.push(referenceLine({
      x: [c.t[0], c.t[c.t.length - 1]],
      y: [result.run_to_failure_cost_rate, result.run_to_failure_cost_rate],
      name: "Run-to-failure",
    }));
  }
  if (result.optimal_time != null && result.optimal_cost_rate != null) {
    traces.push(optimumMarker({
      x: [result.optimal_time],
      y: [result.optimal_cost_rate],
      name: "Optimum",
      text: [`Optimum ${fmt(result.optimal_time)}`],
    }));
  }
  const yMax = result.run_to_failure_cost_rate
    ? result.run_to_failure_cost_rate * 2.5
    : undefined;
  const layout = {
    height: 400,
    showlegend: true,
    xaxis: { title: { text: `Replacement age${u}` } },
    yaxis: {
      title: { text: "Long-run cost per unit time" },
      rangemode: "tozero",
      range: yMax ? [0, yMax] : undefined,
    },
  };

  return (
    <>
      <div className={"strategy-reco " + (result.beneficial ? "" : "strategy-reco-warn")}>
        <span className="strategy-reco-icon">{result.beneficial ? "✓" : "ⓘ"}</span>
        <span>{result.recommendation}</span>
      </div>

      <div className="params">
        <div className="stat">
          <div className="value">{result.optimal_time == null ? "—" : fmt(result.optimal_time)}</div>
          <div className="name">optimal age{u}</div>
        </div>
        <div className="stat">
          <div className="value">{result.beneficial ? `${(result.savings * 100).toFixed(0)}%` : "0%"}</div>
          <div className="name">cost saving vs. run-to-failure</div>
        </div>
        <div className="stat">
          <div className="value">{fmt(result.optimal_cost_rate ?? result.run_to_failure_cost_rate)}</div>
          <div className="name">best cost rate</div>
        </div>
        <div className="stat">
          <div className="value">{fmt(result.mttf)}</div>
          <div className="name">MTTF{u}</div>
        </div>
      </div>

      <Plot data={traces} layout={layout} download={`${name || "Optimal replacement"} — cost rate`} />
    </>
  );
}
