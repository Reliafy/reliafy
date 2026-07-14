import Select from "./Select.jsx";
import { useEffect, useRef } from "react";
import Plot from "react-plotly.js";
import { confidenceAt, evaluateAt } from "../api.js";

// The calculator's inputs (covariate combinations, active function, evaluation
// time, conditional age) live in the parent (ResultView) so they survive tab
// switches — the tab body unmounts when you leave it. This builds the initial
// state for a set of fitted functions.
export function initCalcState(functions) {
  const covariates = functions?.covariates || [];
  const hasCov = covariates.length > 0 && !!functions?.evaluate_path;
  const values = hasCov
    ? Object.fromEntries(covariates.map((c) => [c.name, c.default]))
    : null;
  const x = functions?.curves?.x || [];
  const mid = x.length ? x[Math.floor(x.length / 2)] : 0;
  return {
    series: functions ? [{ id: 0, values, curves: functions.curves, error: null }] : [],
    active: "sf",
    t: x.length ? Number(mid.toPrecision(4)) : 0,
    condAge: "", // conditional survival age s
    // Confidence bounds config + last-fetched band (keyed to avoid refetching).
    ci: { level: 95, bound: "two-sided", key: null, data: null, error: null },
  };
}

// Distinct colours for covariate-combination series.
const COLORS = ["#0284c7", "#16a34a", "#db2777", "#d97706", "#7c3aed", "#0891b2"];
const MAX_SERIES = 6;

// Linear interpolation of y at xq from the (x, y) grid; null y points are
// treated as gaps. Returns null outside the grid or across a gap.
function interp(x, y, xq) {
  if (!x || !y || xq < x[0] || xq > x[x.length - 1]) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1];
      const y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const x0 = x[i - 1];
      const x1 = x[i];
      const f = x1 === x0 ? 0 : (xq - x0) / (x1 - x0);
      return y0 + f * (y1 - y0);
    }
  }
  return null;
}

const fmt = (v) =>
  v == null ? "—" : Math.abs(v) >= 1e-4 || v === 0 ? v.toPrecision(5) : v.toExponential(3);

// Condition a set of curves on having already survived to age s: the time axis
// becomes additional time t (= x - s) and each function is recomputed as the
// conditional version — R(t|s)=R(s+t)/R(s), f(t|s)=f(s+t)/R(s), h(t|s)=h(s+t),
// H(t|s)=H(s+t)-H(s).
function conditionalize(curves, s) {
  const { x } = curves;
  const sfAtS = interp(x, curves.sf, s);
  const HfAtS = interp(x, curves.Hf, s);
  const out = { x: [], sf: [], ff: [], hf: [], Hf: [], df: [] };
  if (sfAtS == null || sfAtS <= 0) return out;
  for (let i = 0; i < x.length; i++) {
    if (x[i] < s) continue;
    out.x.push(x[i] - s);
    const sf = curves.sf?.[i] == null ? null : curves.sf[i] / sfAtS;
    out.sf.push(sf);
    out.ff.push(sf == null ? null : 1 - sf);
    out.hf.push(curves.hf ? curves.hf[i] : null);
    out.Hf.push(
      curves.Hf?.[i] != null && HfAtS != null ? curves.Hf[i] - HfAtS : null
    );
    out.df.push(curves.df?.[i] != null ? curves.df[i] / sfAtS : null);
  }
  return out;
}

