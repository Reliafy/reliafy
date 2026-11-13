import { useEffect, useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import { withUnit } from "./stressName.js";
import { unitInText } from "./unitText.js";
import { evaluateAt } from "../api.js";
import { COLORWAY, bandPair, pointMarker, referenceShape } from "../plotTheme.js";
import { formatNumber, formatPercent } from "../format.js";
import { boundWords, timeAtValue } from "../lifeResults.js";
import { AUTO_BOUND, boundOptions, effectiveBound } from "../levels.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import Chip from "./ui/Chip.jsx";
import { initialSchedule, scheduleBody, scheduleXMax, tvcPath } from "../tvcData.js";
import "./Tvc.css";
import ScrollCue from "./ui/ScrollCue.jsx";
import PercentField from "./PercentField.jsx";
import { readPercents } from "../percentForms.js";

// A regression model whose covariates change over time (#60): the
// coefficients with a plain reading each, and a calculator that follows a
// covariate schedule the user enters — reliability (or failure probability,
// or cumulative hazard) along it with SurPyval's bounds, for a new unit or
// one that has survived to an age, and the age at which reliability falls to
// a level with its bound. Same layout as the life calculator: the answer and chart on the
// left, every input in one card on the right.

const FUNCTIONS = {
  sf: { label: "Reliability R(t)", axis: "Reliability, R(t)", pct: true },
  ff: { label: "Probability of failure F(t)", axis: "Probability of failure, F(t)", pct: true },
  Hf: { label: "Cumulative hazard H(t)", axis: "Cumulative hazard, H(t)" },
};
const MAX_ROWS = 12;
// The usual B-lives, one click each in "Time at reliability": [R %, label].
const B_LIVES = [[99, "B1"], [95, "B5"], [90, "B10"], [50, "B50"]];

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
    // The safe side by default: lower on reliability and lives, upper on a
    // chance of failing and the cumulative hazard.
    bound: result.tvc?.bounds ? AUTO_BOUND : "none",
    level: 90,
    given: "", // the age it has survived to (blank: a new unit)
    mode: "value", // "value": a function at an age; "time": the age at a reliability
    rTarget: 90,
  };
}

