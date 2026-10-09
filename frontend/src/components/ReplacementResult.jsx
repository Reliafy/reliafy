import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatWithUnit } from "../format.js";
import { fitLine, optimumMarker, referenceLine } from "../plotTheme.js";

// Presentational renderer for an optimal-replacement result — used by the live
// tool and by saved analyses (which render the stored payload without refetch).
// Answer first (#311): the replacement age and the saving, the cost-rate
// curve, then the cost rates and MTTF under Details.
export default function ReplacementResult({ result, name = null }) {
  const unit = result?.unit || "";
  const u = unit ? ` (${unit})` : "";
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
      text: [`Optimum ${formatNumber(result.optimal_time)}`],
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

  const pays = result.beneficial && result.optimal_time != null;
  const age = formatWithUnit(result.optimal_time, unit);
  const saving = formatPercent(result.savings);

  return (
    <>
      {pays ? (
        <ResultSummary
          tone="good"
          sentence={
            <>
              Replace preventively at about <b>{age}</b>. That lowers the long-run cost rate by{" "}
              <b>{saving}</b> versus running to failure.
            </>
          }
          stats={[
            { label: "Replace at", value: `≈ ${age}` },
            { label: "Saves", value: saving, hint: "of the run-to-failure cost rate" },
          ]}
        />
      ) : (
        <ResultSummary tone="caveat" sentence={result.recommendation} />
      )}

      <Plot data={traces} layout={layout} download={`${name || "Optimal replacement"} — cost rate`} />

      <ResultDetails
        rows={[
          pays && { label: "Cost rate at the optimum", value: formatNumber(result.optimal_cost_rate, { sig: 4 }) },
          { label: "Run-to-failure cost rate", value: formatNumber(result.run_to_failure_cost_rate, { sig: 4 }) },
          { label: `MTTF${u}`, value: formatNumber(result.mttf, { sig: 4 }) },
        ]}
      >
        <p className="rs-note">Cost rates are long-run costs per unit time.</p>
      </ResultDetails>
    </>
  );
}
