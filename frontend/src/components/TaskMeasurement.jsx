import { useEffect, useRef, useState } from "react";
import { getTaskMeasurement } from "../api.js";
import { FormModal, fmtDate } from "./MaintenanceParts.jsx";
import {
  RELATION_WORDS, atLastDoneText, checkChoice, choiceBody, choiceLabel, fieldBody, measurementLines, pointLabel,
  readingText, startChoice,
} from "../taskMeasurement.js";
import "./TaskMeasurement.css";

const CALENDAR_UNITS = ["days", "weeks", "months", "years"];

// The reading a task had when it was last done, on a measurement it's about
// to count: worked out from the date (the server estimates it from that
// measurement's readings, and marks it an estimate), or typed in.
function LastDoneReading({ name, lastDone, unit, estimate, mode, value, disabled, onMode, onValue }) {
  return (
    <fieldset className="tm-reading">
      <legend>Its reading when it was last done ({fmtDate(lastDone)})</legend>
      <label className="tm-opt">
        <input type="radio" name={`${name}-reading`} checked={mode === "estimate"} disabled={disabled}
               onChange={() => onMode("estimate")} />
        <span>Work it out from the date{estimate ? `: ${estimate}` : ""} <span className="tm-help">(marked as an estimate)</span></span>
      </label>
      <label className="tm-opt tm-enter">
        <input type="radio" name={`${name}-reading`} checked={mode === "enter"} disabled={disabled}
               onChange={() => onMode("enter")} />
        <span>Enter it</span>
        {mode === "enter" && (
          <span className="tm-num">
            <input type="number" inputMode="decimal" step="any" value={value} disabled={disabled} autoFocus
                   aria-label={`Reading when it was last done, in ${unit}`} onChange={(e) => onValue(e.target.value)} />
            <span>{unit}</span>
          </span>
        )}
      </label>
    </fieldset>
  );
}

// The Measurement field in a task's dialog (the RCM tab's failure mode dialog,
// a position's or an item's Tasks): what the task counts, its latest reading
// and the last-done reading; Change… picks another measurement in the task's
// unit (on the position, above or below it, or on the fitted item; an item's
// task: the item's own), with the last-done reading on it. Nothing shows for a
// task on the calendar. `onChange(body, error)`: the task update's
// {point_id, last_done_reading?} (null: no change), and what's missing.
export function TaskMeasurementField({ taskId, unit, disabled = false, onChange }) {
  const [view, setView] = useState(null);
  const [failed, setFailed] = useState(null);
  const [editing, setEditing] = useState(false);
  const [pick, setPick] = useState("");
  const [readingMode, setReadingMode] = useState("estimate");
  const [reading, setReading] = useState("");
  const report = useRef(onChange);
  report.current = onChange;

  useEffect(() => {
    let live = true;
    getTaskMeasurement(taskId).then((v) => {
      if (!live) return;
      setView(v);
      setPick(v.chosen ? v.measurement?.id || "" : "");
    }, (e) => live && setFailed(e.message || "Couldn't read what it counts."));
    return () => { live = false; };
  }, [taskId]);

  useEffect(() => {
    if (!view || !editing) return report.current?.(null, null);
    const body = fieldBody(view, pick, readingMode, reading);
    const bad = body && view.last_done && readingMode === "enter" && !Number.isFinite(body.last_done_reading)
      ? "Enter the reading when it was last done, or work it out from the date." : null;
    return report.current?.(body, bad);
  }, [view, editing, pick, readingMode, reading]);

  if (failed) return <p className="tm-help tm-err" role="alert">{failed}</p>;
  if (!view) return <p className="tm-help">Reading what it counts…</p>;
  if (!view.by_use) return null;
  const lines = measurementLines(view, fmtDate);
  const relation = view.measurement?.relation && view.measurement.relation !== "here" ? RELATION_WORDS[view.measurement.relation] : "";
  const isItem = view.subject?.kind === "item";
  const auto = isItem ? `Automatic: its own ${view.unit} counter, else its use where fitted` : `Automatic: this position's ${view.unit} counter`;
  const was = view.chosen ? view.measurement?.id || "" : "";
  const picked = view.choices.find((c) => c.id === pick)
    || (pick === "" ? view.choices.find((c) => c.relation === "here" && c.on?.id === view.subject?.id) : null);
  const norm = (u) => String(u || "").trim().toLowerCase().replace(/s$/, "");
  const unitChanged = !!unit && norm(unit) !== norm(view.unit);
  return (
    <fieldset className="tm-field">
      <legend>Measurement</legend>
      <p className="tm-counts">{lines.counts}{relation && <span className="tm-help"> ({relation})</span>}</p>
      {lines.reads && <p className="tm-help">{lines.reads}</p>}
      {lines.lastDone && <p className="tm-help">{lines.lastDone}</p>}
      {unitChanged ? (
        <p className="tm-help">Save the new unit first, then pick the measurement in it.</p>
      ) : !editing ? (
        <button type="button" className="link tm-change" disabled={disabled} onClick={() => setEditing(true)}>
          Change the measurement…
        </button>
      ) : (
        <div className="tm-edit">
          <label className="tm-label">
            <span>Count</span>
            <select value={pick} disabled={disabled} onChange={(e) => setPick(e.target.value)} aria-label="Measurement to count">
              <option value="">{auto}</option>
              {view.choices.map((c) => <option key={c.id} value={c.id}>{choiceLabel(c)}</option>)}
            </select>
          </label>
          {!view.choices.length && (
            <p className="tm-help">No other {view.unit} counter on this position, above or below it, or on the fitted item. Add one on the position first.</p>
          )}
          {view.last_done && pick !== was && (
            <LastDoneReading name={`tm-${taskId}`} lastDone={view.last_done} unit={view.unit} estimate={atLastDoneText(picked, view.unit)}
                             mode={readingMode} value={reading} disabled={disabled} onMode={setReadingMode} onValue={setReading} />
          )}
          <button type="button" className="link" disabled={disabled}
                  onClick={() => { setEditing(false); setPick(was); setReadingMode("estimate"); setReading(""); }}>
            Keep the measurement as it is
          </button>
        </div>
      )}
    </fieldset>
  );
}