// The curve along the schedule in ``state``, evaluated by the model (and
// kept per request): { res, error, body, key, data }. The calculator and the
// Model characteristics tab share it.
export function useTvcEvaluation(result, state, { on, given = null, at = null, reliability = null, bound: side = null } = {}) {
  const fns = result.functions || {};
  const fields = result.tvc?.covariates || fns.covariates || [];
  const path = tvcPath(fns);
  const x0 = fns.curves?.x || [];
  const xEnd = x0.length ? x0[x0.length - 1] : 1;
  const { rows, bound, level } = state;
  const active = on || state.active;
  const hasBounds = !!result.tvc?.bounds;
  const body = useMemo(() => scheduleBody(rows, fields), [rows, fields]);
  const levelCheck = readPercents("tvc", { level: String(level ?? "") }).checks.level;
  const levelNum = levelCheck.state === "ok" ? levelCheck.percent : Number(level);
  const alpha = hasBounds && bound !== "none" && levelCheck.state === "ok" ? 1 - levelCheck.fraction : null;
  // The side asked for (the calculator's), else the rule's for the function.
  const sent = side || effectiveBound(bound, active);
  const g = Number(given) > 0 ? Number(given) : null;
  const a = at != null && at !== "" && Number.isFinite(Number(at)) ? Number(at) : null;
  // The axis reaches the age asked about.
  const reach = Math.max(a ?? 0, g ?? 0);
  const xMax0 = scheduleXMax(rows, xEnd);
  const xMax = reach > (xMax0 ?? xEnd) ? Number((reach * 1.15).toPrecision(3)) : xMax0;
  const key = JSON.stringify([body.schedule, active, alpha, sent, xMax, g, a, reliability]);
  const [data, setData] = useState({ key: null, res: null, error: null });
  useEffect(() => {
    if (!path || !body.schedule || data.key === key) return undefined;
    const id = setTimeout(() => {
      evaluateAt(path, {
        schedule: body.schedule, on: active, alpha_ci: alpha, bound: sent === "none" ? "lower" : sent,
        ...(xMax ? { x_max: xMax } : {}),
        ...(g != null ? { given: g } : {}),
        ...(a != null ? { at: a } : {}),
        ...(reliability != null ? { reliability } : {}),
      })
        .then((res) => setData({ key, res, error: null }))
        .catch((err) => setData({ key, res: null, error: err.message }));
    }, 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, path]);
  return { res: data.res, error: data.key === key ? data.error : null, body, key, data, path, alpha, xMax, fields, xEnd };
}

export function TvcCalculator({ result, state, setState, name = null, fill = false }) {
  const unit = result.unit;
  const unitWord = unit ? ` ${unitInText(unit)}` : "";
  const { rows, active, t, bound, level } = state;
  const given = state.given ?? "";
  const timeMode = state.mode === "time";
  const set = (patch) => setState((st) => ({ ...st, ...patch }));
  const hasBounds = !!result.tvc?.bounds;
  const rCheck = readPercents("tvc", { reliability: String(state.rTarget ?? "") }).checks.reliability;
  const rOk = rCheck.state === "ok";
  const tNum = Number(t);
  const gNum = Number(given);
  const hasGiven = given !== "" && Number.isFinite(gNum) && gNum > 0;
  const givenBad = given !== "" && !(Number.isFinite(gNum) && gNum >= 0);
  const tBad = !timeMode && hasGiven && Number.isFinite(tNum) && tNum < gNum;
  // In time mode the curve is reliability and the bound a life's.
  const on = timeMode ? "sf" : active;
  const side = effectiveBound(bound, timeMode ? "time" : active);
  const { res, body, key, data, path, alpha, xMax, fields, xEnd } = useTvcEvaluation(result, state, {
    on, bound: side, given: hasGiven ? gNum : null,
    at: !timeMode && !tBad && Number.isFinite(tNum) && t !== "" ? tNum : null,
    reliability: timeMode && rOk ? rCheck.fraction : null,
  });
  const levelCheck = readPercents("tvc", { level: String(level ?? "") }).checks.level;
  const levelNum = levelCheck.state === "ok" ? levelCheck.percent : Number(level);
  const curves = res?.curves;
  const band = alpha != null && res?.bounds ? res.bounds : null;
  // The exact answer at the age asked (the backend's), else read off the curve.
  const point = res?.point && res.point.t === tNum ? res.point : null;
  const value = point ? point[active] : curves ? interp(curves.x, curves[active], tNum) : null;
  const lo = point ? point.lower ?? null : band?.lower ? interp(band.x, band.lower, tNum) : null;
  const hi = point ? point.upper ?? null : band?.upper ? interp(band.x, band.upper, tNum) : null;
  const words = alpha != null && (point?.bound || band) ? boundWords(levelNum, point?.bound || band.bound, lo, hi, (v) => fmtFn(active, v)) : "";
  const fmtTime = (v) => (v == null ? "—" : `${formatNumber(v)}${unitWord}`);
  const life = timeMode ? res?.life?.[0] : null;
  const lifeWords = life && alpha != null && life.bound
    ? boundWords(levelNum, life.bound, life.lower, life.upper, fmtTime) : "";
  const b10 = curves && !hasGiven ? timeAtValue(curves.x, curves.sf, 0.9) : null;
  const median = curves && !hasGiven ? timeAtValue(curves.x, curves.sf, 0.5) : null;
  const ageWords = (v) => `${Number.isFinite(v) ? v.toLocaleString(undefined, { maximumFractionDigits: 6 }) : "—"}${unitWord}`;
  // [new unit, given survived to an age, the word before the later age].
  const QUESTION = {
    sf: ["Reliability R(t) at", "Chance of surviving from", "to"],
    ff: ["Probability of failure F(t) at", "Chance of failing between", "and"],
    Hf: ["Cumulative hazard H(t) at", "Cumulative hazard between", "and"],
  };

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
    traces.push({ x: curves.x, y: curves[on], mode: "lines", type: "scatter", line: { color, width: 2 },
                  name: FUNCTIONS[on].axis, connectgaps: false });
    if (timeMode) {
      if (life?.time != null) traces.push({ ...pointMarker(color), x: [life.time], y: [life.reliability] });
    } else if (value != null) traces.push({ ...pointMarker(color), x: [tNum], y: [value] });
  }
  const label = (values) => fields.map((f) => (fields.length === 1 ? "" : `${f.name} `) + `${values[f.name]}${f.unit ? (f.unit === "%" ? "%" : ` ${f.unit}`) : ""}`).join(", ");
  const schedule = body.schedule || [];
  const layout = {
    height: 440,
    showlegend: false,
    margin: { t: 26, r: 12 },
    xaxis: { title: { text: `t${unit ? ` (${unit})` : ""}` }, ...(xMax ? { range: [0, xMax], autorange: false } : {}) },
    yaxis: { title: { text: hasGiven ? `${FUNCTIONS[on].axis}, from ${ageWords(gNum)}` : FUNCTIONS[on].axis } },
    shapes: [
      ...schedule.slice(1).map((r) => referenceShape({ x: r.t, line: { dash: "dot" } })),
      ...(timeMode ? (life?.time != null ? [referenceShape({ x: life.time, line: { dash: "dash" } })] : [])
        : [referenceShape({ x: tNum, line: { dash: "dash" } })]),
    ],
    annotations: fields.length <= 2 ? schedule.map((r) => ({
      x: r.t, xanchor: "left", y: 1, yref: "paper", yanchor: "bottom", showarrow: false,
      text: label(r.values), font: { size: 12, color: "#5f5e57" },
    })) : [],
  };

  return (
    <div className="calc tvc-calc">
      <div className="calc-body">
        <div className="calc-main">
          {timeMode ? (
            <div className="calc-answer">
              <span>
                Age when {hasGiven ? <>the chance of surviving from <b>{ageWords(gNum)}</b></> : "reliability"} falls to{" "}
                <b>{rOk ? `${rCheck.percent.toLocaleString(undefined, { maximumFractionDigits: 6 })}%` : "—"}</b>
                {rOk && !hasGiven && Number.isInteger(Math.round((100 - rCheck.percent) * 1e6) / 1e6) ? ` (the B${100 - rCheck.percent} life)` : ""} on this schedule:
              </span>
              <span className="calc-answer-value">
                <b aria-live="polite">{life?.time != null ? fmtTime(life.time) : res && data.key === key ? "it doesn't fall that far on this schedule" : "—"}</b>
                {life?.further != null && <span className="calc-answer-ci"> (a further {fmtTime(life.further)})</span>}
                {lifeWords && <span className="calc-answer-ci"> — {lifeWords}</span>}
              </span>
            </div>
          ) : (
            <div className="calc-answer">
              <span>
                {hasGiven ? <>{QUESTION[active][1]} <b>{ageWords(gNum)}</b> {QUESTION[active][2]}</> : QUESTION[active][0]}{" "}
                <b>{ageWords(tNum)}</b> on this schedule:
              </span>
              <span className="calc-answer-value">
                <b aria-live="polite">{fmtFn(active, value)}</b>
                {words && <span className="calc-answer-ci"> — {words}</span>}
              </span>
            </div>
          )}
          {givenBad && <p className="hint tvc-msg">The age it has survived to must be 0 or more.</p>}
          {tBad && <p className="hint tvc-msg">Evaluate at an age after the {ageWords(gNum)} it has survived to.</p>}
          {timeMode && life && alpha != null && life.bound && life.time != null && !lifeWords && (
            <p className="muted-line tvc-msg">No bound on this age: the reliability's own bound doesn't fall to it.</p>
          )}
          {res?.warning && <p className="calc-warn">⚠ {res.warning}</p>}
          {body.error && <p className="hint tvc-msg">{body.error}</p>}
          {!body.error && data.key === key && data.error && <p className="hint tvc-msg">Couldn't evaluate the schedule: {data.error}</p>}
          {!path && <p className="muted-line tvc-msg">Open the model in Reliafy to change the schedule.</p>}
          {alpha != null && res && !res.bounds && res.bounds_note && <p className="muted-line tvc-msg">{res.bounds_note}</p>}
          <div className="tvc-plot">
            <Plot fill={fill} data={traces} layout={layout} download={`${name || result.distribution} — ${FUNCTIONS[active].axis} on a schedule`} />
          </div>
        </div>

        <div className="calc-side-rail">
          <div className="calc-rail-card calc-eval-card">
            <div className="gofh">Inputs</div>
            <div className="calc-eval-body">
              <SegmentedControl
                label="What to calculate" size="sm" className="calc-mode"
                value={timeMode ? "time" : "value"} onChange={(v) => set({ mode: v })}
                options={[
                  { value: "value", label: "At an age" },
                  { value: "time", label: "Time at reliability", title: "The age by which reliability falls to a level: R = 90% is the B10 life" },
                ]}
              />
              {timeMode ? (
                <>
                  <PercentField label="Reliability" value={String(state.rTarget ?? "")} onChange={(v) => set({ rTarget: v })} check={rCheck} />
                  <div className="chip-row calc-blives" role="group" aria-label="B-lives">
                    {B_LIVES.map(([r, b]) => (
                      <Chip key={b} tone={rOk && rCheck.percent === r ? "accent" : "neutral"} onClick={() => set({ rTarget: r })}
                            aria-pressed={rOk && rCheck.percent === r} title={`Reliability ${r}%: the ${b} life`}>
                        {b}
                      </Chip>
                    ))}
                  </div>
                </>
              ) : (
                <div className="tvc-pair">
                <label className="calc-t">
                  <span>Function</span>
                  <Select value={active} onChange={(v) => set({ active: v })}
                          options={Object.entries(FUNCTIONS).map(([id, f]) => ({ value: id, label: f.label }))} />
                </label>
                <label className="calc-t">
                  <span>At age{unit ? ` (${unitInText(unit)})` : ""}</span>
                  <input type="number" inputMode="decimal" min={0} step="any" value={t} onChange={(e) => set({ t: e.target.value })} />
                </label>
                </div>
              )}
              <label className="calc-t">
                <span>Given survived to age{unit ? ` (${unitInText(unit)})` : ""}</span>
                <input type="number" inputMode="decimal" min={0} step="any" placeholder="0 (a new unit)" value={given}
                       aria-invalid={givenBad || undefined} onChange={(e) => set({ given: e.target.value })} />
              </label>
              <div className="tvc-schedule" role="group" aria-label="Covariate schedule">
                <span className="tvc-schedule-h">Covariate schedule <span className="tvc-schedule-sub">· each row holds until the next</span></span>
                <ScrollCue className="tvc-table-wrap">
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
                              <input type="number" inputMode="decimal" min={0} step="any" aria-label={`Row ${k + 1} starts at`}
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
                </ScrollCue>
                {rows.length < MAX_ROWS && (
                  <button type="button" className="secondary sm tvc-add" onClick={addRow}>+ Add a change</button>
                )}
              </div>
              {hasBounds && (
                <div className="tvc-pair">
                  <label className="calc-t">
                    <span>Confidence bound</span>
                    <Select value={bound} onChange={(v) => set({ bound: v })} options={boundOptions(timeMode ? "time" : active)} />
                  </label>
                  {bound !== "none" && (
                    <PercentField label="Level" value={String(level ?? "")} onChange={(v) => set({ level: v })} check={levelCheck} />
                  )}
                </div>
              )}
            </div>
          </div>
          {!fill && !hasGiven && <div className="calc-rail-card calc-rail-params">
            <div className="gofh">Life on this schedule</div>
            <div className="gofr"><span className="gk">10% failed by (B10)</span><span className="gv">{fmtTime(b10)}</span></div>
            <div className="gofr"><span className="gk">Half failed by</span><span className="gv">{median != null ? fmtTime(median) : curves ? `after ${fmtTime(curves.x[curves.x.length - 1])}` : "—"}</span></div>
            {result.tvc?.mean && <div className="gofr"><span className="gk">Mean life</span><span className="gv">{fmtTime(res?.mean)}</span></div>}
          </div>}
        </div>
      </div>
    </div>
  );
}
