import { useState } from "react";
import Plot from "react-plotly.js";
import RecurrentCalculator from "./RecurrentCalculator.jsx";

const fmt = (v, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

const GROWTH = {
  improving: { label: "Improving", note: "failures are slowing (β < 1)", cls: "health-green" },
  stable: { label: "Stable", note: "roughly constant rate (β ≈ 1)", cls: "health-grey" },
  deteriorating: { label: "Deteriorating", note: "failures are accelerating (β > 1)", cls: "health-red" },
};

const TABS = [
  { id: "mcf", label: "MCF plot" },
  { id: "calc", label: "Calculator" },
  { id: "detail", label: "Trend & fit" },
];

// A fitted recurrent-event (repairable-system) model, laid out like the life-
// data result view: a tabbed panel with the mean-cumulative-function plot (plus
// a parameter side-rail) and a "Trend & fit" detail tab, and a growth verdict
// footer. Handles both data fits and models built from parameters (no observed
// step / trend test).
export default function RecurrentResultView({ results }) {
  const r = results || {};
  const [tab, setTab] = useState("mcf");
  const unit = r.unit ? ` ${r.unit}` : "";
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const obs = r.mcf?.observed || {};
  const fit = r.mcf?.fitted || {};
  const growth = GROWTH[r.growth] || null;

  const traces = [];
  if (obs.lower && obs.upper) {
    traces.push({
      x: [...obs.x, ...[...obs.x].reverse()],
      y: [...obs.upper, ...[...obs.lower].reverse()],
      fill: "toself", fillcolor: "rgba(108,114,124,0.12)", line: { width: 0 },
      hoverinfo: "skip", name: "95% band", type: "scatter",
    });
  }
  if (obs.x?.length) {
    traces.push({
      x: obs.x, y: obs.mcf, mode: "lines+markers", type: "scatter",
      line: { color: "#6c727c", width: 1.4, shape: "hv" },
      marker: { color: "#6c727c", size: 5 }, name: "observed (MCF)",
    });
  }
  if (fit.x) {
    traces.push({
      x: fit.x, y: fit.mcf, mode: "lines", type: "scatter",
      line: { color: "#2f6df6", width: 2 }, name: `${r.model?.name || "fitted"}`,
    });
  }

  const layout = {
    autosize: true, height: 420,
    margin: { l: 60, r: 20, t: 20, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
    font: { color: "#6c727c", family: "IBM Plex Mono, monospace", size: 11 },
    legend: { orientation: "h", y: -0.18 },
    xaxis: { title: { text: xTitle, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures (MCF)", standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
  };

  const t = r.trend;
  const trendText = t
    ? (t.trend === "no trend" || !t.significant
        ? "No significant trend — consistent with a constant failure rate."
        : `Significant ${t.trend} trend (${t.test}, p = ${fmt(t.p_value, 3)}).`)
    : null;

  return (
    <>
      <div className="tabs">
        {TABS.map((tb) => (
          <button
            key={tb.id}
            className={"tab" + (tab === tb.id ? " active" : "")}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      <div className="tab-panel">
        {tab === "mcf" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <div className="plottitle">{r.model?.name || "Recurrent"} — mean cumulative function</div>
              <Plot data={traces} layout={layout} config={{ displayModeBar: true, responsive: true }} style={{ width: "100%" }} useResizeHandler />
            </div>
            <div className="aside">
              {(r.params || []).length > 0 && (
                <div className="gof-card">
                  <div className="gofh">Parameters</div>
                  {r.params.map((p) => (
                    <div className="gofr" key={p.name}>
                      <span className="gk">{p.name}</span>
                      <span className="gv">{fmt(p.value, 3)}</span>
                    </div>
                  ))}
                  {r.beta != null && (
                    <div className="gofr"><span className="gk">β (shape)</span><span className="gv">{fmt(r.beta, 3)}</span></div>
                  )}
                </div>
              )}
              <div className="detail-note">
                {r.n_systems != null
                  ? <>Fitted to <b>{r.n_events} events</b> across {r.n_systems} systems. The step is the observed MCF (95% band); the line is the fitted {r.model?.name || "model"}.</>
                  : <>Built from parameters — the line is the fitted {r.model?.name || "model"}; there's no observed data.</>}
              </div>
            </div>
          </div>
        )}

        {tab === "calc" && <RecurrentCalculator r={r} />}

        {tab === "detail" && (
          <div className="detail-panel" style={{ flexWrap: "wrap", alignItems: "flex-start" }}>
            <div className="gof-card" style={{ flex: "1 1 220px" }}>
              <div className="gofh">Rates</div>
              <div className="gofr">
                <span className="gk">Reliability growth</span>
                <span className="gv">{growth ? <span className={`health-badge ${growth.cls}`}>{growth.label}</span> : "—"}</span>
              </div>
              <div className="gofr"><span className="gk">Current MTBF</span><span className="gv">{fmt(r.mtbf, 1)}{unit}</span></div>
              <div className="gofr"><span className="gk">ROCOF</span><span className="gv">{fmt(r.rocof, 5)}</span></div>
              {r.n_systems != null && (
                <div className="gofr"><span className="gk">Systems / failures</span><span className="gv">{r.n_systems} / {r.n_events}</span></div>
              )}
            </div>
            <div className="gof-card" style={{ flex: "1 1 220px" }}>
              <div className="gofh">Trend test</div>
              <div className="detail-note" style={{ margin: 0, padding: "11px 16px" }}>
                {trendText || "Not available for a model built from parameters — the trend test needs event data."}
              </div>
            </div>
            {(r.gof || []).length > 0 && (
              <div className="gof-card" style={{ flex: "1 1 220px" }}>
                <div className="gofh">Goodness of fit</div>
                {r.gof.map((g) => (
                  <div className="gofr" key={g.id}><span className="gk">{g.label}</span><span className="gv">{fmt(g.value, 2)}</span></div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {growth && (
        <div className="result-foot">
          <p className="verdict-line">
            <b>{growth.label}</b> — {growth.note}. Current ROCOF {fmt(r.rocof, 5)} per{unit || " unit"}
            {r.mtbf != null ? `, MTBF ≈ ${fmt(r.mtbf, 1)}${unit}` : ""}.
          </p>
        </div>
      )}
    </>
  );
}
