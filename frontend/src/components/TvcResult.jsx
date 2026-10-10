import { useEffect, useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import Coefficients from "./Coefficients.jsx";
import CiNote from "./CiNote.jsx";
import { paramView } from "./LifeSummary.jsx";
import { withUnit } from "./stressName.js";
import { unitInText } from "./unitText.js";
import { evaluateAt } from "../api.js";
import { COLORWAY, bandPair, pointMarker, referenceShape } from "../plotTheme.js";
import { formatNumber, formatPercent } from "../format.js";
import { boundWords, timeAtValue } from "../lifeResults.js";
import { initialSchedule, scheduleBody, scheduleXMax, tvcPath } from "../tvcData.js";
import "./Tvc.css";

// A regression model whose covariates change over time (#60): the
// coefficients with a plain reading each, and a calculator that follows a
// covariate schedule the user enters — reliability (or failure probability,
// or cumulative hazard) along it with SurPyval's bounds, and the life it
// gives. Same layout as the life calculator: the answer and chart on the
// left, every input in one card on the right.

const FUNCTIONS = {
  sf: { label: "Reliability R(t)", axis: "Reliability, R(t)", pct: true },
  ff: { label: "Probability of failure F(t)", axis: "Probability of failure, F(t)", pct: true },
  Hf: { label: "Cumulative hazard H(t)", axis: "Cumulative hazard, H(t)" },
};
const MAX_ROWS = 12;
const LAYOUT_WORDS = { intervals: "start and stop rows", timeline: "timeline rows" };

const fmtFn = (id, v) => (v == null ? "—" : FUNCTIONS[id]?.pct ? formatPercent(v, { sig: 3 }) : formatNumber(v, { sig: 4 }));

// Linear interpolation of y at xq on the grid (null outside it or at a gap).
function interp(x, y, xq) {
  if (!x || !y || !(xq >= x[0] && xq <= x[x.length - 1])) return null;
  for (let i = 1; i < x.length; i++) {
    if (xq <= x[i]) {
      const y0 = y[i - 1], y1 = y[i];
      if (y0 == null || y1 == null) return null;
      const f = x[i] === x[i - 1] ? 0 : (xq - x[i - 1]) / (x[i] - x[i - 1]);
      return y0 + f * (y1 - y0);
    }
  }
  return null;
}

// The baseline distribution's own id (weibull_ph → weibull), for plain names.
const baseOf = (result) => ({ ...result, distribution_id: String(result.distribution_id || "").replace(/_(ph|aft|po|ah)$/, "") });

export function TvcCoefficients({ result }) {
  const t = result.tvc || {};
  const params = result.params || [];
  const base = baseOf(result);
  return (
    <div className="tvc-coef">
      <Coefficients coefficients={result.coefficients} ratioLabel={result.ratio_label} />
      <div className="tvc-coef-side">
        {(t.readings || []).length > 0 && (
          <div className="gof-metrics-card tvc-readings">
            <div className="gofh">What it means</div>
            {t.readings.map((r) => <p className="tvc-reading" key={r.name}>{r.text}</p>)}
          </div>
        )}
        {params.length > 0 && (
          <div className="gof-metrics-card">
            <div className="gofh">Baseline (every covariate at 0)</div>
            {params.map((p) => {
              const v = paramView(base, p);
              return (
                <div className="gofr" key={p.name}>
                  <span className="gk">{v.label}</span>
                  <span className="gv-col">
                    <span className="gv">{v.value}</span>
                    {v.ci && <span className="param-ci">95% {v.ci}</span>}
                  </span>
                </div>
              );
            })}
            <CiNote params={params} note={result.ci_note} />
          </div>
        )}
        <p className="tvc-data-line">
          Fitted to {t.items?.toLocaleString()} items over {t.rows?.toLocaleString()} {LAYOUT_WORDS[t.layout] || "rows"}
          {t.failures != null ? ` (${t.failures.toLocaleString()} failures)` : ""}, each item's covariates following
          its rows.
        </p>
      </div>
    </div>
  );
}

// The calculator's opening state for a result.
export function initTvcState(result) {
  const fns = result.functions || {};
  const x = fns.curves?.x || [];
  const xEnd = x.length ? x[x.length - 1] : 1;
  const rows = initialSchedule(result.tvc?.covariates || fns.covariates || [], xEnd);
  const last = rows[rows.length - 1].t;
  return {
    rows,
    nextId: rows.length,
    active: "sf",
    t: last > 0 ? Number((last * 1.25).toPrecision(2)) : Number((xEnd / 2).toPrecision(2)),
    bound: result.tvc?.bounds ? "lower" : "none",
    level: 90,
  };
}

export function TvcCalculator({ result, state, setState, name = null }) {
  const fns = result.functions || {};
  const fields = result.tvc?.covariates || fns.covariates || [];
  const unit = result.unit;
  const unitWord = unit ? ` ${unitInText(unit)}` : "";
  const path = tvcPath(fns);
  const x0 = fns.curves?.x || [];
  const xEnd = x0.length ? x0[x0.length - 1] : 1;
  const { rows, active, t, bound, level } = state;
  const set = (patch) => setState((st) => ({ ...st, ...patch }));
  const hasBounds = !!result.tvc?.bounds;

  const body = useMemo(() => scheduleBody(rows, fields), [rows, fields]);
  const levelNum = Number(level);
  const alpha = hasBounds && bound !== "none" && levelNum > 0 && levelNum < 100 ? 1 - levelNum / 100 : null;
  const xMax = scheduleXMax(rows, xEnd);
  const key = JSON.stringify([body.schedule, active, alpha, bound, xMax]);

  const [data, setData] = useState({ key: null, res: null, error: null });
  useEffect(() => {
    if (!path || !body.schedule || data.key === key) return undefined;
    const id = setTimeout(() => {
      evaluateAt(path, {
        schedule: body.schedule, on: active, alpha_ci: alpha, bound: bound === "none" ? "lower" : bound,
        ...(xMax ? { x_max: xMax } : {}),
      })
        .then((res) => setData({ key, res, error: null }))
        .catch((err) => setData({ key, res: null, error: err.message }));
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, path]);

  const res = data.res;
  const curves = res?.curves;
  const band = alpha != null && res?.bounds ? res.bounds : null;
  const tNum = Number(t);
  const value = curves ? interp(curves.x, curves[active], tNum) : null;
  const lo = band?.lower ? interp(band.x, band.lower, tNum) : null;
  const hi = band?.upper ? interp(band.x, band.upper, tNum) : null;
  const words = band ? boundWords(levelNum, bound, lo, hi, (v) => fmtFn(active, v)) : "";
  const fmtTime = (v) => (v == null ? "—" : `${formatNumber(v)}${unitWord}`);
  const b10 = curves ? timeAtValue(curves.x, curves.sf, 0.9) : null;
  const median = curves ? timeAtValue(curves.x, curves.sf, 0.5) : null;

  // Editing the schedule.
  const setRow = (id, patch) => set({ rows: rows.map((r) => (r.id === id ? { ...r, ...patch } : r)) });
  const setValue = (id, name, v) => setRow(id, { values: { ...rows.find((r) => r.id === id).values, [name]: v } });
  const addRow = () => {
    const last = rows[rows.length - 1];
    const step = Number((xEnd / 4).toPrecision(1));
    set({ rows: [...rows, { id: state.nextId, t: (Number(last.t) || 0) + step, values: { ...last.values } }],
          nextId: state.nextId + 1 });
  };
  const removeRow = (id) => set({ rows: rows.filter((r) => r.id !== id) });

  // Chart: the curve along the schedule, its bound(s), the change-points and
  // the reading at t.
  const color = COLORWAY[0];
  const traces = [];
  if (band) {
    const bandName = band.bound === "two-sided" ? `${levelNum}% confidence band` : `${levelNum}% ${band.bound} bound`;
    if (band.lower && band.upper) {
      traces.push(...bandPair(band.x, band.lower, band.upper, { name: bandName, connectgaps: false }));
    } else {
      traces.push({ x: band.x, y: band.lower || band.upper, mode: "lines", type: "scatter",
                    line: { color, width: 1.5, dash: "dash" }, name: bandName, hoverinfo: "skip", connectgaps: false });
    }
  }
  if (curves) {
    traces.push({ x: curves.x, y: curves[active], mode: "lines", type: "scatter", line: { color, width: 2 },
                  name: FUNCTIONS[active].axis, connectgaps: false });
    if (value != null) traces.push({ ...pointMarker(color), x: [tNum], y: [value] });
  }
  const label = (values) => fields.map((f) => (fields.length === 1 ? "" : `${f.name} `) + `${values[f.name]}${f.unit ? (f.unit === "%" ? "%" : ` ${f.unit}`) : ""}`).join(", ");
  const schedule = body.schedule || [];
  const layout = {
    height: 440,
    showlegend: false,
    margin: { t: 26, r: 12 },
    xaxis: { title: { text: `t${unit ? ` (${unit})` : ""}` }, ...(xMax ? { range: [0, xMax], autorange: false } : {}) },
    yaxis: { title: { text: FUNCTIONS[active].axis } },
    shapes: [
      ...schedule.slice(1).map((r) => referenceShape({ x: r.t, line: { dash: "dot" } })),
      referenceShape({ x: tNum, line: { dash: "dash" } }),
    ],
    annotations: fields.length <= 2 ? schedule.map((r) => ({
      x: r.t, xanchor: "left", y: 1, yref: "paper", yanchor: "bottom", showarrow: false,
      text: label(r.values), font: { size: 12, color: "#5f6670" },
    })) : [],
  };

  return (
    <div className="calc tvc-calc">
      <div className="calc-body">
        <div className="calc-main">
          <div className="calc-answer">
            <span>
              {FUNCTIONS[active].label} at <b>{Number.isFinite(tNum) ? tNum.toLocaleString(undefined, { maximumFractionDigits: 6 }) : "—"}{unitWord}</b> on this schedule:
            </span>
            <span className="calc-answer-value">
              <b>{fmtFn(active, value)}</b>
              {words && <span className="calc-answer-ci"> — {words}</span>}
            </span>
          </div>
          {res?.warning && <p className="calc-warn">⚠ {res.warning}</p>}
          {body.error && <p className="hint tvc-msg">{body.error}</p>}
          {!body.error && data.key === key && data.error && <p className="hint tvc-msg">Couldn't evaluate the schedule: {data.error}</p>}
          {!path && <p className="muted-line tvc-msg">Open the model in Reliafy to change the schedule.</p>}
          {alpha != null && res && !res.bounds && res.bounds_note && <p className="muted-line tvc-msg">{res.bounds_note}</p>}
          <div className="tvc-plot">
            <Plot data={traces} layout={layout} download={`${name || result.distribution} — ${FUNCTIONS[active].axis} on a schedule`} />
          </div>
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Inputs</div>
            <div className="calc-eval-body">
              <div className="tvc-pair">
              <label className="calc-t">
                <span>Function</span>
                <Select value={active} onChange={(v) => set({ active: v })}
                        options={Object.entries(FUNCTIONS).map(([id, f]) => ({ value: id, label: f.label }))} />
              </label>
              <label className="calc-t">
                <span>At{unit ? ` (${unitInText(unit)})` : ""}</span>
                <input type="number" min={0} step="any" value={t} onChange={(e) => set({ t: e.target.value })} />
              </label>
              </div>
              <div className="tvc-schedule" role="group" aria-label="Covariate schedule">
                <span className="tvc-schedule-h">Covariate schedule <span className="tvc-schedule-sub">· each row holds until the next</span></span>
                <div className="tvc-table-wrap">
                  <table className="tvc-table">
                    <thead>
                      <tr>
                        <th>From{unit ? ` (${unitInText(unit)})` : ""}</th>
                        {fields.map((f) => <th key={f.name}>{withUnit(f.name, f.unit)}</th>)}
                        <th aria-label="Remove" />
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r, k) => (
                        <tr key={r.id}>
                          <td>
                            {k === 0 ? <span className="tvc-zero">0</span> : (
                              <input type="number" min={0} step="any" aria-label={`Row ${k + 1} starts at`}
                                     value={r.t} onChange={(e) => setRow(r.id, { t: e.target.value })} />
                            )}
                          </td>
                          {fields.map((f) => (
                            <td key={f.name}>
                              {f.type === "category" ? (
                                <Select value={r.values[f.name]} onChange={(v) => setValue(r.id, f.name, v)} options={f.options || []} />
                              ) : (
                                <input type="number" step="any" aria-label={`${f.name} from row ${k + 1}`}
                                       value={r.values[f.name] ?? ""} onChange={(e) => setValue(r.id, f.name, e.target.value)} />
                              )}
                            </td>
                          ))}
                          <td>
                            {k > 0 && (
                              <button type="button" className="combo-remove" aria-label={`Remove row ${k + 1}`}
                                      title="Remove this change" onClick={() => removeRow(r.id)}>×</button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {rows.length < MAX_ROWS && (
                  <button type="button" className="secondary sm tvc-add" onClick={addRow}>+ Add a change</button>
                )}
              </div>
              {hasBounds && (
                <div className="tvc-pair">
                  <label className="calc-t">
                    <span>Confidence bound</span>
                    <Select value={bound} onChange={(v) => set({ bound: v })} options={[
                      { value: "none", label: "None" }, { value: "lower", label: "Lower" },
                      { value: "upper", label: "Upper" }, { value: "two-sided", label: "Two-sided" },
                    ]} />
                  </label>
                  {bound !== "none" && (
                    <label className="calc-t">
                      <span>Level %</span>
                      <input type="number" min={1} max={99.9} step="any" value={level}
                             onChange={(e) => set({ level: e.target.value })} />
                    </label>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="calc-rail-card calc-rail-params">
            <div className="gofh">Life on this schedule</div>
            <div className="gofr"><span className="gk">10% failed by (B10)</span><span className="gv">{fmtTime(b10)}</span></div>
            <div className="gofr"><span className="gk">Half failed by</span><span className="gv">{median != null ? fmtTime(median) : curves ? `after ${fmtTime(curves.x[curves.x.length - 1])}` : "—"}</span></div>
            {result.tvc?.mean && <div className="gofr"><span className="gk">Mean life</span><span className="gv">{fmtTime(res?.mean)}</span></div>}
          </div>
        </div>
      </div>
    </div>
  );
}
