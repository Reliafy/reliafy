import Plot from "react-plotly.js";

const fmt = (v, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

const GROWTH = {
  improving: { label: "Improving", note: "failures are slowing (β < 1)", cls: "health-green" },
  stable: { label: "Stable", note: "roughly constant rate (β ≈ 1)", cls: "health-grey" },
  deteriorating: { label: "Deteriorating", note: "failures are accelerating (β > 1)", cls: "health-red" },
};

// A fitted recurrent-event (repairable-system) model: the mean cumulative
// function (observed step + confidence band + fitted curve), the reliability-
// growth verdict from the Crow-AMSAA shape, ROCOF/MTBF, and the trend test.
export default function RecurrentResultView({ results }) {
  const r = results || {};
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
  traces.push({
    x: obs.x, y: obs.mcf, mode: "lines+markers", type: "scatter",
    line: { color: "#6c727c", width: 1.4, shape: "hv" },
    marker: { color: "#6c727c", size: 5 }, name: "observed (MCF)",
  });
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
      <div className="stats">
        <div className="stat"><div className="k">Systems</div><div className="v">{r.n_systems ?? "—"}</div></div>
        <div className="stat"><div className="k">Failures</div><div className="v">{r.n_events ?? "—"}</div></div>
        <div className="stat">
          <div className="k">Reliability growth</div>
          <div className="v sm">
            {growth ? <span className={`health-badge ${growth.cls}`}>{growth.label}</span> : "—"}
          </div>
        </div>
        <div className="stat"><div className="k">Current MTBF</div><div className="v sm">{fmt(r.mtbf, 1)}{unit}</div></div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <Plot data={traces} layout={layout} config={{ displayModeBar: true, responsive: true }} style={{ width: "100%" }} useResizeHandler />
      </div>

      <div className="row" style={{ gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
        <div className="card" style={{ flex: 1 }}>
          <h2 style={{ marginTop: 0 }}>{r.model?.name || "Model"}</h2>
          {growth && (
            <p className="muted-line" style={{ marginTop: 0 }}>
              <b>{growth.label}</b> — {growth.note}. Current rate of occurrence of
              failures (ROCOF): {fmt(r.rocof, 5)} per{unit || " unit"}.
            </p>
          )}
          <table className="lib-table">
            <tbody>
              {(r.params || []).map((p) => (
                <tr key={p.name}><td className="mono">{p.name}</td><td className="lib-n">{fmt(p.value, 3)}</td></tr>
              ))}
              {r.beta != null && <tr><td className="mono">β (shape)</td><td className="lib-n">{fmt(r.beta, 3)}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card" style={{ flex: 1 }}>
          <h2 style={{ marginTop: 0 }}>Trend test</h2>
          {trendText ? <p className="muted-line">{trendText}</p> : <p className="muted-line">—</p>}
          {(r.gof || []).length > 0 && (
            <table className="lib-table">
              <tbody>
                {r.gof.map((g) => (
                  <tr key={g.id}><td className="mono">{g.label}</td><td className="lib-n">{fmt(g.value, 2)}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}
