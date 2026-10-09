import Select from "./Select.jsx";
import Modal from "./Modal.jsx";
import { withUnit } from "./stressName.js";
import CiNote from "./CiNote.jsx";
import { useEffect, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, bandPair, pointMarker, referenceShape } from "../plotTheme.js";
import { confidenceAt, evaluateAt } from "../api.js";
import { formatNumber, formatPercent } from "../format.js";
import { unitInText } from "./unitText.js";

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
    xMin: "", // blank = auto-range from the data
    xMax: "",
    // Confidence bounds config + last-fetched band (keyed to avoid refetching).
    ci: { level: 95, bound: "two-sided", key: null, data: null, error: null },
  };
}

// Distinct colours for covariate-combination series, in the theme's order.
const COLORS = COLORWAY;
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

// The five functions by their plain names (#313). ``lead`` starts the answer
// sentence; probabilities read as percentages.
const FUNCTIONS = {
  sf: { label: "Reliability R(t)", axis: "Reliability, R(t)", pct: true },
  ff: { label: "Probability of failure F(t)", axis: "Probability of failure, F(t)", pct: true },
  hf: { label: "Hazard rate", axis: "Hazard rate, h(t)" },
  Hf: { label: "Cumulative hazard", axis: "Cumulative hazard, H(t)" },
  df: { label: "Density", axis: "Density, f(t)" },
};
const fnLabel = (id, meta) => FUNCTIONS[id]?.label || meta.find((m) => m.id === id)?.label || id;

// A value of function ``id``: a probability as a percentage, else a number.
const fmtFn = (id, v) =>
  v == null ? "—" : FUNCTIONS[id]?.pct ? formatPercent(v, { sig: 3 }) : formatNumber(v, { sig: 4 });

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

// The covariate-combination editor: one row per combination, each a set of
// covariate value inputs. Shared by the side rail (narrow, stacked) and the
// "more" modal (wide). Each edit re-evaluates its combination on the backend.
function CovariateCombos({ series, covariates, onUpdate, onRemove, onAdd, canAdd }) {
  return (
    <>
      {series.map((s, i) => (
        <div className="combo-row" key={s.id}>
          <span className="combo-dot" style={{ background: COLORS[i % COLORS.length] }} />
          <div className="calc-cov-fields">
            {covariates.map((c) => (
              <label className="calc-cov" key={c.name}>
                <span>{withUnit(c.name, c.unit)}</span>
                {c.type === "category" ? (
                  <Select
                    value={s.values[c.name]}
                    onChange={(v) => onUpdate(s.id, c.name, v)}
                    options={c.options}
                  />
                ) : (
                  <input
                    type="number"
                    step="any"
                    value={s.values[c.name]}
                    onChange={(e) => onUpdate(s.id, c.name, e.target.value)}
                  />
                )}
              </label>
            ))}
          </div>
          {s.error && <span className="combo-err">{s.error}</span>}
          {series.length > 1 && (
            <button
              className="combo-remove"
              onClick={() => onRemove(s.id)}
              aria-label="Remove combination"
              title="Remove combination"
            >
              ×
            </button>
          )}
        </div>
      ))}
      {canAdd && (
        <button className="secondary combo-add" onClick={onAdd}>
          + Add combination
        </button>
      )}
    </>
  );
}

