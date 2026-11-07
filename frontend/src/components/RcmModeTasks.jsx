import { useEffect, useRef, useState } from "react";
import { LevelIcon } from "./RcmWorksheet.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { INTERVAL_UNITS, startUnit } from "../decisionCheck.js";
import { OUTCOME_LABEL, addableOutcomes, decisionRows, decisionWithMember, everyText, isCombination, memberEvidenceText, tasksOf } from "../rcmWorksheet.js";
import { getTaskTriggerPoints } from "../api.js";
import { asksInterval, pointLabel, triggerBody, triggerState, triggerWhy } from "../taskTrigger.js";
import { secondTaskHint } from "../explorerRcm.js";
import { TaskMeasurementField } from "./TaskMeasurement.jsx";
import Chip from "./ui/Chip.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import Modal from "./Modal.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import { AddRow } from "./ui/Section.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";

// A failure mode's decision's tasks, inside its Decision section (the Explorer's
// RCM tab; Derryn, 8 Nov 2026: in RCM the decision is the choice of task, so
// they're one section). One row per member task: "<outcome> · <task name>",
// how often, whether other failure modes share it, its instructions, its own
// evidence (a combination's member), and its ⋯ (Edit…, which changes it in
// place: a shared task changes for every mode it serves; Remove…: a shared
// task is unlinked and stays, one serving this mode alone is retired). The
// dashed "Add another task" row at the end adds a member to the decision (a
// combination of tasks): one small dialog asks its kind first, then a new
// task's name and how often, or an existing task on the position or above it.
// With no decision, the tasks linked before it are rows under their own
// heading, and nothing is added here (Decide… first). Each write goes at once
// through `ops` (useTreeRcm) and the row is read again, so the list follows.
//
//   r         the failure mode's row (read afresh after each save)
//   ops       modeTasks, editTask, removeTask, decide; none: rows only
//   readOnly  rows without their ⋯ and no add row
//   addStart  a value that, when it changes, opens the add dialog (the row menu's Add a task…)
//   onSaid    (text) a few words in the page's status line once something's done

const SCHEDULED = ["on_condition", "fixed_interval", "failure_finding"];
const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;
// "every 6 months", or "on event: 120 mm on POOL-RAIN" for a task raised by an event.
const every = (t) => everyText(t);
const KIND_LABEL = { ...OUTCOME_LABEL, redesign: "Redesign (until the change is made)" };

