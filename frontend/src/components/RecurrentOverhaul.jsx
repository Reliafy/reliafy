import { useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { recurrentOverhaul } from "../api.js";
import { unitInText } from "./unitText.js";
import { CardHeader } from "./ui/Card.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatWithUnit } from "../format.js";

// Optimal overhaul interval for a saved recurrent model: minimal repair between
// overhauls, an overhaul renews the system. Minimises the long-run cost rate
// (cr·Λ(T) + co) / T server-side (RePyability's Repairable). Styled like the
// Strategy › Optimal replacement tool: the answer first (#311), the cost-rate
// curve, the cost rates under Details.
export default function RecurrentOverhaul({ modelId, unit, name = null }) {
  const [cr, setCr] = useState("");
  const [co, setCo] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const u = unit ? ` (${unit})` : "";
  const ut = unit ? unitInText(unit) : "";

  const canRun = Number(cr) > 0 && Number(co) > 0;
  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      setResult(await recurrentOverhaul(modelId, Number(cr), Number(co)));
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const opt = result?.optimal;
  const none = result?.never_overhaul;
  let plot = null;
  if (opt && result.curve) {
    const c = result.curve;
    const traces = [
      fitLine({ x: c.t, y: c.cost_rate, name: "Cost rate", connectgaps: false }),
      optimumMarker({ x: [opt.interval], y: [opt.cost_rate], name: "Optimum T*", text: [`T* ${formatNumber(opt.interval)}`] }),
    ];
    const layout = {
      height: 380,
      xaxis: { title: { text: `Overhaul interval${u}` } },
      yaxis: { title: { text: "Long-run cost per unit time" }, rangemode: "tozero", range: [0, opt.cost_rate * 2.5] },
      shapes: [referenceShape({ x: opt.interval, line: { dash: "dot" } })],
    };
    plot = <Plot data={traces} layout={layout} download={`${name || "Recurrent model"} — overhaul cost rate`} />;
  }

  return (
    <div className="strategy-tool">
      <CardHeader
        title="Optimal overhaul interval"
        subtitle="Minimal repair between overhauls; an overhaul restores the system to as-good-as-new."
      />
      <div className="strategy-form">
        <div className="strategy-costs">
          <label className="calc-t">
            <span>Repair cost (per failure)</span>
            <input type="number" min="0" step="any" value={cr} onChange={(e) => setCr(e.target.value)} />
          </label>
          <label className="calc-t">
            <span>Overhaul cost</span>
            <input type="number" min="0" step="any" value={co} onChange={(e) => setCo(e.target.value)} />
          </label>
          <button onClick={run} disabled={!canRun || loading}>
            {loading ? "Calculating…" : "Calculate"}
          </button>
        </div>
        <p className="hint">Same currency for both.</p>
      </div>

      {error && <div className="error">{error}</div>}

      {result && !opt && <ResultSummary tone="caveat" sentence={result.reason} />}

      {opt && (
        <>
          <ResultSummary
            tone={result.saving_pct > 0 ? "good" : "neutral"}
            sentence={
              <>
                Overhaul about every <b>{formatWithUnit(opt.interval, ut)}</b>
                {result.saving_pct != null && (
                  <>. That lowers the long-run cost rate by <b>{result.saving_pct.toFixed(0)}%</b> versus
                    repairs only</>
                )}.
              </>
            }
            stats={[
              { label: "Overhaul every", value: `≈ ${formatWithUnit(opt.interval, ut)}` },
              result.saving_pct != null && { label: "Saves", value: `${result.saving_pct.toFixed(0)}%`, hint: "versus repairs only" },
              { label: "Repairs between overhauls", value: `≈ ${formatNumber(opt.expected_failures_per_cycle)}` },
            ]}
          />
          {plot}
          <ResultDetails
            rows={[
              { label: "Cost rate at the optimum", value: formatNumber(opt.cost_rate, { sig: 4 }) },
              {
                label: `Repairs only (to ${formatWithUnit(none?.horizon, ut)})`,
                value: formatNumber(none?.cost_rate, { sig: 4 }),
              },
            ]}
          >
            <p className="rs-note">Cost rates are long-run costs per unit time, in the currency of the costs.</p>
          </ResultDetails>
        </>
      )}
    </div>
  );
}
