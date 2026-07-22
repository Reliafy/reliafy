import { useState } from "react";
import Plot from "react-plotly.js";

// Recurrent-event calculator: read off the repairable-system functions at a
// chosen time — expected cumulative failures N(t), the rate of occurrence of
// failures ROCOF(t), and the instantaneous MTBF(t) — plus the expected number
// of failures in a window. The power-law form (Crow-AMSAA / Duane) is evaluated
// analytically from α, β; otherwise the fitted MCF curve is interpolated. Mirrors
// the life-data Calculator's layout (segmented function picker + evaluate-at-t).
const FUNCS = [
  { id: "N", label: "Expected cumulative failures N(t)", y: "Expected cumulative failures" },
  { id: "rocof", label: "Rate of occurrence of failures", y: "ROCOF" },
  { id: "mtbf", label: "Mean time between failures", y: "MTBF" },
];

const fmt = (v) =>
  v == null || !Number.isFinite(v) ? "—" : Math.abs(v) >= 1e-4 || v === 0 ? Number(v).toPrecision(5) : Number(v).toExponential(3);

function interp(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1], y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1], x1 = x[i];
      return y0 + (x1 === x0 ? 0 : (xq - x0) / (x1 - x0)) * (y1 - y0);
    }
  }
  return null;
}

export default function RecurrentCalculator({ r }) {
  const unit = r.unit || "";
  const tLabel = unit ? `t (${unit})` : "t";
  const fitted = r.mcf?.fitted || {};
  const byName = Object.fromEntries((r.params || []).map((p) => [p.name, p.value]));
  const alpha = byName.alpha;
  const beta = byName.beta ?? r.beta;
  const analytic = alpha > 0 && beta != null; // power-law: N(t) = (t/α)^β

  const gridMax = (fitted.x?.length ? fitted.x[fitted.x.length - 1] : 0) || 1;
  const [t, setT] = useState(Number((gridMax / 2).toPrecision(4)) || 0);
  const [from, setFrom] = useState("");
  const [active, setActive] = useState("N");

  const nt = Number(t);
  const tMax = Math.max(gridMax, (Number.isFinite(nt) ? nt : 0) * 1.05) || 1;

  // Point evaluators.
  const mcfAt = (tv) => (analytic ? Math.pow(tv / alpha, beta) : interp(fitted.x, fitted.mcf, tv));
  const rocofAt = (tv) => {
    if (analytic) return tv > 0 ? (beta / alpha) * Math.pow(tv / alpha, beta - 1) : (beta === 1 ? 1 / alpha : null);
    // Numeric slope of the fitted MCF.
    const h = tMax / 400;
    const a = mcfAt(Math.max(0, tv - h)), b = mcfAt(tv + h);
    return a != null && b != null ? (b - a) / (2 * h) : null;
  };
  const mtbfAt = (tv) => { const rr = rocofAt(tv); return rr && Number.isFinite(rr) && rr > 0 ? 1 / rr : null; };
  const valAt = (id, tv) => (id === "N" ? mcfAt(tv) : id === "rocof" ? rocofAt(tv) : mtbfAt(tv));

  // Curves over [0, tMax] for the active function.
  const M = 200;
  const gx = Array.from({ length: M }, (_, k) => (tMax * k) / (M - 1));
  const gy = gx.map((tv) => { const v = valAt(active, tv); return v != null && Number.isFinite(v) ? v : null; });

  const values = { N: mcfAt(nt), rocof: rocofAt(nt), mtbf: mtbfAt(nt) };
  const nFrom = from !== "" && !Number.isNaN(Number(from)) ? Number(from) : null;
  const windowN = nFrom != null ? (() => { const a = mcfAt(nFrom), b = mcfAt(nt); return a != null && b != null ? b - a : null; })() : null;

  const yv = valAt(active, nt);
  const traces = [
    { x: gx, y: gy, mode: "lines", type: "scatter", line: { color: "#2f6df6", width: 2 }, name: active, connectgaps: false },
  ];
  if (yv != null && Number.isFinite(yv)) {
    traces.push({ x: [nt], y: [yv], mode: "markers", type: "scatter",
      marker: { color: "#2f6df6", size: 8, line: { color: "#fff", width: 1 } }, showlegend: false, hoverinfo: "y" });
  }
  const yTitle = FUNCS.find((f) => f.id === active)?.y || active;
  const layout = {
    autosize: true, height: 420, margin: { l: 64, r: 20, t: 20, b: 46 },
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "#ffffff",
    font: { color: "#6c727c", family: "IBM Plex Mono, monospace", size: 11 },
    showlegend: false,
    xaxis: { title: { text: tLabel, standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
    yaxis: { title: { text: yTitle + (unit && active !== "N" && active !== "rocof" ? ` (${unit})` : ""), standoff: 12 }, automargin: true, gridcolor: "#eceae4", linecolor: "#cdcbc3", zeroline: false, rangemode: "tozero" },
    shapes: [{ type: "line", x0: nt, x1: nt, yref: "paper", y0: 0, y1: 1, line: { color: "#94a3b8", width: 1, dash: "dot" } }],
  };

  return (
    <div className="calc">
      <div className="calc-body">
        <div className="calc-main">
          <div className="calc-values">
            {FUNCS.map((f) => (
              <div className={"calc-cell" + (active === f.id ? " active" : "")} key={f.id}>
                <div className="calc-cell-id">{f.id === "N" ? "N(t)" : f.id === "rocof" ? "ROCOF" : "MTBF"}</div>
                <div className="calc-cell-val">
                  {fmt(values[f.id])}{f.id === "mtbf" && values.mtbf != null && unit ? ` ${unit}` : ""}
                </div>
              </div>
            ))}
          </div>
          {windowN != null && (
            <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
              Expected failures between {tLabel} = {from} and {t}: <b>{fmt(windowN)}</b>
              {analytic ? "" : " (interpolated)"}.
            </p>
          )}
          <Plot data={traces} layout={layout} config={{ displayModeBar: true, responsive: true }} style={{ width: "100%" }} useResizeHandler />
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Evaluate</div>
            <div className="calc-eval-body">
              <div className="seg">
                {FUNCS.map((f) => (
                  <button key={f.id} className={"seg-btn" + (active === f.id ? " active" : "")}
                          onClick={() => setActive(f.id)} title={f.label}>
                    {f.id === "N" ? "N(t)" : f.id === "rocof" ? "ROCOF" : "MTBF"}
                  </button>
                ))}
              </div>
              <label className="calc-t">
                <span>Evaluate at {tLabel}</span>
                <input type="number" min={0} step="any" value={t} onChange={(e) => setT(e.target.value)} />
              </label>
              <label className="calc-t">
                <span>From{unit ? ` (${unit})` : ""} — for a window</span>
                <input type="number" min={0} step="any" placeholder="e.g. 0" value={from} onChange={(e) => setFrom(e.target.value)} />
              </label>
              {!analytic && (
                <p className="muted-line" style={{ margin: "0.2rem 0 0", fontSize: "0.8rem" }}>
                  Interpolated from the fitted MCF — accurate within the fitted range.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