export default function RcmModeTasks({ r, ops = null, readOnly = false, addStart = null, onSaid }) {
  const confirm = useConfirm();
  const d = r.ref.decision || null;
  const rows = decisionRows(d, tasksOf(r.ref));
  const [editing, setEditing] = useState(null); // the task being changed in place
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [adding, setAdding] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const can = !readOnly && !!ops;
  const addable = can && d ? addableOutcomes(d, r.ref) : [];
  // The row menu's Add a task…: the dialog, opened (when another task can join the decision).
  const opened = useRef(null);
  useEffect(() => {
    if (addStart == null || addStart === opened.current) return;
    opened.current = addStart;
    if (addable.length) setAdding(true);
  }, [addStart, addable.length]);

  const submitEdit = (task) => async (body) => {
    if (busy) return false;
    setBusy(true);
    setFailed(null);
    try {
      await ops.editTask(task.id, body);
      if (alive.current) { setBusy(false); setEditing(null); }
      onSaid?.("Saved the task.");
      return true;
    } catch (e) {
      if (alive.current) { setBusy(false); setFailed(saveErrorText(e, { offline: navigator.onLine === false })); }
      return false;
    }
  };

  const remove = async (t) => {
    const body = t.shared_with
      ? `“${t.name}” also serves ${plural(t.shared_with, "other failure mode")}, so it stays with them: only this failure mode comes off it.`
      : `“${t.name}” serves only this failure mode, so it is retired. It stays in the history and can be restored.`;
    const ok = await confirm({
      title: "Remove this task?", body, confirmLabel: t.shared_with ? "Remove from this failure mode" : "Retire the task",
      pendingLabel: "Removing…", failedWhat: "remove it", run: () => ops.removeTask(r, t).then(() => true),
    });
    if (ok) onSaid?.(t.shared_with ? "Removed the task from this failure mode." : "Retired the task.");
  };

  const combo = isCombination(d);
  if (!rows.length && !addable.length) return null;
  return (
    <div className="rim-tasks">
      {!d && rows.length > 0 && <h4 className="rim-before">Tasks linked before the decision</h4>}
      {rows.length > 0 && (
        <ul className="rim-tlist" aria-label={d ? "The decision's tasks" : "Tasks linked before the decision"}>
          {rows.map((row) => {
            const t = row.task;
            const word = row.outcome ? OUTCOME_LABEL[row.outcome] || row.outcome : null;
            if (!t) {
              // A member with no task now: a redesign (the interim tasks are the others), or a task that has gone.
              return (
                <li key={row.key} className="rim-card">
                  <div className="rim-chead">
                    <LevelIcon type="task" className="rw-ic rw-ic-task" />
                    <span className="rim-tname">{row.outcome === "redesign" ? KIND_LABEL.redesign : `${word} · no task now`}</span>
                  </div>
                  {combo && row.member?.status && <p className="rim-tev">Evidence: {memberEvidenceText(row.member)}</p>}
                </li>
              );
            }
            if (editing === t.id && can) {
              return (
                <li key={row.key} className="rim-card editing">
                  <TaskForm key={t.id} r={r} task={t} busy={busy} failed={failed}
                            onCancel={() => { setEditing(null); setFailed(null); }} onSubmit={submitEdit(t)} />
                </li>
              );
            }
            const name = t.text || t.name;
            return (
              <li key={row.key} className="rim-card">
                <div className="rim-chead">
                  <LevelIcon type="task" className="rw-ic rw-ic-task" />
                  <span className="rim-tname">{word ? <><span className="rim-tkind">{word}</span> · </> : null}{name}</span>
                  {can && (
                    <MoreMenu label={`Actions for ${t.name}`} disabled={busy} items={[
                      { id: "edit", label: "Edit…", onSelect: () => { setFailed(null); setEditing(t.id); } },
                      { id: "remove", label: t.shared_with ? "Remove from this failure mode…" : "Remove…", danger: true, onSelect: () => remove(t) },
                    ]} />
                  )}
                </div>
                {(every(t) || t.shared_with) ? (
                  <div className="rim-chips">
                    {every(t) && <Chip tone="accent">{every(t)}</Chip>}
                    {t.shared_with ? <Chip>Shared with {plural(t.shared_with, "other failure mode")}</Chip> : null}
                  </div>
                ) : null}
                {t.instructions && <Instructions text={t.instructions} />}
                {combo && row.member?.status && <p className="rim-tev">Evidence: {memberEvidenceText(row.member)}</p>}
              </li>
            );
          })}
        </ul>
      )}
      {addable.length > 0 && !editing && (
        <AddRow disabled={busy} onClick={() => setAdding(true)}>{rows.length ? "Add another task" : "Add a task"}</AddRow>
      )}
      {failed && !editing && <p className="field-error" role="alert">{failed}</p>}
      {adding && (
        <AddTaskDialog r={r} d={d} ops={ops} kinds={addable} onClose={() => setAdding(false)}
                       onDone={(said) => { setAdding(false); onSaid?.(said); }} />
      )}
    </div>
  );
}

