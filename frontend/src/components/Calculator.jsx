import Select from "./Select.jsx";
import Modal from "./Modal.jsx";
import { withUnit } from "./stressName.js";
import CiNote from "./CiNote.jsx";
import { useEffect, useRef, useState } from "react";
import Plot from "./Plot.jsx";
import { COLORWAY, bandPair, pointMarker, referenceShape } from "../plotTheme.js";
import { confidenceAt, evaluateAt, lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import PercentField from "./PercentField.jsx";
import { readPercents } from "../percentForms.js";
import { boundWords, checkTime, perUnit, precisePercent, timeAtValue, timeInWords } from "../lifeResults.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Chip from "./ui/Chip.jsx";
import { unitInText } from "./unitText.js";
import { applyAnswer, curveIsCurrent, markPending, requestKey } from "../calcSeries.js";
import { SPREAD_LABEL, spreadCurves, spreadRangeText, spreadTime, spreadWords } from "../rateSpread.js";

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
    // A round example time (1000, not 996.2): only the starting input.
    t: x.length ? Number(mid.toPrecision(2)) : 0,
    condAge: "", // conditional survival age s
    xMin: "", // blank = auto-range from the data
    xMax: "",
    // Confidence bounds config + the last-fetched band of each series, by its
    // id (keyed to avoid refetching): a regression model has one per
    // covariate combination (#54). 90% one-sided lower by default (#288).
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
// The usual B-lives, one click each in "Time at reliability": [R %, label].
const B_LIVES = [[99, "B1"], [95, "B5"], [90, "B10"], [50, "B50"]];

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
  hf: { label: "Hazard rate", axis: "Hazard rate, h(t)", rate: true },
  Hf: { label: "Cumulative hazard", axis: "Cumulative hazard, H(t)" },
  df: { label: "Density", axis: "Density, f(t)", rate: true },
};
const fnLabel = (id, meta) => FUNCTIONS[id]?.label || meta.find((m) => m.id === id)?.label || id;

// A value of function ``id``: a probability as a percentage that keeps its
// decimals near 0% and 100% (99.82%, never a rounded "100%"); a hazard or a
// density with its unit ("per month") when ``unit`` is given.
const fmtFn = (id, v, unit = null) => {
  if (v == null) return "—";
  if (FUNCTIONS[id]?.pct) return precisePercent(v);
  const per = FUNCTIONS[id]?.rate ? perUnit(unit) : "";
  return `${formatNumber(v, { sig: 4 })}${per ? ` ${per}` : ""}`;
};

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

// The covariates as one compact row above the chart: the first combination's
// values typed in place; with several combinations, each as a chip (its
// colour and values), edited in the larger view.
function CovariateRow({ series, covariates, onUpdate, onAdd, canAdd, onEdit, labelOf }) {
  const multi = series.length > 1;
  const first = series[0];
  return (
    <div className="calc-cov-row" role="group" aria-label="Covariates">
      <span className="calc-cov-row-label">{multi ? "Combinations" : "At"}</span>
      {multi ? (
        <span className="calc-cov-combos">
          {series.map((s, i) => (
            <Chip key={s.id} dot={COLORS[i % COLORS.length]} onClick={onEdit} title="Edit the combinations">
              {labelOf(s)}
            </Chip>
          ))}
        </span>
      ) : first && covariates.map((c) => (
        <label className="calc-cov" key={c.name}>
          <span>{c.stratum ? `${c.name} (stratum)` : withUnit(c.name, c.unit)}</span>
          {c.type === "category" ? (
            <Select value={first.values[c.name]} onChange={(v) => onUpdate(first.id, c.name, v)} options={c.options} />
          ) : (
            <input type="number" step="any" value={first.values[c.name]}
                   onChange={(e) => onUpdate(first.id, c.name, e.target.value)} />
          )}
        </label>
      ))}
      <span className="calc-cov-actions">
        {multi && (
          <button type="button" className="secondary sm" onClick={onEdit} aria-haspopup="dialog">Edit ✎</button>
        )}
        {canAdd && (
          <button type="button" className="secondary sm" onClick={multi ? onAdd : () => { onAdd(); onEdit(); }}
                  title="Overlay the curve at other covariate values">
            + Compare another
          </button>
        )}
      </span>
      {series.map((s) => s.error && <span className="combo-err" key={s.id}>{s.error}</span>)}
    </div>
  );
}

