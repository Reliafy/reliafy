import { useState } from "react";
import Plot from "react-plotly.js";
import CompareModal from "./CompareModal.jsx";
import { compareModels } from "../api.js";

const COLORS = ["#0284c7", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];

const fmt = (v) =>
  v == null
    ? "—"
    : Math.abs(v) >= 1e-4 || v === 0
    ? Number(v).toPrecision(5)
    : Number(v).toExponential(3);

const fmt1 = (v) => (v == null ? "—" : Number(v).toFixed(1));

const gofVal = (m, id) => {
  const g = (m.gof || []).find((x) => x.id === id);
  return g ? g.value : null;
};

// Model comparison tool: overlay every fitted distribution on the empirical
// (non-parametric) estimate and rank them, with decision metrics.
export default function ModelComparison() {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoError, setDemoError] = useState(null);

  const runDemo = async () => {
    setDemoBusy(true);
    setDemoError(null);
    try {
      // The seeded bearing-fatigue sample: one 'hours' column of failure times.
      setResult(await compareModels(null, { x: "hours" }, "hours", "sample-ds-bearings"));
    } catch (err) {
      setDemoError(err.message);
    } finally {
      setDemoBusy(false);
    }
  };
  const [fn, setFn] = useState("sf"); // sf | ff

  const unit = result?.unit;
  const axisLabel = fn === "sf" ? "Reliability, R(t)" : "Unreliability, F(t)";
  const tLabel = unit ? `t (${unit})` : "t";

  let traces = [];
  if (result) {
    traces = result.models.map((m, i) => ({
      x: result.time,
      y: fn === "sf" ? m.sf : m.sf.map((v) => (v == null ? null : 1 - v)),
      mode: "lines",
      line: {
        color: COLORS[i % COLORS.length],
        width: m.id === result.best_id ? 3 : 1.5,
        dash: m.id === result.best_id ? "solid" : "dot",
      },
      name: m.name + (m.id === result.best_id ? " (best)" : ""),
      type: "scatter",
      connectgaps: false,
    }));
    const emp = result.empirical || { x: [], R: [] };
    traces.push({
      x: emp.x,
      y: fn === "sf" ? emp.R : emp.R.map((v) => (v == null ? null : 1 - v)),
      mode: "markers",
      marker: { color: "#0f172a", size: 5, opacity: 0.55 },
      name: "Empirical (Kaplan–Meier)",
      type: "scatter",
    });
  }

  const layout = {
    autosize: true,
    height: 420,
    margin: { l: 64, r: 20, t: 20, b: 70 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: true,
    legend: { orientation: "h", y: -0.2 },
    xaxis: { title: { text: tLabel, standoff: 12 }, gridcolor: "#e2e8f0", zeroline: false },
    yaxis: {
      title: { text: axisLabel, standoff: 12 },
      gridcolor: "#e2e8f0",
      range: [0, 1.02],
      zeroline: false,
    },
  };

  return (
    <div className="strategy-tool">
      <div className="strategy-actions">
        <button onClick={() => setOpen(true)}>
          {result ? "Compare another dataset" : "Compare a dataset"}
        </button>
      </div>

      {result && (
        <>
          <div className="strategy-reco">
            <span className="strategy-reco-icon">★</span>
            <span>
              {result.recommendation} <span className="muted-line">· {result.n} observations</span>
            </span>
          </div>

          <div className="seg" style={{ width: "fit-content", margin: "0.5rem 0 1rem" }}>
            <button
              className={"seg-btn" + (fn === "sf" ? " active" : "")}
              onClick={() => setFn("sf")}
            >
              R(t)
            </button>
            <button
              className={"seg-btn" + (fn === "ff" ? " active" : "")}
              onClick={() => setFn("ff")}
            >
              F(t)
            </button>
          </div>

          <Plot
            data={traces}
            layout={layout}
            config={{ displayModeBar: true, responsive: true }}
            style={{ width: "100%" }}
            useResizeHandler
          />

          <table className="calc-table strategy-table">
            <thead>
              <tr>
                <th>Distribution</th>
                <th>Parameters</th>
                <th title="Akaike information criterion (lower is better)">AIC</th>
                <th title="Bayesian information criterion (lower is better)">BIC</th>
                <th title="Time by which 10% have failed">B10 life</th>
                <th title="Median life (B50)">Median</th>
                <th title="Mean time to failure">MTTF</th>
              </tr>
            </thead>
            <tbody>
              {result.models.map((m) => (
                <tr key={m.id} className={m.id === result.best_id ? "strategy-best" : ""}>
                  <td className="calc-row-label">
                    {m.name}
                    {m.id === result.best_id ? " ★" : ""}
                  </td>
                  <td>
                    {m.params
                      .map((p) => `${p.name}=${fmt(p.value)}`)
                      .join(", ")}
                  </td>
                  <td>{fmt1(m.aic)}</td>
                  <td>{fmt1(gofVal(m, "bic"))}</td>
                  <td>{fmt1(m.metrics.b10)}</td>
                  <td>{fmt1(m.metrics.median)}</td>
                  <td>{fmt1(m.metrics.mttf)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {unit && <p className="muted-line">Life metrics in {unit}.</p>}
        </>
      )}

      {!result && (
        <p className="muted-line">
          No comparison yet — upload a dataset, or{" "}
          <button className="link-btn" onClick={runDemo} disabled={demoBusy}>
            {demoBusy ? "ranking…" : "try it on the bearing sample"}
          </button>
          .{demoError ? ` (${demoError})` : ""}
        </p>
      )}

      {open && (
        <CompareModal
          onClose={() => setOpen(false)}
          onCompared={(r) => {
            setResult(r);
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}