// Another task for the decision (a combination of tasks), in one small dialog:
// its kind first, then a new task's name and how often (Enter adds it), or
// "Use an existing task…": one on this position or above it (read when asked
// for), which keeps its own interval for every mode it serves. A redesign
// needs no task: the others stand in until the change is made. Saved as the
// whole decision with the new member (ops.decide), so the members it has keep
// their tasks.
function AddTaskDialog({ r, d, ops, kinds, onClose, onDone }) {
  const [kind, setKind] = useState(kinds[0]);
  const [use, setUse] = useState("new"); // "new" | "existing"
  const [name, setName] = useState("");
  const [interval, setInterval_] = useState("");
  const [unit, setUnit] = useState(() => startUnit(d || {}));
  const [choices, setChoices] = useState(null);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [tried, setTried] = useState(false);
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  const scheduled = SCHEDULED.includes(kind);
  const nameBox = useRef(null);
  useEffect(() => {
    if (use !== "existing" || choices !== null) return undefined;
    let on = true;
    ops.modeTasks(r).then((out) => { if (on) setChoices(out.available || []); },
      (e) => { if (on) { setChoices([]); setFailed(saveErrorText(e, { offline: navigator.onLine === false })); } });
    return () => { on = false; };
  }, [use, choices, ops, r]);
  const n = Number(interval);
  const why = !scheduled ? null
    : use === "existing" ? (picked ? null : "Choose a task.")
      : !name.trim() ? "Name the task." : intervalWhy(interval) || null;
  const hint = scheduled && use === "new" ? secondTaskHint(r) : null;
  const here = r.ref.position_id;
  const save = async (e) => {
    e?.preventDefault();
    setTried(true);
    if (busy || why) return;
    const member = !scheduled ? { outcome: kind }
      : use === "existing" ? { outcome: kind, task_id: picked }
        : { outcome: kind, task: name.trim(), interval: n, interval_unit: unit };
    setBusy(true);
    setFailed(null);
    try {
      await ops.decide(r, { consequence: r.ref.consequence || null, decision: decisionWithMember(d, member) });
      onDone(use === "existing" && scheduled ? "Linked the task." : "Added the task.");
    } catch (err) {
      setBusy(false);
      setFailed(saveErrorText(err, { offline: navigator.onLine === false }));
    }
  };
  const formId = `rim-add-${r.key}`;
  return (
    <Modal title="Add another task" onClose={onClose} locked={busy} trapFocus className="rim-add"
           footer={(
             <>
               <button type="button" className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
               <button type="submit" form={formId} disabled={busy} aria-busy={busy || undefined}>
                 {busy ? "Saving…" : use === "existing" && scheduled ? "Link task" : "Add task"}
               </button>
             </>
           )}>
      <form id={formId} className="rim-tform rim-addform" onSubmit={save}>
        <p className="rw-fhelp">The decision becomes a combination of tasks: each one scheduled on its own.</p>
        <Field label="Kind of task">
          <ChoiceChips label="Kind of task" autoFocus value={kind} disabled={busy}
                       options={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] || k }))}
                       onChange={(v) => { if (v) setKind(v); }} />
        </Field>
        {!scheduled ? (
          <p className="rw-fhelp">A redesign needs no task here: the other task stands in until the change is made. Say what's to change in the decision notes.</p>
        ) : use === "new" ? (
          <>
            <Field label="Task" help={hint}>
              <TextInput ref={nameBox} value={name} readOnly={busy} placeholder="e.g. Replace the acid pump"
                         aria-invalid={tried && !name.trim() ? "true" : undefined} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Every" as="fieldset">
              <InputGroup label="Every">
                <TextInput type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={busy} aria-label="Interval"
                           aria-invalid={tried && intervalWhy(interval) ? "true" : undefined} placeholder="e.g. 6"
                           onChange={(e) => setInterval_(e.target.value)} />
                <Select value={unit} disabled={busy} aria-label="Interval unit" onChange={(e) => setUnit(e.target.value)}>
                  {units.map((u) => <option key={u} value={u}>{u}</option>)}
                </Select>
              </InputGroup>
            </Field>
            <button type="button" className="link rim-use" disabled={busy} onClick={() => { setFailed(null); setUse("existing"); }}>
              Use an existing task…
            </button>
          </>
        ) : (
          <>
            <p className="rw-fhelp">A task on this position, or on a position above it, can serve this failure mode too. It keeps its own interval for every mode it serves.</p>
            {choices === null ? <p className="rw-fhelp">Reading the tasks…</p> : choices.length === 0 ? (
              <p className="rw-fhelp">No other task on this position or above it. Write a new task instead.</p>
            ) : (
              <Field label="Task">
                <Select value={picked} disabled={busy} onChange={(e) => setPicked(e.target.value)} aria-label="Existing task">
                  <option value="">Choose a task…</option>
                  {choices.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}{every(t) ? ` · ${every(t)}` : ""}{t.position?.id !== here ? ` · on ${t.position?.name}` : ""}{t.serves ? ` · serves ${plural(t.serves, "failure mode")}` : ""}
                    </option>
                  ))}
                </Select>
              </Field>
            )}
            <button type="button" className="link rim-use" disabled={busy} onClick={() => { setFailed(null); setUse("new"); }}>
              Write a new task instead
            </button>
          </>
        )}
        {tried && why && !busy && <p className="rim-why">{why}</p>}
        {failed && <p className="field-error" role="alert">{failed}</p>}
      </form>
    </Modal>
  );
}