// Calculator tab: chart any of the reliability functions and read them off at a
// chosen t. For regression models you can add several covariate combinations,
// each re-evaluated by the backend and overlaid on the chart.
export default function Calculator({ functions, unit, params, state, setState, nextIdRef, name = null }) {
  const { meta, evaluate_path: evaluatePath } = functions;
  const tLabel = unit ? `t (${unit})` : "t";
  const covariates = functions.covariates || [];
  const hasCov = covariates.length > 0 && !!evaluatePath;

  const defaults = () =>
    Object.fromEntries(covariates.map((c) => [c.name, c.default]));

  // Side-rail collapse + "edit in a larger view" modal (local UI only).
  const [railOpen, setRailOpen] = useState(true);
  const [covModal, setCovModal] = useState(false);
  const [axisOpen, setAxisOpen] = useState(false);

  // State is owned by the parent so it persists across tab switches.
  const { series, active, t, condAge, ci, xMin, xMax } = state;
  const setSeries = (updater) =>
    setState((st) => ({
      ...st,
      series: typeof updater === "function" ? updater(st.series) : updater,
    }));
  const setActive = (v) => setState((st) => ({ ...st, active: v }));
  const setT = (v) => setState((st) => ({ ...st, t: v }));
  const setCondAge = (v) => setState((st) => ({ ...st, condAge: v }));
  const setXMin = (v) => setState((st) => ({ ...st, xMin: v }));
  const setXMax = (v) => setState((st) => ({ ...st, xMax: v }));
  const setCi = (patch) => setState((st) => ({ ...st, ci: { ...st.ci, ...patch } }));

  // Manual x-axis limits (blank/invalid = auto). When set — and the model can
  // be re-evaluated — the curves and confidence band are recomputed over the
  // new range so the lines extend (or refine) to the chosen limits, not just
  // clip the view.
  const xLoNum = xMin !== "" && !Number.isNaN(Number(xMin)) ? Number(xMin) : null;
  const xHiNum = xMax !== "" && !Number.isNaN(Number(xMax)) ? Number(xMax) : null;
  const manualX = xLoNum != null || xHiNum != null;
  const evalRange = manualX ? { xMin: xLoNum, xMax: xHiNum } : undefined;

  // Confidence bounds — available for plain/discrete/non-parametric models
  // (regression has none). Computed by SurPyval's cb() on demand.
  const confidencePath = functions.confidence_path;
  const ciLevel = Number(ci.level);
  const ciValid = confidencePath && ciLevel > 0 && ciLevel < 100;
  const ciAlpha = 1 - ciLevel / 100;
  useEffect(() => {
    if (!ciValid || ci.bound === "none") return;
    const wantKey = `${active}|${ciAlpha}|${ci.bound}|${xLoNum}|${xHiNum}`;
    if (ci.key === wantKey && ci.data) return; // already have this band
    // Debounced so typing a level doesn't spam the backend.
    const id = setTimeout(() => {
      confidenceAt(confidencePath, { on: active, alpha_ci: ciAlpha, bound: ci.bound }, evalRange)
        .then((res) => setCi({ key: wantKey, data: res, error: null }))
        .catch((err) => setCi({ key: wantKey, data: null, error: err.message }));
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ciValid, active, ciAlpha, ci.bound, confidencePath, xLoNum, xHiNum]);

  const x = functions.curves.x;

  const cond = condAge === "" ? 0 : Number(condAge);
  const sLabel = `${cond}${unit ? ` ${unit}` : ""}`;
  const view = (curves) => (cond > 0 && curves ? conditionalize(curves, cond) : curves);
  const xMaxView = cond > 0 ? x[x.length - 1] - cond : x[x.length - 1];

  const baseLabel = FUNCTIONS[active]?.axis || fnLabel(active, meta);
  const activeLabel = cond > 0 ? `${baseLabel} | survived to ${sLabel}` : baseLabel;
  const tAxisLabel =
    cond > 0 ? `additional time${unit ? ` (${unit})` : ""}` : tLabel;
  const multi = series.length > 1;

  // Per-series debounced re-evaluation against the backend (over the current
  // x-range when limits are set).
  const timers = useRef({});
  const seriesRef = useRef(series);
  seriesRef.current = series;
  const runEval = (id, values) => {
    clearTimeout(timers.current[id]);
    timers.current[id] = setTimeout(async () => {
      try {
        const res = await evaluateAt(evaluatePath, values || {}, evalRange);
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

  // When the x-limits change, recompute every series over the new range.
  // Skips the initial mount (the payload curves already span the default grid).
  const rangeReady = useRef(false);
  useEffect(() => {
    if (!evaluatePath) return; // params-only models can't be re-evaluated
    if (!rangeReady.current) { rangeReady.current = true; return; }
    seriesRef.current.forEach((s) => runEval(s.id, s.values));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [xLoNum, xHiNum, evaluatePath]);

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
      ? covariates.map((c) => `${c.name}=${s.values[c.name]}${c.unit ? ` ${c.unit}` : ""}`).join(", ")
      : "Model";

  // Per-series curves, conditioned on the survived age when set.
  const views = series.map((s) => view(s.curves));

  // Backend flags impossible reliability (sf > 1 from a negative cumulative
  // hazard — additive-hazards models). Surface it rather than hide it.
  const curveWarning = series.map((s) => s.curves?.warning).find(Boolean);

  // Confidence band for the active function (raw scale only — it isn't
  // conditionalised, so it's hidden when a survived-age is set).
  const band = ci.bound !== "none" && ci.data && ci.data.on === active && cond === 0 ? ci.data : null;

  // Chart: the active function for every series, plus a marker at t.
  const traces = [];
  if (band) {
    // Two-sided: a shaded band under the fitted line (added next). One-sided:
    // the bound alone, dashed.
    const bandName = band.bound === "two-sided" ? `${ciLevel}% confidence band` : `${ciLevel}% ${band.bound} bound`;
    if (band.lower && band.upper) {
      traces.push(...bandPair(band.x, band.lower, band.upper, { name: bandName, connectgaps: false }));
    } else {
      traces.push({
        x: band.x, y: band.lower || band.upper, mode: "lines", type: "scatter",
        line: { color: COLORS[0], width: 1.5, dash: "dash" },
        name: bandName, connectgaps: false, hoverinfo: "skip",
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
      traces.push({ ...pointMarker(color), x: [Number(t)], y: [y] });
    }
  });

  const showLegend = multi || !!band;

  // Plot axis range: a single manual bound falls back to the data extent for
  // the other end.
  const xRange = manualX ? [xLoNum != null ? xLoNum : 0, xHiNum != null ? xHiNum : xMaxView] : undefined;

  const layout = {
    height: 440,
    showlegend: showLegend,
    xaxis: {
      title: { text: tAxisLabel },
      ...(manualX ? { range: xRange, autorange: false } : {}),
    },
    yaxis: { title: { text: activeLabel } },
    shapes: [referenceShape({ x: Number(t), line: { dash: "dot" } })],
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
          options={meta.map((m) => ({ value: m.id, label: fnLabel(m.id, meta) }))}
        />
        <span>{cond > 0 ? "for a further" : "at"}</span>
        <input
          type="number"
          className="calc-t-input"
          aria-label={`Evaluate at ${tAxisLabel}`}
          value={t}
          min={0}
          max={xMaxView}
          step="any"
          onChange={(e) => setT(e.target.value)}
        />
        <span>{unit ? unitInText(unit) : ""}{cond > 0 ? `, having survived ${sLabel}` : ""}{multi ? "" : ":"}</span>
        {!multi && (
          <span className="calc-answer-value">
            <b>{fmtFn(active, interp(views[0]?.x, views[0]?.[active], Number(t)))}</b>
            {band && (() => {
              const lo = band.lower ? interp(band.x, band.lower, Number(t)) : null;
              const hi = band.upper ? interp(band.x, band.upper, Number(t)) : null;
              const text =
                band.bound === "two-sided"
                  ? `${fmtFn(active, lo).replace(/%$/, "")}–${fmtFn(active, hi)}`
                  : band.bound === "lower"
                  ? `lower bound ${fmtFn(active, lo)}`
                  : `upper bound ${fmtFn(active, hi)}`;
              return <span className="calc-answer-ci"> ({ciLevel}% {text})</span>;
            })()}
          </span>
        )}
      </div>
      {curveWarning && <p className="calc-warn">⚠ {curveWarning}</p>}
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
                  {fnLabel(m.id, meta)}
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
                    {fmtFn(m.id, interp(views[i]?.x, views[i]?.[m.id], Number(t)))}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      <Plot data={traces} layout={layout} download={`${name || "Model"} — ${activeLabel}`} />
        </div>

        <div className="calc-side-rail">
            <div className="calc-rail-card calc-eval-card">
              <div className="gofh">Options</div>
              <div className="calc-eval-body">
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
                      <span>Confidence bound</span>
                      <Select
                        value={ci.bound}
                        onChange={(v) => setCi({ bound: v })}
                        options={[
                          { value: "none", label: "None" },
                          { value: "two-sided", label: "Two-sided" },
                          { value: "lower", label: "Lower" },
                          { value: "upper", label: "Upper" },
                        ]}
                      />
                    </label>
                    {ci.bound !== "none" && (
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
                    )}
                  </>
                )}
                <details className="calc-axis" open={axisOpen} onToggle={(e) => setAxisOpen(e.currentTarget.open)}>
                  <summary>Axis</summary>
                  <div className="calc-axis-body">
                    <label className="calc-cov">
                      <span>Min{unit ? ` (${unit})` : ""}</span>
                      <input
                        type="number"
                        step="any"
                        placeholder="auto"
                        value={xMin}
                        onChange={(e) => setXMin(e.target.value)}
                      />
                    </label>
                    <label className="calc-cov">
                      <span>Max{unit ? ` (${unit})` : ""}</span>
                      <input
                        type="number"
                        step="any"
                        placeholder="auto"
                        value={xMax}
                        onChange={(e) => setXMax(e.target.value)}
                      />
                    </label>
                    {(xMin !== "" || xMax !== "") && (
                      <button
                        type="button"
                        className="secondary calc-axis-reset"
                        onClick={() => { setXMin(""); setXMax(""); }}
                      >
                        Reset to auto
                      </button>
                    )}
                  </div>
                </details>
              </div>
            </div>
            {params && params.length > 0 && (
              <div className="calc-rail-card calc-rail-params">
                <div className="gofh">Parameters</div>
                {params.map((p) => (
                  <div className="gofr" key={p.name}>
                    <span className="gk">{p.name}</span>
                    <span className="gv-col">
                      <span className="gv">{formatNumber(p.value, { sig: 4 })}</span>
                      {p.ci && (
                        <span className="param-ci">
                          95% {formatNumber(p.ci[0])}–{formatNumber(p.ci[1])}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
                <CiNote params={params} />
              </div>
            )}
            {hasCov && (
            <aside className={"calc-rail-card calc-cov-rail" + (railOpen ? "" : " collapsed")}>
            <div className="calc-cov-rail-head">
              <button
                type="button"
                className="cov-rail-toggle"
                onClick={() => setRailOpen((o) => !o)}
                aria-expanded={railOpen}
              >
                <span>{railOpen ? "▾" : "▸"}</span> Covariates
              </button>
              <button
                type="button"
                className="cov-rail-expand"
                title="Edit in a larger view"
                aria-label="Edit covariates in a larger view"
                onClick={() => setCovModal(true)}
              >
                ⤢
              </button>
            </div>
            {railOpen && (
              <div className="calc-cov-rail-body">
                <CovariateCombos
                  series={series}
                  covariates={covariates}
                  onUpdate={updateValue}
                  onRemove={removeSeries}
                  onAdd={addSeries}
                  canAdd={series.length < MAX_SERIES}
                />
              </div>
            )}
            </aside>
            )}

          </div>
      </div>

      {hasCov && covModal && (
        <Modal
          title="Covariate combinations"
          onClose={() => setCovModal(false)}
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              <button onClick={() => setCovModal(false)}>Done</button>
            </div>
          }
        >
          <p className="hint" style={{ marginTop: 0 }}>
            Each combination is evaluated by the model and overlaid on the chart.
            Changes apply live.
          </p>
          <div className="calc-cov-modal">
            <CovariateCombos
              series={series}
              covariates={covariates}
              onUpdate={updateValue}
              onRemove={removeSeries}
              onAdd={addSeries}
              canAdd={series.length < MAX_SERIES}
            />
          </div>
        </Modal>
      )}
    </div>
  );
}