// Calculator tab: chart any of the reliability functions and read them off at a
// chosen t. For regression models you can add several covariate combinations,
// each re-evaluated by the backend and overlaid on the chart. ``fill``: the
// chart fills the tab's height (the model page's frame).
export default function Calculator({ functions, unit, params, state, setState, nextIdRef, name = null,
                                     paramLabel = null, fill = false, ciLabel = "95%", ciNote = null,
                                     credible = false, spread = null }) {
  const { meta, evaluate_path: evaluatePath } = functions;
  const tLabel = unit ? `t (${unit})` : "t";
  const covariates = functions.covariates || [];
  const hasCov = covariates.length > 0 && !!evaluatePath;

  const defaults = () =>
    Object.fromEntries(covariates.map((c) => [c.name, c.default]));

  // The axes dialog and the covariate combinations' larger view (local UI only).
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
  // The axis now, beside its button: "Auto", or the range that's set.
  const axisUnit = unit ? ` ${unitInText(unit)}` : "";
  const axisWords = !manualX ? "Auto"
    : `${xLoNum != null ? formatNumber(xLoNum) : "auto"} to ${xHiNum != null ? formatNumber(xHiNum) : "auto"}${axisUnit}`;

  // Confidence bounds — plain, discrete and non-parametric models, and a
  // parametric regression model at each covariate combination (#54); Cox PH
  // has none (``bands_note`` says why). Computed by SurPyval's cb() on demand.
  const confidencePath = functions.confidence_path;
  // Percentages typed as 90 (percent.js): 0.9 is asked about, not taken as 0.9%.
  const pcts = readPercents("calculator", { reliability: String(rTarget ?? ""), level: String(ci.level ?? "") });
  const ciOk = pcts.checks.level.state === "ok";
  const ciLevel = ciOk ? pcts.checks.level.percent : Number(ci.level);
  const ciValid = confidencePath && ciOk;
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
  // No error left over from a level that has since been changed to a bad one.
  const bandError = ciValid ? banded.map((s) => bands[s.id]?.error).find(Boolean) : null;

  // Time at a reliability (#288): the model's own quantile and its bound(s)
  // from the life path; without one (regression, or parameters only), read
  // off the curve, with no bound.
  const lifePath = functions.life_path;
  const rValid = pcts.checks.reliability.state === "ok";
  const rNum = rValid ? pcts.checks.reliability.percent : Number(rTarget);
  const tarBound = ci.bound === "none" ? "lower" : ci.bound;
  // A regression model's time is the first combination's (#54).
  const tarCovariates = hasCov ? series[0]?.values : null;
  const tarKey = `${rNum}|${ciLevel}|${tarBound}|${tarCovariates ? JSON.stringify(tarCovariates) : ""}`;
  const tar = state.tar || {};
  useEffect(() => {
    if (!timeMode || !lifePath || !rValid || !ciOk) return undefined;
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
  const sLabel = timeInWords(cond, unit);
  // The time as typed, checked: blank is not zero, and a negative time is
  // refused with a message beside its box.
  const tCheck = checkTime(t, { example: x.length ? Number(x[Math.floor(x.length / 2)].toPrecision(2)) : null });
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
  // The series is pending from the keystroke until the curve for exactly
  // these values (and range) is back: nothing is read off the curve it holds
  // meanwhile, and an answer for values since changed is dropped (calcSeries.js).
  const runEval = (id, values, newValues) => {
    const key = requestKey(values, evalRange);
    setSeries((prev) => markPending(prev, id, key, newValues));
    clearTimeout(timers.current[id]);
    timers.current[id] = setTimeout(async () => {
      try {
        const res = await evaluateAt(evaluatePath, values || {}, evalRange);
        setSeries((prev) => applyAnswer(prev, id, key, { curves: res.curves }));
      } catch (err) {
        setSeries((prev) => applyAnswer(prev, id, key, { error: err.message }));
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
    runEval(id, updated, updated);
  };

  const addSeries = () => {
    if (series.length >= MAX_SERIES) return;
    const id = nextIdRef.current++;
    const values = { ...(series[series.length - 1]?.values || defaults()) };
    setSeries((prev) => [...prev, { id, values, curves: null, error: null }]);
    runEval(id, values);  // pending until its curve arrives
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
  // Read off a curve only when it is the curve for the values on screen.
  const current = series.map(curveIsCurrent);
  const tarTimes = series.map((s, i) =>
    i === 0 && tarPoint && !multi ? tarPoint.time
      : rValid && current[i] ? timeAtValue(views[i]?.x, views[i]?.sf, rNum / 100) : null
  );
  // The answer is on its way: say so, rather than show the one before.
  const working = timeMode ? tarTimes[0] == null && rValid && (!!series[0]?.pending || (lifePath && tar.key !== tarKey))
    : !!series[0]?.pending;
  const WORKING = "Working it out…";

  // Backend flags impossible reliability (sf > 1 from a negative cumulative
  // hazard — additive-hazards models). Surface it rather than hide it.
  const curveWarning = series.map((s) => s.curves?.warning).find(Boolean);

  // Confidence band of each series for the active function (raw scale only —
  // it isn't conditionalised, so it's hidden when a survived-age is set).
  // A library model (NRC/INL): no fit to bound, but its rate's spread across plants gives a band
  // (exp(-λ95 t) to exp(-λ5 t) on reliability), worked out here from the rate's 5% and 95%.
  const spreadBand = spread && !confidencePath && cond === 0 ? spreadCurves(spread, active, x) : null;
  const bandOf = (s) => {
    if (spreadBand) return s === series[0] ? spreadBand : null;
    const b = bands[s.id]?.data;
    // No band while the level typed isn't usable: the sentence must not say
    // "we're NaN% sure" or "150% sure" about bounds worked out at another level.
    return ci.bound !== "none" && ciOk && b && b.on === active && cond === 0 ? b : null;
  };
  const band = series[0] ? bandOf(series[0]) : null;

  // Chart: the active function for every series, plus a marker at t.
  const traces = [];
  (spreadBand ? series.slice(0, 1) : banded).forEach((s, i) => {
    const b = bandOf(s);
    if (!b) return;
    // Two-sided: a shaded band under the fitted line (added next). One-sided:
    // the bound alone, dashed. Several combinations: each in its own colour,
    // named only in the hover-free legend of one.
    const color = COLORS[i % COLORS.length];
    const bandName = multi ? undefined : b.spread ? SPREAD_LABEL
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
    const y = current[i] ? interp(cv.x, cv[active], Number(t)) : null;
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
              <b aria-live="polite">{tarTimes[0] != null ? fmtTime(tarTimes[0]) : working ? WORKING : "—"}</b>
              {spread && !lifePath && rValid && (() => {
                const r = spreadTime(spread, rNum / 100);
                return r ? <span className="calc-answer-ci"> — {spreadRangeText(r.lower, r.upper, fmtTime)}</span> : null;
              })()}
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
          <b>{timeInWords(tCheck.ok ? tCheck.value : null, unit)}</b>
          {cond > 0 ? `, having survived ${sLabel}` : ""}{multi ? "" : ":"}
        </span>
        {!multi && (
          <span className="calc-answer-value">
            <b aria-live="polite">{working ? WORKING
              : tCheck.ok && current[0] ? fmtFn(active, interp(views[0]?.x, views[0]?.[active], Number(t)), unit) : "—"}</b>
            {band && tCheck.ok && current[0] && (() => {
              // In words (#292): "we're 90% sure it's at least 38%".
              const lo = band.lower ? interp(band.x, band.lower, Number(t)) : null;
              const hi = band.upper ? interp(band.x, band.upper, Number(t)) : null;
              if (band.spread) {
                return lo != null && hi != null
                  ? <span className="calc-answer-ci"> — {spreadRangeText(lo, hi, (v) => fmtFn(active, v, unit))}</span> : null;
              }
              const words = boundWords(ciLevel, band.bound, lo, hi, (v) => fmtFn(active, v, unit));
              return words ? <span className="calc-answer-ci"> — {words}</span> : null;
            })()}
          </span>
        )}
      </div>
      )}
      {spread && <p className="muted-line calc-spread-words">{spreadWords(spread)}</p>}
      {timeMode && lifePath && tar.key === tarKey && tar.error && (
        <p className="hint" style={{ margin: "0 0 0.4rem" }}>Couldn't compute the time: {tar.error}</p>
      )}
      {timeMode && tarPoint && tar.data?.bounds_note && ci.bound !== "none" && (
        <p className="muted-line" style={{ margin: "0 0 0.4rem" }}>{tar.data.bounds_note}</p>
      )}
      {curveWarning && <p className="calc-warn">⚠ {curveWarning}</p>}
      {confidencePath && ci.bound !== "none" && bandError && (
        <p className="hint" style={{ margin: "0 0 0.4rem" }}>
          Couldn't compute {credible ? "credible intervals" : "confidence bounds"}: {bandError}
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
                <td>{tarTimes[i] != null ? formatNumber(tarTimes[i]) : s.pending ? WORKING : "—"}</td>
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
                    {s.pending ? "…" : current[i] ? fmtFn(m.id, interp(views[i]?.x, views[i]?.[m.id], Number(t))) : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}

      {hasCov && (
        <CovariateRow
          series={series}
          covariates={covariates}
          onUpdate={updateValue}
          onAdd={addSeries}
          canAdd={series.length < MAX_SERIES}
          onEdit={() => setCovModal(true)}
          labelOf={labelOf}
        />
      )}
      <Plot data={traces} layout={layout} download={`${name || "Model"} — ${activeLabel}`} fill={fill} />
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
                  <>
                  <PercentField label="Reliability" value={String(rTarget ?? "")} onChange={setRTarget}
                    check={pcts.checks.reliability} />
                  <div className="chip-row calc-blives" role="group" aria-label="B-lives">
                    {B_LIVES.map(([r, b]) => (
                      <Chip key={b} tone={rNum === r ? "accent" : "neutral"} onClick={() => setRTarget(r)}
                            aria-pressed={rNum === r} title={`Reliability ${r}%: the ${b} life`}>
                        {b}
                      </Chip>
                    ))}
                  </div>
                  </>
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
                    type="number" inputMode="decimal"
                    value={t}
                    min={0}
                    max={xMaxView}
                    step="any"
                    aria-invalid={!tCheck.ok || undefined}
                    onChange={(e) => setT(e.target.value)}
                  />
                  {!tCheck.ok && <span className="combo-err" role="alert">{tCheck.message}</span>}
                </label>
                <label className="calc-t">
                  <span>Given survived to{unit ? ` (${unitInText(unit)})` : ""}</span>
                  <input
                    type="number" inputMode="decimal"
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
                      <PercentField label={credible ? "Credible level" : "Confidence level"} value={String(ci.level ?? "")}
                        onChange={(v) => setCi({ level: v })} check={pcts.checks.level} />
                    )}
                  </>
                )}
                {/* A Bayesian update's bounds are credible intervals: say so beside the level. */}
                {spread && !confidencePath && (
                  <p className="calc-note">Shaded: {SPREAD_LABEL.toLowerCase()}, not a confidence band.</p>
                )}
                {(!confidencePath || credible) && functions.bands_note && (
                  <p className="calc-note">{functions.bands_note}</p>
                )}
                <div className="calc-axis">
                  <button type="button" className="secondary calc-axis-btn" onClick={() => setAxisOpen(true)}
                          aria-haspopup="dialog">
                    Axes
                  </button>
                  <span className="calc-axis-now">{axisWords}</span>
                </div>
              </div>
            </div>
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
                          {ciLabel} {formatNumber(p.ci[0])}–{formatNumber(p.ci[1])}
                        </span>
                      )}
                    </span>
                  </div>
                ))}
                {ciNote ? <p className="param-ci-note">{ciNote}</p> : <CiNote params={params} />}
              </div>
            )}

          </div>
      </div>

      {axisOpen && (
        <Modal
          title="Axes"
          className="modal-sm calc-axis-modal"
          onClose={() => setAxisOpen(false)}
          footer={
            <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
              {manualX && (
                <button type="button" className="secondary" onClick={() => { setXMin(""); setXMax(""); }}>
                  Reset to auto
                </button>
              )}
              <button type="button" onClick={() => setAxisOpen(false)}>Done</button>
            </div>
          }
        >
          <fieldset className="calc-axis-group">
            <legend>Time axis{unit ? ` (${unitInText(unit)})` : ""}</legend>
            <p className="muted-line">
              Where the chart starts and ends. Leave a box blank and it fits the model's curves.
              {evaluatePath ? " The curves are worked out again over the range you set." : ""}
              {" "}It changes as you type.
            </p>
            <div className="calc-axis-body">
              <label className="calc-cov">
                <span>From</span>
                <input type="number" inputMode="decimal" step="any" placeholder="auto" value={xMin}
                       onChange={(e) => setXMin(e.target.value)} />
              </label>
              <label className="calc-cov">
                <span>To</span>
                <input type="number" inputMode="decimal" step="any" placeholder="auto" value={xMax}
                       onChange={(e) => setXMax(e.target.value)} />
              </label>
            </div>
          </fieldset>
        </Modal>
      )}
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