// The reason an interval can't be kept ("" when it can).
function intervalWhy(raw) {
  const n = Number(raw);
  if (String(raw).trim() === "") return "Enter how often: an interval above 0.";
  return Number.isFinite(n) && n > 0 ? "" : "Enter an interval above 0.";
}

// Changing a task (its ⋯ Edit…): its name, what raises it (Trigger: every
// interval, or when an event happens: a reading past a limit, or an event
// logged by name; taskTrigger.js), interval and unit, what kind of
// task it is, its instructions; a task by use being changed, its measurement
// (what it counts, with the last-done reading on a new one). Saved once (the button says so until the
// server answers); a refusal shows here with everything as typed.
function TaskForm({ r, task, busy, failed, onCancel, onSubmit }) {
  const d = r.ref.decision;
  const [name, setName] = useState(task?.name || "");
  const [interval, setInterval_] = useState(task?.interval != null ? String(task.interval) : "");
  const [unit, setUnit] = useState(task?.unit || startUnit(d || {}));
  const [outcome, setOutcome] = useState(task?.outcome || (d && SCHEDULED.includes(d.outcome) ? d.outcome : ""));
  const [instructions, setInstructions] = useState(task?.instructions || "");
  const [meas, setMeas] = useState({ body: null, error: null });
  const [trig, setTrig] = useState(() => triggerState(task));
  const setT = (k) => (e) => setTrig((x) => ({ ...x, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const [points, setPoints] = useState(null);
  useEffect(() => {
    if (trig.mode !== "event" || trig.by !== "reading" || points || !task?.id) return undefined;
    let on = true;
    getTaskTriggerPoints(task.id).then((out) => { if (on) setPoints(out.points || []); }, () => { if (on) setPoints([]); });
    return () => { on = false; };
  }, [trig.mode, trig.by, points, task?.id]);
  const nameBox = useRef(null);
  useEffect(() => {
    // Focused, its start in view (a long name isn't shown scrolled to its end).
    const el = nameBox.current;
    el?.focus();
    if (el) el.scrollLeft = 0;
  }, []);
  const n = Number(interval);
  const timed = asksInterval(trig);
  const intervalOk = !timed || (interval.trim() !== "" && Number.isFinite(n) && n > 0);
  const can = !!name.trim() && intervalOk && !triggerWhy(trig) && !busy && !meas.error;
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  const why = busy ? null : !name.trim() ? "Name the task first."
    : timed && interval.trim() === "" ? "Enter how often: an interval above 0."
    : !intervalOk ? "Enter an interval above 0." : triggerWhy(trig) || (meas.error ? "Settle the measurement first." : null);
  return (
    <form className="rim-tform" onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit({ name: name.trim(), ...(timed ? { interval: n, unit } : {}), outcome: outcome || null,
        instructions: instructions.trim(), ...(timed ? meas.body || {} : {}), trigger: triggerBody(trig) });
    }}>
      <h4>Change the task</h4>
      {task?.shared_with ? (
        <p className="rw-fhelp">It also serves {plural(task.shared_with, "other failure mode")}: the change applies to all of them.</p>
      ) : null}
      <Field label="Task">
        <TextInput ref={nameBox} value={name} readOnly={busy} placeholder="What to do, e.g. Replace the acid pump"
                   onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Trigger">
        <Select value={trig.mode} disabled={busy} onChange={setT("mode")}>
          <option value="interval">Every interval</option>
          <option value="event">When an event happens</option>
        </Select>
      </Field>
      {trig.mode === "event" && (
        <fieldset className="rim-trigger">
          <legend className="sr-only">The event</legend>
          <Field label="What happens">
            <Select value={trig.by} disabled={busy} onChange={setT("by")}>
              <option value="reading">A reading passes a limit</option>
              <option value="name">Someone logs an event</option>
            </Select>
          </Field>
          {trig.by === "reading" ? (
            <div className="rim-trow">
              <Field label="Measuring point">
                <Select value={trig.pointId} disabled={busy || points === null} onChange={setT("pointId")}>
                  <option value="">{points === null ? "Reading the points…" : points.length ? "Choose a point…" : "No condition points nearby"}</option>
                  {(points || []).map((p) => <option key={p.id} value={p.id}>{pointLabel(p)}</option>)}
                </Select>
              </Field>
              <Field label="Limit" as="fieldset">
                <InputGroup label="Limit">
                  <Select value={trig.side} disabled={busy} aria-label="Above or below" onChange={setT("side")}>
                    <option value="above">At or above</option>
                    <option value="below">At or below</option>
                  </Select>
                  <TextInput type="number" inputMode="decimal" step="any" value={trig.limit} readOnly={busy}
                             aria-label="Limit" placeholder="e.g. 120" onChange={setT("limit")} />
                </InputGroup>
              </Field>
            </div>
          ) : (
            <Field label="Event name" help="Logged on this position, or one above it, from its ⋯ menu: Log an event…">
              <TextInput value={trig.eventType} readOnly={busy} placeholder="e.g. Lightning strike" onChange={setT("eventType")} />
            </Field>
          )}
          <label className="rim-check">
            <input type="checkbox" checked={trig.withInterval} disabled={busy} onChange={setT("withInterval")} />
            Keep the interval too (whichever comes first)
          </label>
          {!trig.withInterval && <p className="rw-fhelp">It waits for the event: never overdue, and each event raises one work order.</p>}
        </fieldset>
      )}
      <div className="rim-trow">
        {timed && <Field label="Every" as="fieldset" error={interval.trim() !== "" && !(Number.isFinite(n) && n > 0) ? "Enter an interval above 0." : null}>
          <InputGroup label="Every">
            <TextInput type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={busy} aria-label="Interval"
                       onChange={(e) => setInterval_(e.target.value)} />
            <Select value={unit} disabled={busy} aria-label="Interval unit" onChange={(e) => setUnit(e.target.value)}>
              {units.map((u) => <option key={u} value={u}>{u}</option>)}
            </Select>
          </InputGroup>
        </Field>}
        <Field label="Kind of task">
          <Select value={outcome} disabled={busy} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Routine work</option>
            {SCHEDULED.map((o) => <option key={o} value={o}>{OUTCOME_LABEL[o]}</option>)}
          </Select>
        </Field>
      </div>
      {task?.id && timed && (
        <TaskMeasurementField taskId={task.id} unit={unit} disabled={busy} onChange={(body, error) => setMeas({ body, error })} />
      )}
      {meas.error && <p className="field-error" role="alert">{meas.error}</p>}
      <Field label="Instructions" optional>
        <TextArea value={instructions} readOnly={busy} onChange={(e) => setInstructions(e.target.value)} />
      </Field>
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        {why && <p className="rim-why">{why}</p>}
        <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="sm" disabled={!can} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save task"}</button>
      </div>
    </form>
  );
}

// A task's instructions: two lines, with "Show all" when there's more.
function Instructions({ text }) {
  const [open, setOpen] = useState(false);
  const [long, setLong] = useState(false);
  const box = useRef(null);
  useEffect(() => {
    const el = box.current;
    if (el && !open) setLong(el.scrollHeight > el.clientHeight + 1);
  }, [text, open]);
  return (
    <>
      <span ref={box} className={"rim-tinst" + (open ? "" : " clamped")}>{text}</span>
      {(long || open) && (
        <button type="button" className="link rim-tmore" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </>
  );
}
