import Plot from "react-plotly.js";

// Instrument-ish categorical palette for per-item traces.
const COLORS = [
  "#2f6df6", "#e58e26", "#2faa6a", "#a15af0", "#d05a5a",
  "#22a6b3", "#b8860b", "#6c727c", "#e056a5", "#4a69bd",
];

const fmt = (v, digits = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

// The fitted degradation model: per-item measurement paths + fitted lines
// against the failure threshold, plus the derived life model and diagnostics.
export default function DegradationResultView({ results }) {
  const r = results || {};
  const units = r.units || [];
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const yTitle = r.measurement_unit ? `Measurement (${r.measurement_unit})` : "Measurement";

  const traces = [];
  units.forEach((u, idx) => {
    const color = COLORS[idx % COLORS.length];
    traces.push({
      x: u.line.x, y: u.line.y, mode: "lines", type: "scatter",
      line: { color, width: 1.6 }, name: u.id, legendgroup: u.id,
      hoverinfo: "skip", showlegend: false,
    });
    traces.push({
      x: u.scatter.x, y: u.scatter.y, mode: "markers", type: "scatter",
      marker: { color, size: 6, line: { color: "#fff", width: 1 } },
      name: u.id, legendgroup: u.id,
    });
  });

  const layout = {
    autosize: true,
    height: 440,
    margin: { l: 60, r: 20, t: 20, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#6c727c", family: "IBM Plex Mono, monospace", size: 11 },
    legend: { orientation: "h", y: -0.18 },
    xaxis: { title: { text: xTitle, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false },
    yaxis: { title: { text: yTitle, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false },
    shapes: [{
      type: "line", xref: "paper", x0: 0, x1: 1, y0: r.threshold, y1: r.threshold,
      line: { color: "#d05a5a", width: 1.6, dash: "dash" },
    }],
    annotations: [{
      xref: "paper", x: 1, y: r.threshold, xanchor: "right", yanchor: "bottom",
      text: `threshold ${fmt(r.threshold)}${r.measurement_unit ? " " + r.measurement_unit : ""}`,
      showarrow: false, font: { color: "#d05a5a", size: 11 },
    }],
  };

  const life = r.life_model || {};

  return (
    <>
      <div className="stats">
        <div className="stat"><div className="k">Path model</div><div className="v sm">{r.path_model?.name || "—"}</div></div>
        <div className="stat"><div className="k">Items</div><div className="v">{r.n_units ?? "—"}</div></div>
        <div className="stat"><div className="k">Threshold</div><div className="v sm">{fmt(r.threshold)}{r.measurement_unit ? ` ${r.measurement_unit}` : ""}</div></div>
        <div className="stat"><div className="k">Mean life</div><div className="v sm">{fmt(life.mean, 0)}{r.unit ? ` ${r.unit}` : ""}</div></div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <Plot data={traces} layout={layout} config={{ displayModeBar: true, responsive: true }} style={{ width: "100%" }} useResizeHandler />
      </div>

      <div className="row" style={{ gap: "1rem", alignItems: "flex-start", marginTop: "1rem" }}>
        <div className="card" style={{ flex: 1 }}>
          <h2 style={{ marginTop: 0 }}>Pseudo failure times</h2>
          <p className="muted-line">When each item's fitted path crosses the threshold. The life model is fitted to these.</p>
          <table className="lib-table">
            <thead><tr><th>Item</th><th>Crossing{r.unit ? ` (${r.unit})` : ""}</th><th /></tr></thead>
            <tbody>
              {units.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td className="lib-n">{u.pseudo_failure_time === null ? "never (censored)" : fmt(u.pseudo_failure_time, 0)}</td>
                  <td className="lib-date">{u.censored ? "censored" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="card" style={{ flex: 1 }}>
          <h2 style={{ marginTop: 0 }}>Life model</h2>
          <p className="muted-line">
            {life.distribution || "—"} fitted to the pseudo failure times.
          </p>
          <table className="lib-table">
            <tbody>
              {(life.params || []).map((p) => (
                <tr key={p.name}><td className="mono">{p.name}</td><td className="lib-n">{fmt(p.value, 3)}</td></tr>
              ))}
              <tr><td className="mono">mean</td><td className="lib-n">{fmt(life.mean, 1)}</td></tr>
            </tbody>
          </table>

          {r.path_selection && (
            <>
              <h2 style={{ marginTop: "1.2rem" }}>Path selection (AICc)</h2>
              <table className="lib-table">
                <tbody>
                  {r.path_selection.slice(0, 5).map((row, i) => (
                    <tr key={row.id}>
                      <td className="mono">{row.name || row.id}{i === 0 ? " ✓" : ""}</td>
                      <td className="lib-n">{fmt(row.aicc, 1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>
    </>
  );
}
