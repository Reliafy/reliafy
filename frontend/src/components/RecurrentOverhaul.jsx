import { useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { recurrentOverhaul } from "../api.js";
import { unitInText } from "./unitText.js";
import { CardHeader } from "./ui/Card.jsx";

const fmt = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

// Optimal overhaul interval for a saved recurrent model: minimal repair between
// overhauls, an overhaul renews the system. Minimises the long-run cost rate
// (cr·Λ(T) + co) / T server-side (RePyability's Repairable). Styled like the
// Strategy › Optimal replacement tool.
export default function RecurrentOverhaul({ modelId, unit, name = null }) {
  const [cr, setCr] = useState("");
  const [co, setCo] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const u = unit ? ` (${unit})` : "";

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
      optimumMarker({ x: [opt.interval], y: [opt.cost_rate], name: "Optimum T*", text: [`T* ${fmt(opt.interval)}`] }),
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

      {result && !opt && (
        <div className="strategy-reco strategy-reco-warn">
          <span className="strategy-reco-icon">ⓘ</span>
          <span>{result.reason}</span>
        </div>
      )}

      {opt && (
        <>
          <div className="strategy-reco">
            <span className="strategy-reco-icon">✓</span>
            <span>
              Overhaul every <b>{fmt(opt.interval)}{unit ? ` ${unitInText(unit)}` : ""}</b> — about{" "}
              {fmt(opt.expected_failures_per_cycle)} repairs expected between overhauls.
            </span>
          </div>
          <div className="params">
            <div className="stat">
              <div className="value">{fmt(opt.interval)}</div>
              <div className="name">optimal interval T*{u}</div>
            </div>
            <div className="stat">
              <div className="value">{fmt(opt.cost_rate)}</div>
              <div className="name">cost rate at T*</div>
            </div>
            <div className="stat">
              <div className="value">{fmt(none?.cost_rate)}</div>
              <div className="name">no overhaul (repairs only, to {fmt(none?.horizon)}{unit ? ` ${unitInText(unit)}` : ""})</div>
            </div>
            <div className="stat">
              <div className="value">{result.saving_pct == null ? "—" : `${result.saving_pct.toFixed(0)}%`}</div>
              <div className="name">saving vs. no overhaul</div>
            </div>
          </div>
          {plot}
        </>
      )}
    </div>
  );
}
