import { useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { recurrentOverhaul } from "../api.js";
import { unitInText } from "./unitText.js";
import { PlotCard, PlotPanel } from "./model/ModelLayouts.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { formatNumber, formatWithUnit } from "../format.js";

// Optimal overhaul interval for a saved recurrent model: minimal repair between
// overhauls, an overhaul renews the system. Minimises the long-run cost rate
// (cr·Λ(T) + co) / T server-side (RePyability's Repairable). Styled like the
// Strategy › Optimal replacement tool: the answer first (#311), the cost-rate
// curve, the cost rates under Details. Laid out for the model frame's Plan
// ahead tab: the curve fills the tab, the costs and the answer beside it.
export default function RecurrentOverhaul({ modelId, unit: rawUnit, name = null }) {
  const unit = rawUnit ? String(rawUnit).toLowerCase() : rawUnit;
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
      xaxis: { title: { text: `Overhaul interval${u}` } },
      yaxis: { title: { text: "Long-run cost per unit time" }, rangemode: "tozero", range: [0, opt.cost_rate * 2.5] },
      shapes: [referenceShape({ x: opt.interval, line: { dash: "dot" } })],
    };
    plot = <Plot fill data={traces} layout={layout} download={`${name || "Recurrent model"} — overhaul cost rate`} />;
  }

  return (
    <PlotPanel
      className="rec-plan-panel"
      sideClassName="rec-plan-side"
      plot={
        <PlotCard title="Long-run cost rate against the overhaul interval">
          {plot || (
            <div className="rec-plan-empty">
              <p className="muted-line">
                {result && !opt ? result.reason : "Enter the cost of a repair and of an overhaul to see the cost rate at each interval and the cheapest one."}
              </p>
            </div>
          )}
        </PlotCard>
      }
      side={
        <>
          <section className="gof-card mf-flex-none rec-plan-form" aria-labelledby="oh-title">
            <div className="gofh"><h3 className="mf-card-title" id="oh-title">Optimal overhaul interval</h3></div>
            <p className="mf-note">Minimal repair between overhauls; an overhaul makes the system as good as new.</p>
            <div className="rec-oh-inputs">
              <label className="calc-t">
                <span>Repair cost (per failure)</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={cr} onChange={(e) => setCr(e.target.value)} />
              </label>
              <label className="calc-t">
                <span>Overhaul cost</span>
                <input type="number" inputMode="decimal" min="0" step="any" value={co} onChange={(e) => setCo(e.target.value)} />
              </label>
              <p className="rs-note">Same currency for both.</p>
              <button onClick={run} disabled={!canRun || loading}>
                {loading ? "Calculating…" : "Calculate"}
              </button>
            </div>
          </section>

          {error && <div className="error" role="alert">{error}</div>}

          {opt && (
            <>
              <ResultSummary
                tone={result.saving_pct > 0 ? "good" : "neutral"}
                sentence={
                  <>
                    Overhaul about every <b>{formatWithUnit(opt.interval, ut)}</b>
                    {result.saving_pct != null && (
                      <>. That lowers the long-run cost rate by <b>{result.saving_pct.toFixed(0)}%</b> against
                        repairs only</>
                    )}.
                  </>
                }
                stats={[
                  { label: "Repairs between overhauls", value: `≈ ${formatNumber(opt.expected_failures_per_cycle)}` },
                ]}
              />
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
        </>
      }
    />
  );
}
