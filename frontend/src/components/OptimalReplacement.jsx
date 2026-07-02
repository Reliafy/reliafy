import { useState } from "react";
import Plot from "react-plotly.js";
import ModelPicker from "./ModelPicker.jsx";
import { optimalReplacement } from "../api.js";

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

// Optimal preventive-replacement tool: the age that minimises the long-run
// cost rate given planned vs. unplanned costs.
export default function OptimalReplacement() {
  const [model, setModel] = useState(null);
  const [cp, setCp] = useState("");
  const [cu, setCu] = useState("");
  const [unit, setUnit] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const isRegression = model?.kind === "regression";
  const canRun =
    model && model.distribution_id && !isRegression && cp !== "" && cu !== "";

  const run = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await optimalReplacement(
        model.distribution_id,
        model.params,
        Number(cp),
        Number(cu),
        unit || model.unit
      );
      setResult(res);
    } catch (err) {
      setError(err.message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const u = result?.unit ? ` (${result.unit})` : "";

  let traces = [];
  let layout = {};
  if (result) {
    const c = result.curve;
    traces = [
      {
        x: c.t,
        y: c.cost_rate,
        mode: "lines",
        line: { color: "#0284c7", width: 2.5 },
        name: "Cost rate",
        type: "scatter",
        connectgaps: false,
      },
    ];
    if (result.run_to_failure_cost_rate != null) {
      traces.push({
        x: [c.t[0], c.t[c.t.length - 1]],
        y: [result.run_to_failure_cost_rate, result.run_to_failure_cost_rate],
        mode: "lines",
        line: { color: "#94a3b8", width: 1.5, dash: "dash" },
        name: "Run-to-failure",
        type: "scatter",
      });
    }
    if (result.optimal_time != null && result.optimal_cost_rate != null) {
      traces.push({
        x: [result.optimal_time],
        y: [result.optimal_cost_rate],
        mode: "markers",
        marker: { color: "#16a34a", size: 11, symbol: "diamond" },
        name: "Optimum",
        type: "scatter",
      });
    }
    const yMax = result.run_to_failure_cost_rate
      ? result.run_to_failure_cost_rate * 2.5
      : undefined;
    layout = {
      autosize: true,
      height: 400,
      margin: { l: 70, r: 20, t: 20, b: 60 },
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#ffffff",
      font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
      showlegend: true,
      legend: { orientation: "h", y: -0.2 },
      xaxis: {
        title: { text: `replacement age${u}`, standoff: 12 },
        gridcolor: "#e2e8f0",
        zeroline: false,
      },
      yaxis: {
        title: { text: "long-run cost per unit time", standoff: 12 },
        gridcolor: "#e2e8f0",
        rangemode: "tozero",
        range: yMax ? [0, yMax] : undefined,
        zeroline: false,
      },
    };
  }

  return (
    <div className="strategy-tool">
      <div className="strategy-form">
        <ModelPicker label="Life model" value={model} onChange={setModel} />
        {isRegression && (
          <p className="hint">
            Pick a plain distribution — proportional-hazards models aren't
            supported here.
          </p>
        )}
        <div className="strategy-costs">
          <label className="calc-t">
            <span>Planned replacement cost</span>
            <input
              type="number"
              min="0"
              step="any"
              value={cp}
              onChange={(e) => setCp(e.target.value)}
            />
          </label>
          <label className="calc-t">
            <span>Unplanned (failure) cost</span>
            <input
              type="number"
              min="0"
              step="any"
              value={cu}
              onChange={(e) => setCu(e.target.value)}
            />
          </label>
          <label className="calc-t">
            <span>Unit (optional)</span>
            <input
              type="text"
              placeholder="e.g. Hours"
              value={unit}
              onChange={(e) => setUnit(e.target.value)}
            />
          </label>
          <button onClick={run} disabled={!canRun || loading}>
            {loading ? "Computing…" : "Compute"}
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {result && (
        <>
          <div
            className={
              "strategy-reco " + (result.beneficial ? "" : "strategy-reco-warn")
            }
          >
            <span className="strategy-reco-icon">{result.beneficial ? "✓" : "ⓘ"}</span>
            <span>{result.recommendation}</span>
          </div>

          <div className="params">
            <div className="stat">
              <div className="value">
                {result.optimal_time == null ? "—" : fmt(result.optimal_time)}
              </div>
              <div className="name">optimal age{u}</div>
            </div>
            <div className="stat">
              <div className="value">
                {result.beneficial ? `${(result.savings * 100).toFixed(0)}%` : "0%"}
              </div>
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

          <Plot
            data={traces}
            layout={layout}
            config={{ displayModeBar: true, responsive: true }}
            style={{ width: "100%" }}
            useResizeHandler
          />
        </>
      )}
    </div>
  );
}
