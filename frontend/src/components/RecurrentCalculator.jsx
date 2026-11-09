import { useState } from "react";
import Plot from "./Plot.jsx";
import { fitLine, pointMarker, referenceShape } from "../plotTheme.js";
import Select from "./Select.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";

// Recurrent-event calculator: read off the repairable-system functions at a
// chosen time — expected cumulative failures N(t), the rate of occurrence of
// failures ROCOF(t), and the instantaneous MTBF(t) — and, over a window, the
// failures to expect with the average rate and MTBF. The power law
// (Crow-AMSAA) is evaluated in closed form from α, β; otherwise the fitted MCF
// curve is interpolated. Mirrors the life-data Calculator: one answer line —
// function, time, value — then the chart filling the tab, the window in the rail.
const FUNCS = [
  { id: "N", label: "Expected failures N(t)", y: "Expected failures per system" },
  { id: "rocof", label: "Failure rate (ROCOF)", y: "Failure rate" },
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
  const unit = String(r.unit || "").toLowerCase();
  const tLabel = unit ? `t (${unit})` : "t";
  const fitted = r.mcf?.fitted || {};
  const byName = Object.fromEntries((r.params || []).map((p) => [p.name, p.value]));
  const alpha = byName.alpha;
  const beta = byName.beta ?? r.beta;
  // Crow-AMSAA's power law, N(t) = (t/α)^β, in closed form; every other
  // model (Duane's own parameters, covariates, imperfect repair) off its
  // fitted MCF curve.
  const analytic = (r.model?.id || "crow_amsaa") === "crow_amsaa" && (r.family || "nhpp") === "nhpp" &&
    alpha > 0 && beta != null;

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

  const nFrom = from !== "" && Number.isFinite(Number(from)) ? Number(from) : null;
  // Over a window [from, t]: the expected failures, and the average rate and
  // MTBF across it.
  const win = (() => {
    if (nFrom == null || !(nt > nFrom)) return null;
    const a = mcfAt(nFrom), b = mcfAt(nt);
    if (a == null || b == null) return null;
    const n = b - a;
    return { n, rate: n / (nt - nFrom), mtbf: n > 0 ? (nt - nFrom) / n : null };
  })();

  const yv = valAt(active, nt);
  const traces = [fitLine({ x: gx, y: gy, name: active, connectgaps: false })];
  if (yv != null && Number.isFinite(yv)) {
    traces.push({ ...pointMarker(), x: [nt], y: [yv] });
  }
  const yTitle = FUNCS.find((f) => f.id === active)?.y || active;
  const shapes = [referenceShape({ x: nt, line: { dash: "dot" } })];
  if (win) {
    // The window, shaded.
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: nFrom, x1: nt, y0: 0, y1: 1,
                  fillcolor: "rgba(47,109,246,0.08)", line: { width: 0 }, layer: "below" });
  }
  const layout = {
    showlegend: false,
    xaxis: { title: { text: tLabel }, rangemode: "tozero" },
    yaxis: {
      title: {
        text: yTitle + (unit && active === "mtbf" ? ` (${unitInText(unit)})`
          : unit && active === "rocof" ? ` (per ${unitInText(unit).replace(/s$/, "")})` : ""),
      },
      rangemode: "tozero",
    },
    shapes,
  };
  const ut = unit ? unitInText(unit) : "";

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
              type="number" inputMode="decimal"
              className="calc-t-input"
              aria-label={`Evaluate at ${tLabel}`}
              min={0}
              step="any"
              value={t}
              onChange={(e) => setT(e.target.value)}
            />
            <span>{ut}:</span>
            <span className="calc-answer-value">
              <b>{fmt(yv)}{active === "mtbf" && yv != null && ut ? ` ${ut}` : ""}</b>
              {active === "rocof" && yv != null && ut && (
                <span className="calc-answer-ci"> per {ut.replace(/s$/, "")}</span>
              )}
            </span>
          </div>
          <Plot fill data={traces} layout={layout} download={`${name || "Recurrent model"} — ${yTitle}`} />
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Over a window</div>
            <div className="calc-eval-body">
              <label className="calc-t">
                <span>From{unit ? ` (${unitInText(unit)})` : ""}, to the time chosen</span>
                <input type="number" inputMode="decimal" min={0} step="any" placeholder="e.g. 0" value={from}
                       onChange={(e) => setFrom(e.target.value)} />
              </label>
              {win ? (
                <dl className="rec-window" aria-live="polite">
                  <div><dt>Expected failures</dt><dd>{fmt(win.n)} <span className="gof-sub">per system</span></dd></div>
                  <div><dt>Average failure rate</dt><dd>{fmt(win.rate)}{ut ? <span className="gof-sub"> per {ut.replace(/s$/, "")}</span> : null}</dd></div>
                  <div><dt>Average MTBF</dt><dd>{win.mtbf != null ? `${fmt(win.mtbf)}${ut ? ` ${ut}` : ""}` : "—"}</dd></div>
                </dl>
              ) : (
                <p className="rs-note">
                  {nFrom != null && !(nt > nFrom)
                    ? "The window ends at the time chosen above the chart: make that later than the start."
                    : "Enter a start time to see the failures to expect between then and the time chosen: for a budget or a spares order."}
                </p>
              )}
              {!analytic && (
                <p className="rs-note">
                  Read off the fitted MCF{r.family === "regression" ? " of the fleet's average system"
                    : r.mcf?.fitted?.simulated ? " (simulated)" : ""}: accurate within the fitted range.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
