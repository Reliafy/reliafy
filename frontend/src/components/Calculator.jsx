import Select from "./Select.jsx";
import Modal from "./Modal.jsx";
import { withUnit } from "./stressName.js";
import CiNote from "./CiNote.jsx";
import { useEffect, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, bandPair, pointMarker, referenceShape } from "../plotTheme.js";
import { confidenceAt, evaluateAt, lifeAt } from "../api.js";
import { formatNumber, formatPercent } from "../format.js";
import { boundWords, timeAtValue } from "../lifeResults.js";
import RegressionLife from "./RegressionLife.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
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
    // Confidence bounds config + the last-fetched band of each series, by its
    // id (keyed to avoid refetching): a regression model has one per
    // covariate combination (#54). 90% one-sided lower by default, as the
    // life card's B-lives (#288).
    ci: { level: 90, bound: "lower", bands: {} },
    // "value": a function at a time; "time": the time at a reliability (#288).
    mode: "value",
    rTarget: 90, // %, for the time at a reliability
    tar: { key: null, data: null, error: null }, // last-fetched time at reliability
  };
}

// Distinct colours for covariate-combination series, in the theme's order.
const COLORS = COLORWAY;
// A series colour as a light band fill ("#2f6df6" → rgba at 12%).
const tint = (hex) => {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  return m ? `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},0.12)` : undefined;
};
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
                <span>{c.stratum ? `${c.name} (stratum)` : withUnit(c.name, c.unit)}</span>
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
export default function Calculator({ functions, unit, params, state, setState, nextIdRef, name = null,
                                     paramLabel = null }) {
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
  const { series, t, condAge: condInput, ci, xMin, xMax } = state;
  const mode = state.mode || "value";
  const timeMode = mode === "time";
  const rTarget = state.rTarget ?? 90;
  // The time at a reliability reads the reliability curve, unconditioned.
  const active = timeMode ? "sf" : state.active;
  const condAge = timeMode ? "" : condInput;
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
  const setMode = (v) => setState((st) => ({ ...st, mode: v }));
  const setRTarget = (v) => setState((st) => ({ ...st, rTarget: v }));
  const setTar = (v) => setState((st) => ({ ...st, tar: v }));

  // Manual x-axis limits (blank/invalid = auto). When set — and the model can
  // be re-evaluated — the curves and confidence band are recomputed over the
  // new range so the lines extend (or refine) to the chosen limits, not just
  // clip the view.
  const xLoNum = xMin !== "" && !Number.isNaN(Number(xMin)) ? Number(xMin) : null;
  const xHiNum = xMax !== "" && !Number.isNaN(Number(xMax)) ? Number(xMax) : null;
  const manualX = xLoNum != null || xHiNum != null;
  const evalRange = manualX ? { xMin: xLoNum, xMax: xHiNum } : undefined;

  // Confidence bounds — plain, discrete and non-parametric models, and a
  // parametric regression model at each covariate combination (#54); Cox PH
  // has none (``bands_note`` says why). Computed by SurPyval's cb() on demand.
  const confidencePath = functions.confidence_path;
  const ciLevel = Number(ci.level);
  const ciValid = confidencePath && ciLevel > 0 && ciLevel < 100;
  const ciAlpha = 1 - ciLevel / 100;
  const bands = ci.bands || {};
  const banded = hasCov ? series : series.slice(0, 1);
  const bandValues = JSON.stringify(banded.map((s) => [s.id, hasCov ? s.values : null]));
  const setBand = (id, value) =>
    setState((st) => ({ ...st, ci: { ...st.ci, bands: { ...(st.ci.bands || {}), [id]: value } } }));
  useEffect(() => {
    if (!ciValid || ci.bound === "none") return undefined;
    const timers = banded.map((s) => {
      const wantKey = `${active}|${ciAlpha}|${ci.bound}|${xLoNum}|${xHiNum}|${hasCov ? JSON.stringify(s.values) : ""}`;
      const have = bands[s.id];
      if (have?.key === wantKey && (have.data || have.error)) return null; // already have this band
      // Debounced so typing a level (or a covariate) doesn't spam the backend.
      return setTimeout(() => {
        confidenceAt(confidencePath, {
          on: active, alpha_ci: ciAlpha, bound: ci.bound, ...(hasCov ? { values: s.values } : {}),
        }, evalRange)
          .then((res) => setBand(s.id, { key: wantKey, data: res, error: null }))
          .catch((err) => setBand(s.id, { key: wantKey, data: null, error: err.message }));
      }, 300);
    });
    return () => timers.forEach((id) => id && clearTimeout(id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ciValid, active, ciAlpha, ci.bound, confidencePath, xLoNum, xHiNum, bandValues]);
  const bandError = banded.map((s) => bands[s.id]?.error).find(Boolean);

  // Time at a reliability (#288): the model's own quantile and its bound(s)
  // from the life path; without one (regression, or parameters only), read
  // off the curve, with no bound.
  const lifePath = functions.life_path;
  const rNum = Number(rTarget);
  const rValid = rTarget !== "" && rNum > 0 && rNum < 100;
  const tarBound = ci.bound === "none" ? "lower" : ci.bound;
  // A regression model's time is the first combination's (#54).
  const tarCovariates = hasCov ? series[0]?.values : null;
  const tarKey = `${rNum}|${ciLevel}|${tarBound}|${tarCovariates ? JSON.stringify(tarCovariates) : ""}`;
  const tar = state.tar || {};
  useEffect(() => {
    if (!timeMode || !lifePath || !rValid || !(ciLevel > 0 && ciLevel < 100)) return undefined;
    if (tar.key === tarKey && (tar.data || tar.error)) return undefined;
    const id = setTimeout(() => {
      lifeAt(lifePath, {
        reliability: [rNum / 100], confidence: ciLevel / 100, bound: tarBound,
        ...(tarCovariates ? { covariates: tarCovariates } : {}),
      })
        .then((res) => setTar({ key: tarKey, data: res, error: null }))
        .catch((err) => setTar({ key: tarKey, data: null, error: err.message }));
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeMode, lifePath, tarKey, rValid]);

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

  // The time at the target reliability for each series, and (one series with
  // a life path) the model's exact value with its bound(s).
  const tarPoint = timeMode && lifePath && tar.key === tarKey ? tar.data?.points?.[0] : null;
  const tarTimes = series.map((s, i) =>
    i === 0 && tarPoint && !multi ? tarPoint.time : rValid ? timeAtValue(views[i]?.x, views[i]?.sf, rNum / 100) : null
  );

  // Backend flags impossible reliability (sf > 1 from a negative cumulative
  // hazard — additive-hazards models). Surface it rather than hide it.
  const curveWarning = series.map((s) => s.curves?.warning).find(Boolean);

  // Confidence band of each series for the active function (raw scale only —
  // it isn't conditionalised, so it's hidden when a survived-age is set).
  const bandOf = (s) => {
    const b = bands[s.id]?.data;
    return ci.bound !== "none" && b && b.on === active && cond === 0 ? b : null;
  };
  const band = series[0] ? bandOf(series[0]) : null;

  // Chart: the active function for every series, plus a marker at t.
  const traces = [];
  banded.forEach((s, i) => {
    const b = bandOf(s);
    if (!b) return;
    // Two-sided: a shaded band under the fitted line (added next). One-sided:
    // the bound alone, dashed. Several combinations: each in its own colour,
    // named only in the hover-free legend of one.
    const color = COLORS[i % COLORS.length];
    const bandName = multi ? undefined
      : b.bound === "two-sided" ? `${ciLevel}% confidence band` : `${ciLevel}% ${b.bound} bound`;
    if (b.lower && b.upper) {
      traces.push(...bandPair(b.x, b.lower, b.upper, {
        name: bandName, connectgaps: false, ...(multi ? { fillcolor: tint(color), showlegend: false } : {}),
      }));
    } else {
      traces.push({
        x: b.x, y: b.lower || b.upper, mode: "lines", type: "scatter",
        line: { color, width: 1.5, dash: "dash" },
        name: bandName, showlegend: !multi, connectgaps: false, hoverinfo: "skip",
      });
    }
  });
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
    if (timeMode) {
      if (tarTimes[i] != null) traces.push({ ...pointMarker(color), x: [tarTimes[i]], y: [rNum / 100] });
      return;
    }
    const y = interp(cv.x, cv[active], Number(t));
    if (y != null) {
      traces.push({ ...pointMarker(color), x: [Number(t)], y: [y] });
    }
  });

  // One curve needs no legend: the axis names it and the read-out above gives
  // the band. Several (covariate combinations) get one inside the plot, in the
  // corner the curves leave empty — top right where they fall (reliability,
  // density), top left where they rise.
  const showLegend = multi;
  const falling = active === "sf" || active === "df";

  // Plot axis range: a single manual bound falls back to the data extent for
  // the other end.
  const xRange = manualX ? [xLoNum != null ? xLoNum : 0, xHiNum != null ? xHiNum : xMaxView] : undefined;

  const layout = {
    height: 440,
    showlegend: showLegend,
    margin: { t: 8, r: 12 },
    legend: {
      orientation: "v",
      x: falling ? 0.985 : 0.015,
      xanchor: falling ? "right" : "left",
      y: 0.985,
      yanchor: "top",
      bgcolor: "rgba(255,255,255,0.85)",
    },
    xaxis: {
      title: { text: tAxisLabel },
      ...(manualX ? { range: xRange, autorange: false } : {}),
    },
    yaxis: { title: { text: activeLabel } },
    shapes: timeMode
      ? [
          ...(rValid ? [referenceShape({ y: rNum / 100, line: { dash: "dot" } })] : []),
          ...(tarTimes[0] != null ? [referenceShape({ x: tarTimes[0], line: { dash: "dot" } })] : []),
        ]
      : [referenceShape({ x: Number(t), line: { dash: "dot" } })],
  };
  const unitWord = unit ? ` ${unitInText(unit)}` : "";
  const fmtTime = (v) => `${formatNumber(v)}${unitWord}`;

  return (
    <div className="calc">
      <div className="calc-body">
        <div className="calc-main">
      {/* The answer, read off the chart; every input sits in the card on the right. */}
      {timeMode ? (
        <div className="calc-answer">
          <span>
            Time when reliability falls to <b>{rValid ? `${rNum.toLocaleString(undefined, { maximumFractionDigits: 6 })}%` : "—"}</b>
            {rValid && Number.isInteger(Math.round((100 - rNum) * 1e6) / 1e6) ? ` (the B${100 - rNum} life)` : ""}
            {multi ? "" : ":"}
          </span>
          {!multi && (
            <span className="calc-answer-value">
              <b>{tarTimes[0] != null ? fmtTime(tarTimes[0]) : "—"}</b>
              {ci.bound !== "none" && tarPoint && (() => {
                const words = boundWords(ciLevel, tar.data.bound, tarPoint.lower, tarPoint.upper, fmtTime);
                return words ? <span className="calc-answer-ci"> — {words}</span> : null;
              })()}
            </span>
          )}
        </div>
      ) : (
      <div className="calc-answer">
        <span>
          {fnLabel(active, meta)} {cond > 0 ? "for a further" : "at"}{" "}
          <b>{Number(t).toLocaleString(undefined, { maximumFractionDigits: 6 })}{unit ? ` ${unitInText(unit)}` : ""}</b>
          {cond > 0 ? `, having survived ${sLabel}` : ""}{multi ? "" : ":"}
        </span>
        {!multi && (
          <span className="calc-answer-value">
            <b>{fmtFn(active, interp(views[0]?.x, views[0]?.[active], Number(t)))}</b>
            {band && (() => {
              // In words (#292): "we're 90% sure it's at least 38%".
              const lo = band.lower ? interp(band.x, band.lower, Number(t)) : null;
              const hi = band.upper ? interp(band.x, band.upper, Number(t)) : null;
              const words = boundWords(ciLevel, band.bound, lo, hi, (v) => fmtFn(active, v));
              return words ? <span className="calc-answer-ci"> — {words}</span> : null;
            })()}
          </span>
        )}
      </div>
      )}
      {timeMode && lifePath && tar.key === tarKey && tar.error && (
        <p className="hint" style={{ margin: "0 0 0.4rem" }}>Couldn't compute the time: {tar.error}</p>
      )}
      {timeMode && tarPoint && tar.data?.bounds_note && ci.bound !== "none" && (
        <p className="muted-line" style={{ margin: "0 0 0.4rem" }}>{tar.data.bounds_note}</p>
      )}
      {curveWarning && <p className="calc-warn">⚠ {curveWarning}</p>}
      {confidencePath && ci.bound !== "none" && bandError && (
        <p className="hint" style={{ margin: "0 0 0.4rem" }}>
          Couldn't compute confidence bounds: {bandError}
        </p>
      )}
      {confidencePath && cond > 0 && (
        <p className="muted-line" style={{ margin: "0 0 0.4rem" }}>
          Confidence bounds are shown on the unconditional function only — clear
          the survived-age to see them.
        </p>
      )}

      {multi && timeMode ? (
        <table className="calc-table">
          <thead>
            <tr><th>Combination</th><th>Time at R = {rValid ? `${rNum}%` : "—"}{unitWord ? ` (${unitWord.trim()})` : ""}</th></tr>
          </thead>
          <tbody>
            {series.map((s, i) => (
              <tr key={s.id}>
                <td className="calc-row-label">
                  <span className="combo-dot" style={{ background: COLORS[i % COLORS.length] }} />
                  {labelOf(s)}
                </td>
                <td>{tarTimes[i] != null ? formatNumber(tarTimes[i]) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : multi ? (
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
              <div className="gofh">Inputs</div>
              <div className="calc-eval-body">
                <SegmentedControl
                  label="What to calculate"
                  size="sm"
                  className="calc-mode"
                  value={mode}
                  onChange={setMode}
                  options={[
                    { value: "value", label: "At a time" },
                    { value: "time", label: "Time at reliability", title: "The time by which reliability falls to a level: R = 90% is the B10 life" },
                  ]}
                />
                {timeMode ? (
                  <label className="calc-t">
                    <span>Reliability %</span>
                    <input
                      type="number"
                      value={rTarget}
                      min={0.01}
                      max={99.99}
                      step="any"
                      onChange={(e) => setRTarget(e.target.value)}
                    />
                  </label>
                ) : (
                <>
                <label className="calc-t">
                  <span>Function</span>
                  <Select
                    value={active}
                    onChange={setActive}
                    className="calc-fn"
                    options={meta.map((m) => ({ value: m.id, label: fnLabel(m.id, meta) }))}
                  />
                </label>
                <label className="calc-t">
                  <span>{cond > 0 ? "For a further" : "At"}{unit ? ` (${unitInText(unit)})` : ""}</span>
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
                </>
                )}
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
                {!confidencePath && functions.bands_note && (
                  <p className="calc-note">{functions.bands_note}</p>
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
            {hasCov && (functions.life_path || functions.life_note) && (
              <RegressionLife
                path={functions.life_path}
                note={functions.life_note}
                values={series[0]?.values}
                level={ciValid ? ciLevel : 90}
                unit={unit}
                dot={multi ? COLORS[0] : null}
              />
            )}
            {params && params.length > 0 && (
              <div className="calc-rail-card calc-rail-params">
                <div className="gofh">Parameters</div>
                {params.map((p) => (
                  <div className="gofr" key={p.name}>
                    <span className="gk">{paramLabel ? paramLabel(p) : p.name}</span>
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
