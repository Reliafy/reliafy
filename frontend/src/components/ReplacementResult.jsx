import Plot from "./Plot.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatPercent, formatWithUnit } from "../format.js";
import { CATEGORY, fitLine, optimumMarker, referenceLine } from "../plotTheme.js";
import { unitInText } from "./unitText.js";
import { useCurrency } from "../WorkspaceProvider.jsx";
import { formatCost, formatCostRate } from "../money.js";

// Presentational renderer for an optimal-replacement result — used by the live
// tool and by saved analyses (which render the stored payload without refetch).
// Answer first (#311): the replacement age and the saving, the cost-rate
// curve, then the cost rates and MTTF under Details. ``actions`` (the live
// tool's Save) sits with the answer.
export default function ReplacementResult({ result, name = null, actions = null, wt }) {
  const unit = result?.unit || "";
  const u = unit ? ` (${unit})` : "";
  const currency = useCurrency();
  const per = unit ? unitInText(unit).replace(/s$/, "") : "unit time";
  const c = result.curve;
  const block = result.block || null;
  const traces = [fitLine({ x: c.t, y: c.cost_rate, name: "Age replacement", connectgaps: false })];
  if (c.block_cost_rate) {
    // Block replacement: every unit at fixed times T apart, failures as they come.
    traces.push({ type: "scatter", mode: "lines", x: c.t, y: c.block_cost_rate, name: "Block replacement",
                  connectgaps: false, line: { color: CATEGORY.pink, width: 2, dash: "dot" } });
  }
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
    xaxis: { title: { text: c.block_cost_rate ? `Replacement age, or block interval${u}` : `Replacement age${u}` } },
    yaxis: {
      title: { text: `Long-run cost (${currency}) per ${per}` },
      rangemode: "tozero",
      range: yMax ? [0, yMax] : undefined,
    },
  };

  const pays = result.beneficial && result.optimal_time != null;
  const age = formatWithUnit(result.optimal_time, unitInText(unit));
  const saving = formatPercent(result.savings);
  // How far the best age moves across the fit's 90% bounds (server-side, #189).
  const span = result.optimal_time_range;
  const range = pays && span?.lower != null && span?.upper != null && span.upper > span.lower
    ? `${formatNumber(span.lower)}–${formatWithUnit(span.upper, unitInText(unit))}` : null;
  const yearly = result.yearly;
  const money = (v) => formatCost(v, currency, { sig: 3 });
  const blockPays = block?.beneficial && block.optimal_time != null;
  const blockVsAge = blockPays && pays && result.optimal_cost_rate
    ? block.optimal_cost_rate / result.optimal_cost_rate - 1 : null;

  return (
    <>
      {pays ? (
        <ResultSummary
          tone="good"
          wt={wt}
          sentence={
            <>
              Replace preventively at about <b>{age}</b>. That lowers the long-run cost rate by{" "}
              <b>{saving}</b> versus running to failure.
            </>
          }
          stats={[
            { label: "Replace at", value: `≈ ${age}`, hint: range ? `${range} across the fit's 90% bounds` : undefined },
            { label: "Saves", value: saving, hint: "of the run-to-failure cost rate" },
            yearly?.saving_per_year != null && {
              label: "Saves a year, per unit", value: money(yearly.saving_per_year),
              hint: `at ${formatWithUnit(yearly.use_per_year, unitInText(unit))} a year`,
            },
            yearly?.fleet_saving_per_year != null && {
              label: `Saves a year, ${formatNumber(yearly.units, { sig: 6 })} units`, value: money(yearly.fleet_saving_per_year),
            },
          ]}
        >
          {blockPays && (
            <>
              Block replacement (every unit at fixed times) is best every about{" "}
              {formatWithUnit(block.optimal_time, unitInText(unit))}
              {blockVsAge != null
                ? `, ${formatPercent(Math.abs(blockVsAge))} ${blockVsAge >= 0 ? "dearer" : "cheaper"} than replacing by age.`
                : "."}
            </>
          )}
        </ResultSummary>
      ) : (
        <ResultSummary tone="caveat" sentence={result.recommendation} wt={wt} />
      )}
      {actions && <div className="rs-actions">{actions}</div>}

      <Plot data={traces} layout={layout} download={`${name || "Optimal replacement"} — cost rate`} />

      <ResultDetails
        rows={[
          pays && { label: "Cost rate at the optimum", value: formatCostRate(result.optimal_cost_rate, currency, unit, { sig: 4 }) },
          { label: "Run-to-failure cost rate", value: formatCostRate(result.run_to_failure_cost_rate, currency, unit, { sig: 4 }) },
          { label: `MTTF${u}`, value: formatNumber(result.mttf, { sig: 4 }) },
          blockPays && { label: `Block replacement, best interval${u}`, value: formatNumber(block.optimal_time, { sig: 4 }) },
          blockPays && { label: "Block replacement cost rate", value: formatCostRate(block.optimal_cost_rate, currency, unit, { sig: 4 }) },
          yearly?.cost_per_year != null && { label: "Cost a year, per unit", value: money(yearly.cost_per_year) },
          yearly?.run_to_failure_per_year != null && { label: "Run to failure a year, per unit", value: money(yearly.run_to_failure_per_year) },
        ]}
      >
        <p className="rs-note">Cost rates are long-run costs per {per}.</p>
        {result.optimal_time_range_note && <p className="rs-note">{result.optimal_time_range_note}</p>}
      </ResultDetails>
    </>
  );
}
