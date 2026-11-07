import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { DEFAULT_OUTCOMES, INTERVAL_UNITS, TASK_ORDER, modeAnswers, startUnit } from "../decisionCheck.js";
import {
  OUTCOME_LABEL, addableOutcomes, decisionCardLines, decisionRows, decisionWithFirstTask, decisionWithMember, decisionWithOutcome,
  everyText, isCombination, tasksDropped, tasksOf,
} from "../rcmWorksheet.js";
import { getTaskTriggerPoints } from "../api.js";
import { asksInterval, pointLabel, triggerBody, triggerState, triggerWhy } from "../taskTrigger.js";
import { secondTaskHint } from "../explorerRcm.js";
import { explorerPath } from "../assetTree.js";
import { TaskMeasurementField } from "./TaskMeasurement.jsx";
import TaskChoice from "./TaskChoice.jsx";
import Chip from "./ui/Chip.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";

// Step 3 of a failure mode's details, "Proactive task or default action" (the
// Explorer's RCM tab), edited in place like step 2 (Derryn, 9 Nov 2026: the
// card's ⋯ asked the step-2 questions again in a dialog; it's gone). Top to
// bottom:
//
// 1. "Which task is worth doing?" (TaskChoice, shared with the decision
//    dialog): the kinds the RCM decision diagram allows for the mode's two
//    answers, then "No task is worth doing" (its default actions, and run to
//    failure's reason). One tap saves the whole decision (its notes and
//    evidence kept; the task it has kept when the kind of task changes); a
//    second tap on the chosen chip clears it. A change that takes tasks off
//    the mode asks first, naming them. Until step 2 is answered the chips are
//    shown but disabled, with why.
// 2. The tasks, as cards: each with its kind, name and how often, its chips
//    (shared, its work package) and instructions, and plain Edit and Remove
//    links at its right (Edit changes it in place: a shared task changes for
//    every mode it serves; Remove unlinks a shared task, retires one serving
//    this mode alone). A scheduled decision with no task yet shows the task
//    form instead (a new task's name and how often, Enter saves; or "Use an
//    existing task…": one on this position or above it). Run to failure shows
//    what's done on failure (`own`). "+ Add another task" (dashed) only when
//    the rules allow a combination and a task exists: its kind, then the form.
// 3. "Evidence and rationale", open: the evidence line and the decision notes
//    (`why`, built by Details: Link evidence… opens the evidence picker alone).
//
// No decision and tasks linked before: those tasks under their own heading.
// Each write goes at once through `ops` (useTreeRcm) and the row is read
// again, so the step follows.
//
//   r         the failure mode's row (read afresh after each save)
//   ops       modeTasks, editTask, removeTask, decide; none: the chips disabled
//   readOnly  no edits at all
//   options   the server's RCM options (labels, hints, run-to-failure reasons)
//   why       the evidence line and the decision notes (shown with a decision)
//   own       run to failure's "What's done on failure" field
//   addStart  a value that, when it changes, opens "Add another task" (the row menu's Add a task…)
//   onSaid    (text) a few words in the page's status line once something's done

const SCHEDULED = ["on_condition", "fixed_interval", "failure_finding"];
const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;
// "every 6 months", or "on event: 120 mm on POOL-RAIN" for a task raised by an event.
const every = (t) => everyText(t);
const KIND_LABEL = { ...OUTCOME_LABEL, redesign: "Redesign (until the change is made)" };
const LOCKED = "Answer step 2 first: what's worth doing depends on the consequence.";
const fromDecision = (d) => ({
  outcome: d?.outcome || null, noTask: DEFAULT_OUTCOMES.includes(d?.outcome), rtfBasis: d?.rtf_basis || null,
});
// What a confirm says about the tasks a change takes off the failure mode.
function droppedWords(going) {
  return going.map((t) => (t.shared_with
    ? `“${t.name}” also serves ${plural(t.shared_with, "other failure mode")}, so it stays with them: only this failure mode comes off it.`
    : `“${t.name}” serves only this failure mode, so it is retired. It stays in the history and can be restored.`)).join(" ");
}