// Calculator tab: chart any of the reliability functions and read them off at a
// chosen t. For regression models you can add several covariate combinations,
// each re-evaluated by the backend and overlaid on the chart.
export default function Calculator({ functions, unit, state, setState, nextIdRef }) {
  const { meta, evaluate_path: evaluatePath } = functions;
  const tLabel = unit ? `t (${unit})` : "t";
  const covariates = functions.covariates || [];
  const hasCov = covariates.length > 0 && !!evaluatePath;

  const defaults = () =>
    Object.fromEntries(covariates.map((c) => [c.name, c.default]));

  // State is owned by the parent so it persists across tab switches.
  const { series, active, t, condAge, ci } = state;
  const setSeries = (updater) =>
    setState((st) => ({
      ...st,
      series: typeof updater === "function" ? updater(st.series) : updater,
    }));
  const setActive = (v) => setState((st) => ({ ...st, active: v }));
  const setT = (v) => setState((st) => ({ ...st, t: v }));
  const setCondAge = (v) => setState((st) => ({ ...st, condAge: v }));
  const setCi = (patch) => setState((st) => ({ ...st, ci: { ...st.ci, ...patch } }));

  // Confidence bounds — available for plain/discrete/non-parametric models
  // (regression has none). Computed by SurPyval's cb() on demand.
  const confidencePath = functions.confidence_path;
  const ciLevel = Number(ci.level);
  const ciValid = confidencePath && ciLevel > 0 && ciLevel < 100;
  const ciAlpha = 1 - ciLevel / 100;
  useEffect(() => {
    if (!ciValid) return;
    const wantKey = `${active}|${ciAlpha}|${ci.bound}`;
    if (ci.key === wantKey && ci.data) return; // already have this band
    // Debounced so typing a level doesn't spam the backend.
    const id = setTimeout(() => {
      confidenceAt(confidencePath, { on: active, alpha_ci: ciAlpha, bound: ci.bound })
        .then((res) => setCi({ key: wantKey, data: res, error: null }))
        .catch((err) => setCi({ key: wantKey, data: null, error: err.message }));
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ciValid, active, ciAlpha, ci.bound, confidencePath]);

  const x = functions.curves.x;

  const cond = condAge === "" ? 0 : Number(condAge);
  const sLabel = `${cond}${unit ? ` ${unit}` : ""}`;
  const view = (curves) => (cond > 0 && curves ? conditionalize(curves, cond) : curves);
  const xMaxView = cond > 0 ? x[x.length - 1] - cond : x[x.length - 1];

  const baseLabel = meta.find((m) => m.id === active)?.label || active;
  const activeLabel = cond > 0 ? `${baseLabel} | survived to ${sLabel}` : baseLabel;
  const tAxisLabel =
    cond > 0 ? `additional time${unit ? ` (${unit})` : ""}` : tLabel;
  const multi = series.length > 1;

  // Per-series debounced re-evaluation against the backend.
  const timers = useRef({});
  const runEval = (id, values) => {
    clearTimeout(timers.current[id]);
    timers.current[id] = setTimeout(async () => {
      try {
        const res = await evaluateAt(evaluatePath, values);
        setSeries((prev) =>
          prev.map((s) => (s.id === id ? { ...s, curves: res.curves, error: null } : s))
        );
      } catch (err) {
        setSeries((prev) =>
          prev.map((s) => (s.id === id ? { ...s, error: err.message } : s))
        );
      }
    }, 300);
  };

  const updateValue = (id, name, value) => {
    const current = series.find((s) => s.id === id);
    const updated = { ...current.values, [name]: value };
    setSeries((prev) =>
      prev.map((s) => (s.id === id ? { ...s, values: updated } : s))
    );
    runEval(id, updated);
  };

  const addSeries = () => {
    if (series.length >= MAX_SERIES) return;
    const id = nextIdRef.current++;
    const values = { ...(series[series.length - 1]?.values || defaults()) };
    setSeries((prev) => [...prev, { id, values, curves: null, error: null }]);
    runEval(id, values);
  };

  const removeSeries = (id) =>
    setSeries((prev) => prev.filter((s) => s.id !== id));

  const labelOf = (s) =>
    s.values
      ? covariates.map((c) => `${c.name}=${s.values[c.name]}`).join(", ")
      : "Model";

  // Per-series curves, conditioned on the survived age when set.
  const views = series.map((s) => view(s.curves));

  // Confidence band for the active function (raw scale only — it isn't
  // conditionalised, so it's hidden when a survived-age is set).
  const band = ci.data && ci.data.on === active && cond === 0 ? ci.data : null;

  // Chart: the active function for every series, plus a marker at t.
  const traces = [];
  if (band) {
    // Lower first, then upper filling down to it (two-sided) — drawn under the
    // fitted line, which is added next.
    if (band.lower) {
      traces.push({
        x: band.x, y: band.lower, mode: "lines", type: "scatter",
        line: { color: "#0284c7", width: 1, dash: "dot" },
        name: band.bound === "two-sided" ? `${ciLevel}% lower` : `${ciLevel}% ${band.bound}`,
        connectgaps: false, hoverinfo: "skip",
      });
    }
    if (band.upper) {
      traces.push({
        x: band.x, y: band.upper, mode: "lines", type: "scatter",
        line: { color: "#0284c7", width: 1, dash: "dot" },
        name: band.bound === "two-sided" ? `${ciLevel}% upper` : `${ciLevel}% ${band.bound}`,
        fill: band.lower ? "tonexty" : undefined, fillcolor: "rgba(2,132,199,0.10)",
        connectgaps: false, hoverinfo: "skip",
      });
    }
  }
  series.forEach((s, i) => {
    const cv = views[i];
    if (!cv) return;
    const color = COLORS[i % COLORS.length];
    traces.push({
      x: cv.x,
      y: cv[active],
      mode: "lines",
      line: { color, width: 2 },
      name: multi ? labelOf(s) : baseLabel,
      type: "scatter",
      connectgaps: false,
    });
    const y = interp(cv.x, cv[active], Number(t));
    if (y != null) {
      traces.push({
        x: [Number(t)],
        y: [y],
        mode: "markers",
        marker: { color, size: 8, line: { color: "#fff", width: 1 } },
        type: "scatter",
        showlegend: false,
        hoverinfo: "y",
      });
    }
  });

  const showLegend = multi || !!band;
  const layout = {
    autosize: true,
    height: 440,
    margin: { l: 64, r: 20, t: 20, b: showLegend ? 70 : 46 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#ffffff",
    font: { color: "#334155", family: "Inter, system-ui, sans-serif" },
    showlegend: showLegend,
    legend: { orientation: "h", y: -0.18 },
    xaxis: {
      title: { text: tAxisLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      zeroline: false,
    },
    yaxis: {
      title: { text: activeLabel, standoff: 12 },
      automargin: true,
      gridcolor: "#e2e8f0",
      linecolor: "#cbd5e1",
      zeroline: false,
    },
    shapes: [
      {
        type: "line",
        x0: Number(t),
        x1: Number(t),
        yref: "paper",
        y0: 0,
        y1: 1,
        line: { color: "#94a3b8", width: 1, dash: "dot" },
      },
    ],
  };

  return (
    <div className="calc">
      {hasCov && (
        <div className="calc-covs">
          <div className="calc-covs-head">Covariate combinations</div>
          {series.map((s, i) => (
            <div className="combo-row" key={s.id}>
              <span
                className="combo-dot"
                style={{ background: COLORS[i % COLORS.length] }}
              />
              <div className="calc-cov-fields">
                {covariates.map((c) => (
                  <label className="calc-cov" key={c.name}>
                    <span>{c.name}</span>
                    {c.type === "category" ? (
                      <Select
                        value={s.values[c.name]}
                        onChange={(v) => updateValue(s.id, c.name, v)}
                        options={c.options}
                      />
                    ) : (
                      <input
                        type="number"
                        step="any"
                        value={s.values[c.name]}
                        onChange={(e) => updateValue(s.id, c.name, e.target.value)}
                      />
                    )}
                  </label>
                ))}
              </div>
              {s.error && <span className="combo-err">{s.error}</span>}
              {series.length > 1 && (
                <button
                  className="combo-remove"
                  onClick={() => removeSeries(s.id)}
                  aria-label="Remove combination"
                  title="Remove combination"
                >
                  ×
                </button>
              )}
            </div>
          ))}
          {series.length < MAX_SERIES && (
            <button className="secondary combo-add" onClick={addSeries}>
              + Add combination
            </button>
          )}
        </div>
      )}

      <div className="calc-controls">
        <div className="seg">
          {meta.map((m) => (
            <button
              key={m.id}
              className={"seg-btn" + (active === m.id ? " active" : "")}
              onClick={() => setActive(m.id)}
              title={m.label}
            >
              {m.id}
            </button>
          ))}
        </div>
        <label className="calc-t">
          <span>Evaluate at {tAxisLabel}</span>
          <input
            type="number"
            value={t}
            min={0}
            max={xMaxView}
            step="any"
            onChange={(e) => setT(e.target.value)}
          />
        </label>
        <label className="calc-t">
          <span>Given survived to{unit ? ` (${unit})` : ""}</span>
          <input
            type="number"
            value={condAge}
            min={0}
            max={x[x.length - 1]}
            step="any"
            placeholder="0"
            onChange={(e) => setCondAge(e.target.value)}
          />
        </label>
        {confidencePath && (
          <>
            <label className="calc-t">
              <span>Confidence level %</span>
              <input
                type="number"
                value={ci.level}
                min={1}
                max={99.9}
                step="any"
                onChange={(e) => setCi({ level: e.target.value })}
              />
            </label>
            <label className="calc-t">
              <span>Bound</span>
              <Select
                value={ci.bound}
                onChange={(v) => setCi({ bound: v })}
                options={[
                  { value: "two-sided", label: "Two-sided" },
                  { value: "lower", label: "Lower" },
                  { value: "upper", label: "Upper" },
                ]}
              />
            </label>
          </>
        )}
      </div>
      {confidencePath && ci.error && (
        <p className="hint" style={{ margin: "0 0 0.4rem" }}>
          Couldn't compute confidence bounds: {ci.error}
        </p>
      )}
      {confidencePath && cond > 0 && (
        <p className="muted-line" style={{ margin: "0 0 0.4rem" }}>
          Confidence bounds are shown on the unconditional function only — clear
          the survived-age to see them.
        </p>
      )}

      {multi ? (
        <table className="calc-table">
          <thead>
            <tr>
              <th>
                at t = {t}
                {cond > 0 ? ` | ${sLabel}` : ""}
              </th>
              {meta.map((m) => (
                <th key={m.id} title={m.label}>
                  {m.id}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {series.map((s, i) => (
              <tr key={s.id}>
                <td className="calc-row-label">
                  <span
                    className="combo-dot"
                    style={{ background: COLORS[i % COLORS.length] }}
                  />
                  {labelOf(s)}
                </td>
                {meta.map((m) => (
                  <td key={m.id}>
                    {fmt(interp(views[i]?.x, views[i]?.[m.id], Number(t)))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <>
          <div className="calc-values">
            {meta.map((m) => (
              <div
                className={"calc-cell" + (active === m.id ? " active" : "")}
                key={m.id}
              >
                <div className="calc-cell-id">{m.id}</div>
                <div className="calc-cell-val">
                  {fmt(interp(views[0]?.x, views[0]?.[m.id], Number(t)))}
                </div>
              </div>
            ))}
          </div>
          {band && (() => {
            const lo = band.lower ? interp(band.x, band.lower, Number(t)) : null;
            const hi = band.upper ? interp(band.x, band.upper, Number(t)) : null;
            const range =
              band.bound === "two-sided"
                ? `[${fmt(lo)}, ${fmt(hi)}]`
                : band.bound === "lower"
                ? `≥ ${fmt(lo)}`
                : `≤ ${fmt(hi)}`;
            return (
              <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
                {ciLevel}% {band.bound === "two-sided" ? "confidence interval" : `${band.bound} confidence bound`} on{" "}
                {baseLabel} at {tAxisLabel} = {t}: <b>{range}</b>
              </p>
            );
          })()}
        </>
      )}

      <Plot
        data={traces}
        layout={layout}
        config={{ displayModeBar: true, responsive: true }}
        style={{ width: "100%" }}
        useResizeHandler
      />
    </div>
  );
}
