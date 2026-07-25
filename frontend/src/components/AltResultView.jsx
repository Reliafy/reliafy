import { useState } from "react";
import Plot from "react-plotly.js";
import AltCalculator from "./AltCalculator.jsx";

const fmt = (v, d = 4) =>
  v === null || v === undefined || !Number.isFinite(v)
    ? "—"
    : Number(v).toLocaleString(undefined, { maximumSignificantDigits: d });

// Palette for the per-secondary-stress series (two-stress models).
const SERIES = ["#2f6df6", "#d0762f", "#2faa6a", "#a05ad0", "#d05a5a", "#0f9ab0"];

// A fitted Accelerated Life model, laid out like the other result views: a
// tabbed panel with the life-vs-stress plot (the ALT signature — characteristic
// life against stress, with the fitted line through each tested level), a
// use-level calculator (only once saved, so it can hit the evaluate endpoint),
// and a coefficients/fit detail tab.
export default function AltResultView({ results, modelId }) {
  const r = results || {};
  const plot = r.life_stress_plot || {};
  const twoStress = (r.stresses || []).length > 1;
  const [tab, setTab] = useState("plot");

  const traces = [];
  (plot.lines || []).forEach((ln, i) => {
    const color = SERIES[i % SERIES.length];
    traces.push({
      x: ln.stress, y: ln.life, mode: "lines", type: "scatter",
      line: { color, width: 2 },
      name: twoStress ? `${plot.secondary_label} = ${fmt(ln.secondary, 3)}` : "Fitted",
      legendgroup: `g${i}`,
    });
  });
  // Tested-level points, coloured to match their series.
  const secLevels = twoStress
    ? [...new Set((plot.lines || []).map((l) => l.secondary))]
    : [null];
  (plot.points || []).forEach((p) => {
    const idx = twoStress ? Math.max(0, secLevels.indexOf(p.secondary)) : 0;
    traces.push({
      x: [p.stress], y: [p.life], mode: "markers", type: "scatter",
      marker: { color: SERIES[idx % SERIES.length], size: 9, symbol: "diamond",
                line: { color: "#fff", width: 1 } },
      name: "Tested level", legendgroup: `g${idx}`, showlegend: false,
      hovertemplate: `${plot.x_label}: %{x}<br>Characteristic life: %{y:.4g}<extra></extra>`,
    });
  });

  const layout = {
    autosize: true, height: 420,
    margin: { l: 70, r: 20, t: 20, b: 55 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
    xaxis: { title: plot.x_label || "Stress", zeroline: false, gridcolor: "#eef1f5" },
    yaxis: {
      title: `${plot.y_label || "Characteristic life"}${r.unit ? ` (${r.unit})` : ""}`,
      type: plot.log_y ? "log" : "linear", gridcolor: "#eef1f5",
    },
    legend: { orientation: "h", y: -0.18 },
    showlegend: twoStress,
  };

  const prob = r.probability_plot || null;
  const TABS = [
    { id: "plot", label: "Life–stress" },
    ...(prob ? [{ id: "prob", label: "Probability plot" }] : []),
    ...(modelId ? [{ id: "calc", label: "Use-level calculator" }] : []),
    { id: "detail", label: "Coefficients & fit" },
  ];

  return (
    <div className="alt-result">
      <div className="seg" style={{ alignSelf: "flex-start" }}>
        {TABS.map((t) => (
          <button key={t.id} className={"seg-btn" + (tab === t.id ? " active" : "")}
                  onClick={() => setTab(t.id)}>{t.label}</button>
        ))}
      </div>

      {tab === "plot" && (
        <div className="alt-plot-wrap">
          <Plot data={traces} layout={layout} useResizeHandler style={{ width: "100%" }}
                config={{ displayModeBar: false, responsive: true }} />
          <p className="muted-line" style={{ margin: 0 }}>
            Each diamond is a tested stress level; the line is the fitted
            life-stress relationship, extended below the lowest test stress toward
            your use level. {plot.log_y ? "The life axis is logarithmic." : ""}
          </p>
        </div>
      )}

      {tab === "prob" && prob && <ProbabilityPanel prob={prob} unit={r.unit} twoStress={twoStress} />}

      {tab === "calc" && modelId && (
        <AltCalculator modelId={modelId} results={r} />
      )}

      {tab === "detail" && (
        <div className="alt-detail">
          <div className="alt-cols">
            <div>
              <div className="ds-section-h">Distribution</div>
              <p className="muted-line">{r.distribution} · {r.life_model} life-stress model · n = {r.n}</p>
              <table className="mini-table">
                <tbody>
                  {(r.params || []).map((p) => (
                    <tr key={p.name}><td>{p.name}</td><td>{fmt(p.value)}</td></tr>
                  ))}
                  {(r.coefficients || []).map((c) => (
                    <tr key={c.name}><td>{c.name} <span className="muted">(life-stress)</span></td><td>{fmt(c.value)}</td></tr>
                  ))}
                </tbody>
              </table>
              {(r.gof || []).length > 0 && (
                <p className="muted-line" style={{ marginBottom: 0 }}>
                  {r.gof.map((g) => `${g.label} ${fmt(g.value, 5)}`).join(" · ")}
                </p>
              )}
            </div>
            <div>
              <div className="ds-section-h">Fitted life at each tested level</div>
              <table className="mini-table">
                <thead>
                  <tr>
                    {(r.stresses || []).map((s) => <th key={s.key}>{s.label}</th>)}
                    <th>n</th><th>Characteristic life{r.unit ? ` (${r.unit})` : ""}</th>
                  </tr>
                </thead>
                <tbody>
                  {(r.levels || []).map((lvl, i) => (
                    <tr key={i}>
                      {lvl.stress.map((v, j) => <td key={j}>{fmt(v, 5)}</td>)}
                      <td>{lvl.n}</td><td>{fmt(lvl.characteristic_life)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// Per-stress-level probability plot: each level's failure points on the
// distribution's probability paper, with its fitted CDF line. Data is already
// linearised server-side, so the axes are plain — a good fit shows parallel
// straight lines (common shape) with the points hugging them.
function ProbabilityPanel({ prob, unit, twoStress }) {
  const traces = [];
  (prob.series || []).forEach((s, i) => {
    const color = SERIES[i % SERIES.length];
    if (s.line) {
      traces.push({
        x: s.line.x, y: s.line.y, mode: "lines", type: "scatter",
        line: { color, width: 2 }, name: s.label, legendgroup: `p${i}`,
      });
    }
    if (s.scatter) {
      traces.push({
        x: s.scatter.x, y: s.scatter.y, mode: "markers", type: "scatter",
        marker: { color, size: 6, line: { color: "#fff", width: 0.5 } },
        name: s.label, legendgroup: `p${i}`, showlegend: !s.line,
        hovertemplate: `${s.label}<extra></extra>`,
      });
    }
  });

  const layout = {
    autosize: true, height: 440,
    margin: { l: 62, r: 20, t: 20, b: 50 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
    xaxis: {
      title: unit ? `Time (${unit})` : "Time",
      tickvals: prob.x_ticks?.vals, ticktext: prob.x_ticks?.labels,
      gridcolor: "#eef1f5", zeroline: false,
    },
    yaxis: {
      title: "Unreliability, F(t)",
      tickvals: prob.y_ticks?.vals, ticktext: prob.y_ticks?.labels,
      gridcolor: "#eef1f5", zeroline: false,
    },
    legend: { orientation: "h", y: -0.16 },
  };

  return (
    <div className="alt-plot-wrap">
      <Plot data={traces} layout={layout} useResizeHandler style={{ width: "100%" }}
            config={{ displayModeBar: false, responsive: true }} />
      <p className="muted-line" style={{ margin: 0 }}>
        Each colour is a tested stress level: points are the observed failures on
        {" "}{prob.distribution} probability paper, the line is the model's fit for
        that level. A good fit shows the points tracking parallel straight lines
        (a shared shape across stresses).
      </p>
    </div>
  );
}