export default function RcmModeTasks({
  r, ops = null, readOnly = false, addStart = null, onSaid, options = null, why = null, own = null,
}) {
  const confirm = useConfirm();
  const d = r.ref.decision || null;
  const tasks = tasksOf(r.ref);
  const answers = modeAnswers(r.ref);
  const answered = !!answers.consequence;
  const can = !readOnly && !!ops?.decide;
  const cards = d
    ? decisionCardLines(d, tasks).filter((l) => l.task || l.member)
    : decisionRows(null, tasks).map((row) => ({
      key: row.key, kind: null, name: row.task.text || row.task.name, every: everyText(row.task) || null, task: row.task, member: null,
    }));
  const [pick, setPick] = useState(() => fromDecision(d));
  const [editing, setEditing] = useState(null); // the task being changed in place
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [adding, setAdding] = useState(false);
  const [saved, setSaved] = useState(0);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  // Another failure mode: everything starts again. The same one read again: the choice follows
  // the decision (a pending "No task is worth doing" stays while none is saved).
  const keyWas = useRef(r.key);
  useEffect(() => {
    if (keyWas.current !== r.key) {
      keyWas.current = r.key;
      setPick(fromDecision(d)); setEditing(null); setAdding(false); setFailed(null); setSaved(0);
      return;
    }
    setPick((p) => (d ? fromDecision(d) : { outcome: null, noTask: p.noTask && !TASK_ORDER.includes(p.outcome), rtfBasis: null }));
  }, [r.key, d?.outcome, d?.rtf_basis]); // eslint-disable-line react-hooks/exhaustive-deps
  const addable = can && d ? addableOutcomes(d, r.ref) : [];
  const canAdd = addable.length > 0 && tasks.some((t) => t.id);
  // The row menu's Add a task…: "Add another task" opened (when another task can join the decision).
  const opened = useRef(null);
  useEffect(() => {
    if (addStart == null || addStart === opened.current) return;
    opened.current = addStart;
    if (canAdd) setAdding(true);
  }, [addStart, canAdd]);
  const needsFirst = can && d && !isCombination(d) && SCHEDULED.includes(d.outcome) && !tasks.some((t) => t.id);
  const decide = (decision) => ops.decide(r, { consequence: r.ref.consequence || null, decision });
  const errorText = (e) => saveErrorText(e, { offline: navigator.onLine === false });

  // A tap in "Which task is worth doing?": saved when it makes a whole decision (run to failure
  // waits for its reason); "No task is worth doing" alone waits for what's done instead.
  const choose = async (next) => {
    if (busy || !can) return;
    const prev = pick;
    setPick(next);
    setFailed(null);
    let target; // the outcome to save; null clears the decision; undefined saves nothing
    if (next.outcome && (next.outcome !== "rtf" || next.rtfBasis)) target = next.outcome;
    else if (!next.outcome && !next.noTask) target = d ? null : undefined;
    else if (next.noTask && !next.outcome && d && DEFAULT_OUTCOMES.includes(d.outcome)) target = null;
    if (target === undefined) return;
    const decision = target ? decisionWithOutcome(d, tasks, target, next.rtfBasis) : null;
    const going = tasksDropped(d, tasks, target);
    const said = target ? "Saved the decision." : "Cleared the decision.";
    if (going.length) {
      const ok = await confirm({
        title: target ? "Change the decision?" : "Clear the decision?",
        body: `${target ? "The new decision schedules no task for" : "With no decision, nothing is scheduled for"} ${going.length === 1 ? "this task" : "these tasks"}. ${droppedWords(going)}`,
        confirmLabel: target ? "Change the decision" : "Clear the decision",
        pendingLabel: "Saving…", failedWhat: "save it", run: () => decide(decision).then(() => true),
      });
      if (!alive.current) return;
      if (!ok) { setPick(prev); return; }
    } else {
      setBusy(true);
      try {
        await decide(decision);
      } catch (e) {
        if (alive.current) { setBusy(false); setPick(prev); setFailed(errorText(e)); }
        return;
      }
      if (!alive.current) return;
      setBusy(false);
    }
    setSaved((n) => n + 1);
    onSaid?.(said);
  };

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
      if (alive.current) { setBusy(false); setFailed(errorText(e)); }
      return false;
    }
  };

  const remove = async (t) => {
    const ok = await confirm({
      title: "Remove this task?", body: droppedWords([t]), confirmLabel: t.shared_with ? "Remove from this failure mode" : "Retire the task",
      pendingLabel: "Removing…", failedWhat: "remove it", run: () => ops.removeTask(r, t).then(() => true),
    });
    if (ok) onSaid?.(t.shared_with ? "Removed the task from this failure mode." : "Retired the task.");
  };

  const card = (l) => {
    const t = l.task;
    if (t && editing === t.id && can) {
      return (
        <li key={l.key} className="rim-line rim-card editing">
          <TaskForm key={t.id} r={r} task={t} busy={busy} failed={failed}
                    onCancel={() => { setEditing(null); setFailed(null); }} onSubmit={submitEdit(t)} />
        </li>
      );
    }
    return (
      <li key={l.key} className="rim-line rim-card">
        <div className="rim-chead">
          <span className="rim-tname">
            {l.kind && <span className="rim-tkind">{l.kind}</span>}
            {l.kind && (l.name || l.every) ? " · " : null}
            {l.name}
            {l.name && l.every ? " · " : null}
            {l.every && <span className="rim-tevery">{l.every}</span>}
          </span>
          {t?.id && can && (
            <span className="rim-tacts">
              <button type="button" className="link" disabled={busy} aria-label={`Edit “${t.name}”`}
                      onClick={() => { setFailed(null); setAdding(false); setEditing(t.id); }}>Edit</button>
              <button type="button" className="link" disabled={busy}
                      aria-label={t.shared_with ? `Remove “${t.name}” from this failure mode` : `Remove “${t.name}”`}
                      onClick={() => remove(t)}>Remove</button>
            </span>
          )}
        </div>
        {t && (t.shared_with || t.package) ? (
          <span className="rim-chips">
            {t.shared_with ? <Chip>Shared with {plural(t.shared_with, "other failure mode")}</Chip> : null}
            {t.package && (
              <Link className="chip chip-neutral chip-btn" title="Done on this work package's visits: open it on the Packages tab"
                    to={explorerPath(t.package.subject?.kind === "location" ? "locations" : "positions",
                                     { sel: t.package.subject?.id, tab: "packages", package: t.package.id })}>
                In: {t.package.name}
              </Link>
            )}
          </span>
        ) : null}
        {t?.instructions && <Instructions text={t.instructions} />}
      </li>
    );
  };

  return (
    <div className={"rim-step" + (editing ? " has-edit" : "")}>
      <TaskChoice options={options} hidden={answers.hidden} consequence={answers.consequence} value={pick} onChange={choose}
                  disabled={!can || !answered || busy} locked={answered ? null : LOCKED} moveOnly saved={saved} />
      {failed && !editing && <p className="field-error" role="alert">{failed}</p>}
      {d?.outcome === "rtf" && own && <div className="rim-own">{own}</div>}
      {needsFirst && (
        <NewTaskForm key={`${r.key}:${d.outcome}`} r={r} d={d} ops={ops} kind={d.outcome}
                     intro="The decision schedules work, but no task does it yet: give it a task and an interval."
                     start={{ name: d.task || "", interval: d.interval ?? "" }}
                     onSave={(member) => decide(decisionWithFirstTask(d, member))}
                     onDone={(said) => { setSaved((n) => n + 1); onSaid?.(said); }} />
      )}
      {d && cards.length > 0 && <ul className="rim-lines rim-cards" aria-label="The decision's tasks">{cards.map(card)}</ul>}
      {!d && cards.length > 0 && (
        <>
          <h4 className="rim-before">Tasks linked before the decision</h4>
          <ul className="rim-lines rim-cards" aria-label="Tasks linked before the decision">{cards.map(card)}</ul>
        </>
      )}
      {canAdd && !editing && (adding ? (
        <div className="rim-card rim-adding" role="group" aria-label="Add another task">
          <NewTaskForm r={r} d={d} ops={ops} kinds={addable} title="Add another task"
                       intro="The decision becomes a combination of tasks: each one scheduled on its own."
                       onSave={(member) => decide(decisionWithMember(d, member))}
                       onCancel={() => setAdding(false)}
                       onDone={(said) => { setAdding(false); onSaid?.(said); }} />
        </div>
      ) : (
        <button type="button" className="rim-addrow" disabled={busy} onClick={() => { setFailed(null); setAdding(true); }}>
          + Add another task
        </button>
      ))}
      {d && why && (
        <div className="rim-whyopen" role="group" aria-labelledby={`rim-why-${r.key}`}>
          <h4 className="rim-before" id={`rim-why-${r.key}`}>Evidence and rationale</h4>
          {why}
        </div>
      )}
    </div>
  );
}

