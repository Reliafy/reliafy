import { useState } from "react";
import Plot from "react-plotly.js";
import { recurrentOverhaul } from "../api.js";

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
export default function RecurrentOverhaul({ modelId, unit }) {
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
      { x: c.t, y: c.cost_rate, mode: "lines", type: "scatter", name: "Cost rate",
        line: { color: "#0284c7", width: 2.5 }, connectgaps: false },
      { x: [opt.interval], y: [opt.cost_rate], mode: "markers", type: "scatter", name: "Optimum T*",
        marker: { color: "#16a34a", size: 11, symbol: "diamond" } },
    ];
    const layout = {
      autosize: true, height: 380, margin: { l: 70, r: 20, t: 20, b: 60 },
      paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
      font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
      showlegend: true, legend: { orientation: "h", y: -0.2 },
      xaxis: { title: { text: `overhaul interval${u}`, standoff: 12 }, gridcolor: "#e2e8f0", zeroline: false },
      yaxis: { title: { text: "long-run cost per unit time", standoff: 12 }, gridcolor: "#e2e8f0",
        rangemode: "tozero", range: [0, opt.cost_rate * 2.5], zeroline: false },
      shapes: [{ type: "line", x0: opt.interval, x1: opt.interval, yref: "paper", y0: 0, y1: 1,
        line: { color: "#16a34a", width: 1, dash: "dot" } }],
    };
    plot = <Plot data={traces} layout={layout} config={{ displayModeBar: true, responsive: true }}
                 style={{ width: "100%" }} useResizeHandler />;
  }

  return (
    <div className="strategy-tool">
      <div className="gofh">Optimal overhaul interval</div>
      <p className="muted-line" style={{ margin: "0.3rem 0 0.6rem" }}>
        Minimal repair between overhauls; an overhaul restores the system to as-good-as-new.
      </p>
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
              Overhaul every <b>{fmt(opt.interval)}{unit ? ` ${unit}` : ""}</b> — about{" "}
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
              <div className="name">no overhaul (repairs only, to {fmt(none?.horizon)}{unit ? ` ${unit}` : ""})</div>
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
