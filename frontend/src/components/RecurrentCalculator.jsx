import { useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, pointMarker, referenceShape } from "../plotTheme.js";
import Select from "./Select.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";

// Recurrent-event calculator: read off the repairable-system functions at a
// chosen time — expected cumulative failures N(t), the rate of occurrence of
// failures ROCOF(t), and the instantaneous MTBF(t) — plus the expected number
// of failures in a window. The power-law form (Crow-AMSAA / Duane) is evaluated
// analytically from α, β; otherwise the fitted MCF curve is interpolated. Mirrors
// the life-data Calculator (#313): one answer line — function, time, value —
// then the chart, with the window option in the rail.
const FUNCS = [
  { id: "N", label: "Expected failures N(t)", y: "Expected cumulative failures" },
  { id: "rocof", label: "Failure rate (ROCOF)", y: "ROCOF" },
  { id: "mtbf", label: "Mean time between failures", y: "MTBF" },
];

const fmt = (v) => (v == null || !Number.isFinite(v) ? "—" : formatNumber(v, { sig: 4 }));

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

export default function RecurrentCalculator({ r, name = null }) {
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

  const nFrom = from !== "" && !Number.isNaN(Number(from)) ? Number(from) : null;
  const windowN = nFrom != null ? (() => { const a = mcfAt(nFrom), b = mcfAt(nt); return a != null && b != null ? b - a : null; })() : null;

  const yv = valAt(active, nt);
  const traces = [fitLine({ x: gx, y: gy, name: active, connectgaps: false })];
  if (yv != null && Number.isFinite(yv)) {
    traces.push({ ...pointMarker(), x: [nt], y: [yv] });
  }
  const yTitle = FUNCS.find((f) => f.id === active)?.y || active;
  const layout = {
    height: 420,
    showlegend: false,
    xaxis: { title: { text: tLabel }, rangemode: "tozero" },
    yaxis: { title: { text: yTitle + (unit && active !== "N" && active !== "rocof" ? ` (${unit})` : "") }, rangemode: "tozero" },
    shapes: [referenceShape({ x: nt, line: { dash: "dot" } })],
  };

  return (
    <div className="calc">
      <div className="calc-body">
        <div className="calc-main">
          <div className="calc-answer">
            <Select
              value={active}
              onChange={setActive}
              title="Function"
              className="calc-fn"
              options={FUNCS.map((f) => ({ value: f.id, label: f.label }))}
            />
            <span>at</span>
            <input
              type="number"
              className="calc-t-input"
              aria-label={`Evaluate at ${tLabel}`}
              min={0}
              step="any"
              value={t}
              onChange={(e) => setT(e.target.value)}
            />
            <span>{unit ? unitInText(unit) : ""}:</span>
            <span className="calc-answer-value">
              <b>{fmt(yv)}{active === "mtbf" && yv != null && unit ? ` ${unitInText(unit)}` : ""}</b>
              {active === "rocof" && yv != null && unit && (
                <span className="calc-answer-ci"> per {unitInText(unit).replace(/s$/, "")}</span>
              )}
            </span>
          </div>
          {windowN != null && (
            <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
              Expected failures between {from} and {t}{unit ? ` ${unitInText(unit)}` : ""}: <b>{fmt(windowN)}</b>
              {analytic ? "" : " (interpolated)"}.
            </p>
          )}
          <Plot data={traces} layout={layout} download={`${name || "Recurrent model"} — ${yTitle}`} />
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Options</div>
            <div className="calc-eval-body">
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