// A task for the decision, in place: with `kinds` (another task for a
// combination) its kind first as chips; then a new task's name and how often
// (Enter saves), or "Use an existing task…": one on this position or above it
// (read when asked for), which keeps its own interval for every mode it
// serves. A redesign needs no task: the others stand in until the change is
// made. `onSave(member)` writes it ({outcome, task, interval, interval_unit},
// {outcome, task_id} or {outcome}) and returns a promise; a refusal shows here
// with everything as typed. Escape cancels (when it can be cancelled).
function NewTaskForm({ r, d, ops, kind: fixed = null, kinds = null, title = null, intro = null, start = {}, onSave, onCancel = null, onDone }) {
  const [kind, setKind] = useState(fixed || kinds?.[0]);
  const [use, setUse] = useState("new"); // "new" | "existing"
  const [name, setName] = useState(start.name || "");
  const [interval, setInterval_] = useState(start.interval != null ? String(start.interval) : "");
  const [unit, setUnit] = useState(() => startUnit(d || {}));
  const [choices, setChoices] = useState(null);
  const [picked, setPicked] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [tried, setTried] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  const scheduled = SCHEDULED.includes(kind);
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
  const hint = kinds && scheduled && use === "new" ? secondTaskHint(r) : null;
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
      await onSave(member);
      if (alive.current) setBusy(false);
      onDone?.(use === "existing" && scheduled ? "Linked the task." : "Added the task.");
    } catch (err) {
      if (!alive.current) return;
      setBusy(false);
      setFailed(saveErrorText(err, { offline: navigator.onLine === false }));
    }
  };
  return (
    <form className="rim-tform rim-addform" onSubmit={save}
          onKeyDown={(e) => {
            if (e.key !== "Escape" || !onCancel || busy) return;
            e.preventDefault();
            e.stopPropagation(); // the form closes, not the panel
            onCancel();
          }}>
      {title && <h4>{title}</h4>}
      {intro && <p className="rw-fhelp">{intro}</p>}
      {kinds && (
        <Field label="Kind of task">
          <ChoiceChips label="Kind of task" autoFocus value={kind} disabled={busy}
                       options={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] || k }))}
                       onChange={(v) => { if (v) setKind(v); }} />
        </Field>
      )}
      {!scheduled ? (
        <p className="rw-fhelp">A redesign needs no task here: the other task stands in until the change is made. Say what's to change in the decision notes.</p>
      ) : use === "new" ? (
        <>
          <Field label="Task" help={hint}>
            <TextInput value={name} readOnly={busy} placeholder="e.g. Replace the acid pump"
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
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        {tried && why && !busy && <p className="rim-why">{why}</p>}
        {onCancel && <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>}
        <button type="submit" className="sm" disabled={busy} aria-busy={busy || undefined}>
          {busy ? "Saving…" : use === "existing" && scheduled ? "Link task" : "Save"}
        </button>
      </div>
    </form>
  );
}

// The reason an interval can't be kept ("" when it can).
function intervalWhy(raw) {
  const n = Number(raw);
  if (String(raw).trim() === "") return "Enter how often: an interval above 0.";
  return Number.isFinite(n) && n > 0 ? "" : "Enter an interval above 0.";
}

// Changing a task (its card's Edit): its name, what raises it (Trigger: every
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