// One task's question in the move dialog: its measurement isn't on the new
// position, above or below it, or on the item fitted there.
function MoveChoice({ view, there, state, many, disabled, onState }) {
  const id = `tmm-${view.task_id}`;
  const set = (k) => (v) => onState({ ...state, [k]: v });
  const now = view.measurement;
  const picked = view.choices.find((c) => c.id === state.pointId);
  return (
    <fieldset className="tm-task">
      <legend className={many ? "" : "sr-only"}>{view.name}</legend>
      <p className="tm-now">
        {now
          ? <>“{view.name}” goes by {view.unit} and counts {pointLabel(now)}, which isn't on {there}, a position above or below it, or the item fitted there.</>
          : <>“{view.name}” goes by {view.unit}, and its last-done reading came from a counter it no longer counts.</>}
        {view.last_done && view.last_done_reading != null ? <> Last done {fmtDate(view.last_done)} at {readingText(view.last_done_reading, view.unit)}.</> : null}
      </p>
      <label className="tm-opt">
        <input type="radio" name={id} checked={state.mode === "switch"} disabled={disabled || !view.choices.length}
               onChange={() => set("mode")("switch")} />
        <span>Count a measurement on {there} instead</span>
      </label>
      {!view.choices.length && (
        <p className="tm-help tm-sub">{there} has no {view.unit} counter, and nor do the positions above or below it. Add one there first, or choose below.</p>
      )}
      {state.mode === "switch" && view.choices.length > 0 && (
        <div className="tm-sub">
          <select value={state.pointId} disabled={disabled} onChange={(e) => set("pointId")(e.target.value)}
                  aria-label={`Measurement for ${view.name} to count`}>
            {view.choices.map((c) => <option key={c.id} value={c.id}>{choiceLabel(c)}</option>)}
          </select>
          {view.last_done && (
            <LastDoneReading name={id} lastDone={view.last_done} unit={view.unit} estimate={atLastDoneText(picked, view.unit)}
                             mode={state.readingMode} value={state.reading} disabled={disabled}
                             onMode={set("readingMode")} onValue={set("reading")} />
          )}
        </div>
      )}
      <label className="tm-opt">
        <input type="radio" name={id} checked={state.mode === "keep"} disabled={disabled} onChange={() => set("mode")("keep")} />
        <span>{now ? `Keep counting ${pointLabel(now)}` : "Keep it as it is"}</span>
      </label>
      <label className="tm-opt">
        <input type="radio" name={id} checked={state.mode === "calendar"} disabled={disabled} onChange={() => set("mode")("calendar")} />
        <span>Go by calendar time instead</span>
      </label>
      {state.mode === "calendar" && (
        <div className="tm-sub tm-num">
          <span>Every</span>
          <input type="number" inputMode="decimal" min="0" step="any" value={state.interval} disabled={disabled} autoFocus
                 aria-label={`How often ${view.name} falls due`} onChange={(e) => set("interval")(e.target.value)} />
          <select value={state.calendarUnit} disabled={disabled} aria-label="Calendar unit" onChange={(e) => set("calendarUnit")(e.target.value)}>
            {CALENDAR_UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      )}
    </fieldset>
  );
}

// The question a move asks when what its tasks by use count isn't on the new
// position, above or below it, or on the item fitted there (Truck 12's engine
// hours, moving to Truck 14): for each task, count a measurement there (the
// position's own in that unit picked first), keep the old one, or go by the
// calendar. `need`: the move's needs_choice; `onChoose(measurement)` sends the
// move again with it ({task_id: choice}); `onCancel()` leaves it where it is.
export function MeasurementMoveModal({ need, onChoose, onCancel }) {
  const tasks = need?.tasks || [];
  const [states, setStates] = useState(() => Object.fromEntries(tasks.map((t) => [t.task_id, startChoice(t)])));
  const there = need?.position?.name || "the new position";
  const many = tasks.length > 1;
  return (
    <FormModal title={many ? `What should these tasks count on ${there}?` : `What should it count on ${there}?`}
           submitLabel="Move" pendingLabel="Moving…" onClose={onCancel}
           onSubmit={async () => {
             const bad = tasks.map((t) => checkChoice(states[t.task_id], t)).find(Boolean);
             if (bad) throw new Error(bad);
             await onChoose(Object.fromEntries(tasks.map((t) => [t.task_id, choiceBody(states[t.task_id], t)])));
           }}>
      <div className="tm-move">
        <p className="tm-help">
          A measurement belongs to the position it describes. Say what {many ? "each task" : "the task"} should count once it moves, so
          its next due date stays right.
        </p>
        {tasks.map((t) => (
          <MoveChoice key={t.task_id} view={t} there={there} many={many} state={states[t.task_id]}
                      onState={(s) => setStates((was) => ({ ...was, [t.task_id]: s }))} />
        ))}
      </div>
    </FormModal>
  );
}
