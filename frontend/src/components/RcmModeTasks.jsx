import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { DEFAULT_OUTCOMES, INTERVAL_UNITS, TASK_ORDER, modeAnswers, startUnit } from "../decisionCheck.js";
import {
  FOUND_EMPTY, OUTCOME_LABEL, ROLE, addableOutcomes, decisionCardLines, decisionRows, decisionWithFirstTask, decisionWithMember, decisionWithoutMember,
  decisionBody, decisionWithOnFound, decisionWithOutcome, everyText, findsSomething, isCombination, onEventOnly, roleLine, tasksDropped, tasksOf,
} from "../rcmWorksheet.js";
import { getTaskTriggerPoints, saveStrategyAnalysis } from "../api.js";
import { appendNotes, calculatorFor, linksEvidence } from "../rcmIntervals.js";
import IntervalCalculator from "./IntervalCalculator.jsx";
import { asksInterval, pointLabel, triggerBody, triggerState, triggerWhy } from "../taskTrigger.js";
import { modeTaskRows, secondTaskHint, taskKey } from "../explorerRcm.js";
import { explorerPath } from "../assetTree.js";
import { TaskMeasurementField } from "./TaskMeasurement.jsx";
import TaskChoice from "./TaskChoice.jsx";
import Chip from "./ui/Chip.jsx";
import ChoiceChips from "./ui/ChoiceChips.jsx";
import Field, { SavedMark } from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";
import Section from "./ui/Section.jsx";
import { PanelField } from "./PanelField.jsx";

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
//    Under the chosen chip, a short bridge says what the card below holds
//    (TaskChoice `bridge`); the worth-doing test is each chip's tooltip.
// 2. The tasks: each task is a row of its own in the tree, under the failure mode
//    (the tree's fifth level; Derryn, 9 Nov 2026: "I'm thinking that task actually
//    becomes another level in the tree"), so here they're a plain list, one line
//    each (name · kind · interval), each a link that picks the task's row; its
//    details (RcmTaskSections, below) change it. What has no row stays here as a
//    card: run to failure "When it fails:" with what's done on failure (`own`),
//    accept "Accepted:" and redesign "Change:" with the first line of the failure
//    mode's notes and rationale. A scheduled decision with no task yet shows the
//    task form instead (a new task's name and how often, Enter saves; or an
//    existing task: one on this position or above it). "+ Add a task" (dashed)
//    only when the rules allow a combination and a task exists: its kind, then the
//    form. A task saved from either form is picked in the tree once it's there.
// 3. "Evidence", open: the evidence line (`why`, built by Details: Link
//    evidence… opens the evidence picker alone). The rationale is the failure
//    mode's notes and rationale, under its title: one place (Derryn, 9 Nov 2026).
//
// No decision and tasks linked before: those tasks under their own heading.
// Each write goes at once through `ops` (useTreeRcm) and the row is read
// again, so the step follows.
//
//   r         the failure mode's row (read afresh after each save)
//   ops       modeTasks, editTask, removeTask, decide; none: the chips disabled
//   readOnly  no edits at all
//   options   the server's RCM options (labels, hints, run-to-failure reasons)
//   why       the evidence line (shown with a decision)
//   own       run to failure's "What's done on failure" field
//   addStart  a value that, when it changes, opens "Add a task" (the row menu's Add a task…)
//   onSaid    (text) a few words in the page's status line once something's done
//   onPick    (key) picks a row in the tree (a task's row)

// A failure mode's steps as one two-column grid, "step | choice" (Derryn, 9 Nov 2026: "this
// can be made a lot more dense. Let's try a table layout with step and choice"): one row per
// question, a hairline between rows, no help sentences. `n`: the step number (accent colour).
export const StepLabel = ({ n = null, id, children, saved = 0 }) => (
  <div className="rw-sl" id={id}>
    <span>{n != null && <><span className="rw-stepn">{n}</span> · </>}{children}</span>
    <SavedMark saved={saved} />
  </div>
);

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

// Takes a task off a failure mode, after asking: a combination's member comes off the
// decision with its task (the others kept by their task); any other task is retired, or
// unlinked when it serves other modes too. Resolves true once it's done.
export async function removeTaskFromMode({ confirm, ops, mode, task, onSaid }) {
  const d = mode.ref.decision || null;
  const without = d ? decisionWithoutMember(d, task.id) : null;
  const ok = await confirm({
    title: "Remove this task?", body: droppedWords([task]), confirmLabel: task.shared_with ? "Remove from this failure mode" : "Retire the task",
    pendingLabel: "Removing…", failedWhat: "remove it",
    run: () => (without ? ops.decide(mode, { consequence: mode.ref.consequence || null, decision: without }) : ops.removeTask(mode, task)).then(() => true),
  });
  if (ok) onSaid?.(task.shared_with ? "Removed the task from this failure mode." : "Retired the task.");
  return !!ok;
}

// The interval calculator for a failure mode's tasks: `link(task, kind, fill)` is the
// "Calculate…" beside a task's interval (none where it can't be used), `dialog` the
// calculator while it's open. Its "Use N unit" writes the interval on the task (or into
// the form being changed: `fill`), adds one paragraph on how it was worked out to the
// failure mode's notes and rationale, and, when the decision has no evidence yet, saves
// the calculation as a strategy analysis linked as its evidence.
function useIntervalCalc({ r, ops, can, busy = false, onSaid }) {
  const d = r.ref.decision || null;
  const [calc, setCalc] = useState(null); // {task, kind, fill?}
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  useEffect(() => setCalc(null), [r.key]);
  const decide = (decision) => ops.decide(r, { consequence: r.ref.consequence || null, decision });
  const useInterval = async ({ value, unit, line, analysis }) => {
    const { task, fill } = calc;
    let linked = false;
    if (d && linksEvidence(d)) {
      const kept = await saveStrategyAnalysis(analysis.name, analysis.kind, analysis.inputs);
      await decide(decisionBody(d, { evidence: { type: "strategy_analysis", id: kept.id } }));
      linked = true;
    }
    if (fill) fill(value, unit);
    else await ops.editTask(task.id, { interval: value, unit });
    await ops.set(r, "notes", appendNotes(r.ref.notes, line));
    if (!alive.current) return;
    setCalc(null);
    onSaid?.(`${fill ? "Put the interval in the form" : "Saved the interval"} and added how it was worked out to the notes${linked ? ", with the calculation as evidence" : ""}.`);
  };
  const link = (t, kind, fill = null) => (t?.id && can && ops?.editTask && ops?.set && calculatorFor(kind) ? (
    <button type="button" className="link rim-calc" disabled={busy} aria-label={`Calculate how often to do “${t.name}”`}
            title="Work out the interval from the failure's numbers" onClick={() => setCalc({ task: t, kind, fill })}>
      Calculate…
    </button>
  ) : null);
  const dialog = calc ? <IntervalCalculator r={r} task={calc.task} kind={calc.kind} onClose={() => setCalc(null)} onUse={useInterval} /> : null;
  return { link, dialog };
}

export default function RcmModeTasks({
  r, ops = null, readOnly = false, addStart = null, onSaid, options = null, why = null, own = null, onPick = null, n = 3,
}) {
  const confirm = useConfirm();
  const d = r.ref.decision || null;
  const tasks = tasksOf(r.ref);
  const answers = modeAnswers(r.ref);
  const answered = !!answers.consequence;
  const can = !readOnly && !!ops?.decide;
  // A decision that schedules nothing (run to failure, accept, redesign) is one card too.
  const cards = d
    ? decisionCardLines(d, tasks).filter((l) => l.task || l.member || (l.key === "decision" && !SCHEDULED.includes(d.outcome)))
    : decisionRows(null, tasks).map((row) => ({
      key: row.key, kind: null, name: row.task.text || row.task.name, every: everyText(row.task) || null, task: row.task, member: null,
    }));
  // A task with a row in the tree is a line linking to it; the rest (run to failure's action,
  // accept, redesign, a task the tree has no row for) stay cards here.
  const rowsHere = modeTaskRows(r.ref);
  const listed = rowsHere.map((x) => ({ key: x.task.id, task: x.task, outcome: x.outcome }));
  const carded = cards.filter((l) => !(l.task?.id && rowsHere.some((x) => x.task.id === l.task.id)));
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
  // The row menu's Add a task…: "Add a task" opened (when another task can join the decision).
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

  // What's done when a check finds it (a card's "Then, if found"), saved with the decision.
  const saveFound = (l, text) => decide(decisionWithOnFound(d, l.found.at, text));

  const submitEdit = (task, l) => async (body, found) => {
    if (busy) return false;
    setBusy(true);
    setFailed(null);
    try {
      await ops.editTask(task.id, body);
      if (l.found && found !== undefined && found !== (l.found.text || "")) await saveFound(l, found);
      if (alive.current) { setBusy(false); setEditing(null); }
      onSaid?.("Saved the task.");
      return true;
    } catch (e) {
      if (alive.current) { setBusy(false); setFailed(errorText(e)); }
      return false;
    }
  };

  const { link: calcLink, dialog: calcDialog } = useIntervalCalc({ r, ops, can, busy, onSaid });
  const remove = (t) => removeTaskFromMode({ confirm, ops, mode: r, task: t, onSaid });

  // The task rows under this failure mode in the tree: listed here as links to them.
  const rowTasks = new Set(rowsHere.map((x) => x.task.id));
  // A task saved from a form here: picked in the tree once the read brings it (a new id).
  const pickNew = useRef(null);
  const taskIds = tasks.map((t) => t.id).filter(Boolean).join(",");
  useEffect(() => {
    const before = pickNew.current;
    if (!before) return;
    const fresh = tasks.find((t) => t.id && !before.has(t.id) && rowTasks.has(t.id));
    if (!fresh) return;
    pickNew.current = null;
    onPick?.(taskKey(r.key, fresh.id));
  }, [taskIds]); // eslint-disable-line react-hooks/exhaustive-deps
  const watching = (save) => (member) => {
    pickNew.current = new Set(tasks.map((t) => t.id).filter(Boolean));
    return save(member).catch((e) => { pickNew.current = null; throw e; });
  };

  const card = (l) => {
    const t = l.task;
    const role = roleLine(l, r.ref.notes);
    if (t && editing === t.id && can) {
      return (
        <li key={l.key} className="rim-line rim-card rim-one editing">
          <TaskEditCard key={t.id} r={r} task={t} lead={role.lead} busy={busy} failed={failed}
                        calculate={(fill) => calcLink(t, l.outcome || t.outcome || d?.outcome, fill)}
                        found={l.found ? { label: ROLE[l.outcome].then, text: l.found.text } : null}
                        onCancel={() => { setEditing(null); setFailed(null); }} onSubmit={submitEdit(t, l)} />
        </li>
      );
    }
    // Run to failure's action on failure is edited in its card (`own`); accept and redesign read the notes.
    const ownHere = l.key === "decision" && d?.outcome === "rtf" && own;
    const empty = l.task || ownHere ? null : l.outcome === "accept" ? "Say why in Notes and rationale above"
      : l.outcome === "redesign" ? "Say what's to change in Notes and rationale above"
        : l.outcome === "rtf" ? "Say what's done when it fails" : null;
    const name = ownHere ? null : role.name;
    const acts = t?.id && can ? (
      <>
        <button type="button" className="link" disabled={busy} aria-label={`Edit “${t.name}”`}
                onClick={() => { setFailed(null); setAdding(false); setEditing(t.id); }}>Edit</button>
        <button type="button" className="link" disabled={busy}
                aria-label={t.shared_with ? `Remove “${t.name}” from this failure mode` : `Remove “${t.name}”`}
                onClick={() => remove(t)}>Remove</button>
      </>
    ) : null;
    const chips = t && (t.shared_with || t.package);
    const calcHere = role.every ? calcLink(t, l.outcome || t?.outcome || d?.outcome) : null;
    return (
      <li key={l.key} className="rim-line rim-card rim-one">
        <div className="rim-r1">
          <span className="rim-tname rim-r1-body">
            {role.lead && <span className="rim-trole">{role.lead}</span>}
            {role.lead && (name || role.every || (!name && empty)) ? " " : null}
            {name || (empty && <span className="rim-empty">{empty}</span>)}
            {(name || empty) && role.every ? " · " : null}
            {role.every && <span className="rim-tevery">{role.every}</span>}
          </span>
          {calcHere && <span className="rim-tcalc">{calcHere}</span>}
          {acts && <span className="rim-tacts">{acts}</span>}
        </div>
        {ownHere && <div className="rim-own">{own}</div>}
        {l.found && t && (
          <FoundLine key={`${r.key}:${l.key}:found`} label={ROLE[l.outcome].then} value={l.found.text}
                     can={can} onSave={(text) => saveFound(l, text).then(() => onSaid?.("Saved what's done when it's found."))} />
        )}
        {(t?.instructions || chips) && (
          <div className="rim-r3">
            {t?.instructions && <Instructions text={t.instructions} />}
            {chips ? (
              <span className="rim-chips">
                {t.shared_with ? <Chip>Shared with {plural(t.shared_with, "other failure mode")}</Chip> : null}
                {t.package && (
                  <Link className="chip chip-neutral chip-btn" title="Done on this work package's visits: open it on the LSA tab"
                        to={explorerPath(t.package.subject?.kind === "location" ? "locations" : "positions",
                                         { sel: t.package.subject?.id, tab: "lsa", package: t.package.id })}>
                    In: {t.package.name}
                  </Link>
                )}
              </span>
            ) : null}
          </div>
        )}
      </li>
    );
  };

  // Rows of the steps grid ("step | choice", Details): the task worth doing, the tasks, the
  // evidence. Each label cell names its row; the evidence cell is a group named by its label.
  const hasTasks = needsFirst || cards.length > 0 || canAdd;
  const whyId = `rim-why-${r.key}`;
  return (
    <div className={"rim-step rw-sg" + (editing ? " has-edit" : "")}>
      <StepLabel n={n} saved={saved}>Task worth doing?</StepLabel>
      <div className="rw-sc">
        <TaskChoice options={options} hidden={answers.hidden} consequence={answers.consequence} value={pick} onChange={choose}
                    disabled={!can || !answered || busy} locked={answered ? null : LOCKED} moveOnly bridge bare />
        {failed && !editing && <p className="field-error" role="alert">{failed}</p>}
      </div>
      {hasTasks && (
        <>
          <StepLabel>Tasks</StepLabel>
          <div className="rw-sc rim-tasks-cell">
            {needsFirst && (
              <div className="rim-card rim-one editing" role="group" aria-label="The decision's task">
                <NewTaskCard key={`${r.key}:${d.outcome}`} r={r} d={d} ops={ops} kind={d.outcome}
                             start={{ name: d.task || "", interval: d.interval ?? "" }}
                             onSave={watching((member) => decide(decisionWithFirstTask(d, member)))}
                             onDone={(said) => { setSaved((x) => x + 1); onSaid?.(said); }} />
              </div>
            )}
            {d && listed.length > 0 && <TaskList r={r} lines={listed} label="The decision's tasks" onPick={onPick} />}
            {d && carded.length > 0 && <ul className="rim-lines rim-cards" aria-label="The decision's action">{carded.map(card)}</ul>}
            {!d && cards.length > 0 && (
              <>
                <h4 className="rim-before">Tasks linked before the decision</h4>
                {listed.length > 0 && <TaskList r={r} lines={listed} label="Tasks linked before the decision" onPick={onPick} />}
                {carded.length > 0 && <ul className="rim-lines rim-cards" aria-label="Other tasks linked before the decision">{carded.map(card)}</ul>}
              </>
            )}
            {canAdd && !editing && (adding ? (
              <div className="rim-card rim-one rim-adding editing" role="group" aria-label="Add a task">
                <NewTaskCard r={r} d={d} ops={ops} kinds={addable}
                             onSave={watching((member) => decide(decisionWithMember(d, member)))}
                             onCancel={() => setAdding(false)}
                             onDone={(said) => { setAdding(false); onSaid?.(said); }} />
              </div>
            ) : (
              <button type="button" className="rim-addrow" disabled={busy} onClick={() => { setFailed(null); setAdding(true); }}>
                + Add a task
              </button>
            ))}
            {calcDialog}
          </div>
        </>
      )}
      {d && why && (
        <>
          <StepLabel id={whyId}>Evidence</StepLabel>
          <div className="rw-sc rim-whyopen" role="group" aria-labelledby={whyId}>{why}</div>
        </>
      )}
    </div>
  );
}

// ---- one card shape in every state (Derryn, 10 Nov 2026) ---------------------------
// "The final box changes appearance": a task's card is the same three rows whether it
// is shown, being changed or not made yet. Row 1: the role ("Check:", "Do:", …) and
// the task, with "every N unit"; its links (Edit, Remove) or Save at the right. Row 2,
// for a check: "Then, if found:" (or "Then, if failed:") and what's done. Row 3, quiet:
// the instructions' first line and the chips, or, while it's changed, its other fields.
// Changing or making a task puts inputs exactly where the words were.

function Row1({ lead, children, acts = null }) {
  return (
    <div className="rim-r1">
      <div className="rim-r1-body">
        {lead && <span className="rim-trole">{lead}</span>}
        {children}
      </div>
      {acts && <span className="rim-tacts">{acts}</span>}
    </div>
  );
}

function Row2({ lead, id, children, hideLabel = false }) {
  return (
    <div className="rim-r2">
      <label className={hideLabel ? "sr-only" : "rim-trole"} htmlFor={id}>{lead}</label>
      {children}
    </div>
  );
}

// "every [6] [months]" in row 1: where the card's "· every 6 months" is.
function EveryInputs({ interval, unit, onInterval, onUnit, busy, invalid = false }) {
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  return (
    <span className="rim-every">
      <span className="rim-every-word" aria-hidden="true">every</span>
      <InputGroup label="Every">
        <TextInput type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={busy} aria-label="Interval"
                   aria-invalid={invalid ? "true" : undefined} placeholder="e.g. 6" onChange={(e) => onInterval(e.target.value)} />
        <Select value={unit} disabled={busy} aria-label="Interval unit" onChange={(e) => onUnit(e.target.value)}>
          {units.map((u) => <option key={u} value={u}>{u}</option>)}
        </Select>
      </InputGroup>
    </span>
  );
}

// The reason an interval can't be kept ("" when it can).
function intervalWhy(raw) {
  const n = Number(raw);
  if (String(raw).trim() === "") return "Enter how often: an interval above 0.";
  return Number.isFinite(n) && n > 0 ? "" : "Enter an interval above 0.";
}

// A task for the decision not made yet, in the card's shape: with `kinds` (another task
// for a combination) its kind first as chips; then "New task · Existing task"; row 1 the
// role and a new task's name and how often (Enter saves), or the picker of a task on
// this position or above it (it keeps its own interval for every mode it serves); row 2,
// for a check, what's done when it finds it. A redesign needs no task: the others stand
// in until the change is made. `onSave(member)` writes it ({outcome, task, interval,
// interval_unit, on_found?}, {outcome, task_id, on_found?} or {outcome}) and returns a
// promise; a refusal shows here with everything as typed. Escape cancels (when it can be).
function NewTaskCard({ r, d, ops, kind: fixed = null, kinds = null, start = {}, onSave, onCancel = null, onDone }) {
  // Starts on a kind the decision doesn't have yet (any kind may come again, a click away).
  const [kind, setKind] = useState(() => {
    const have = isCombination(d) ? d.outcomes.map((o) => o.outcome) : [d?.outcome];
    return fixed || kinds?.find((k) => !have.includes(k)) || kinds?.[0];
  });
  const [use, setUse] = useState("new"); // "new" | "existing"
  const [name, setName] = useState(start.name || "");
  const [interval, setInterval_] = useState(start.interval != null ? String(start.interval) : "");
  const [unit, setUnit] = useState(() => startUnit(d || {}));
  const [choices, setChoices] = useState(null);
  const [picked, setPicked] = useState("");
  const [found, setFound] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [tried, setTried] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);
  const foundId = `rim-found${useId()}`;
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
    const said = findsSomething(kind) && found.trim() ? { on_found: found.trim() } : {};
    const member = !scheduled ? { outcome: kind }
      : use === "existing" ? { outcome: kind, task_id: picked, ...said }
        : { outcome: kind, task: name.trim(), interval: n, interval_unit: unit, ...said };
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
  const acts = (
    <>
      {onCancel && <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>}
      <button type="submit" className="sm" disabled={busy} aria-busy={busy || undefined}>
        {busy ? "Saving…" : use === "existing" && scheduled ? "Link task" : "Save"}
      </button>
    </>
  );
  return (
    <form className="rim-tform rim-addform rim-onecard" onSubmit={save}
          onKeyDown={(e) => {
            if (e.key !== "Escape" || !onCancel || busy) return;
            e.preventDefault();
            e.stopPropagation(); // the form closes, not the panel
            onCancel();
          }}>
      {(kinds || scheduled) && (
        <div className="rim-top">
          {kinds && (
            <ChoiceChips label="Kind of task" autoFocus value={kind} disabled={busy}
                         options={kinds.map((k) => ({ value: k, label: KIND_LABEL[k] || k }))}
                         onChange={(v) => { if (v) setKind(v); }} />
          )}
          {scheduled && (
            <ChoiceChips label="New or existing task" className="rim-seg" value={use} disabled={busy}
                         options={[{ value: "new", label: "New task" }, { value: "existing", label: "Existing task" }]}
                         onChange={(v) => { if (v) { setFailed(null); setUse(v); } }} />
          )}
        </div>
      )}
      <Row1 lead={ROLE[kind]?.lead} acts={acts}>
        {!scheduled ? (
          <span className="rim-empty">the other task stands in until the change is made. Say what's to change in Notes and rationale, under the title.</span>
        ) : use === "new" ? (
          <>
            <TextInput className="rim-in-name" value={name} readOnly={busy} placeholder="e.g. Replace the acid pump" aria-label="Task"
                       aria-invalid={tried && !name.trim() ? "true" : undefined} onChange={(e) => setName(e.target.value)} />
            <EveryInputs interval={interval} unit={unit} onInterval={setInterval_} onUnit={setUnit} busy={busy}
                         invalid={tried && !!intervalWhy(interval)} />
          </>
        ) : choices === null ? <span className="rim-empty">Reading the tasks…</span> : choices.length === 0 ? (
          <span className="rim-empty">No other task on this position or above it: choose New task.</span>
        ) : (
          <Select className="rim-in-name" value={picked} disabled={busy} onChange={(e) => setPicked(e.target.value)} aria-label="Existing task">
            <option value="">Choose a task…</option>
            {choices.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}{every(t) ? ` · ${every(t)}` : ""}{t.position?.id !== here ? ` · on ${t.position?.name}` : ""}{t.serves ? ` · serves ${plural(t.serves, "failure mode")}` : ""}
              </option>
            ))}
          </Select>
        )}
      </Row1>
      {scheduled && findsSomething(kind) && (
        <Row2 lead={ROLE[kind].then} id={foundId}>
          <TextInput id={foundId} value={found} readOnly={busy} placeholder={FOUND_EMPTY} maxLength={500} onChange={(e) => setFound(e.target.value)} />
        </Row2>
      )}
      {(hint || (use === "existing" && scheduled) || failed || (tried && why && !busy)) && (
        <div className="rim-r3">
          {hint && <p className="rw-fhelp">{hint}</p>}
          {use === "existing" && scheduled && <p className="rw-fhelp">It keeps its own interval for every failure mode it serves.</p>}
          {failed && <p className="field-error" role="alert">{failed}</p>}
          {tried && why && !busy && <p className="rim-why">{why}</p>}
        </div>
      )}
    </form>
  );
}

// Changing a task (its card's Edit), in the card's shape: row 1 its name and how
// often in place of the words; row 2, for a check, what's done when it finds it;
// row 3 its other fields: what raises it (every interval, or an event: a reading past
// a limit, or an event logged by name; taskTrigger.js), a task by use's measurement
// (what it counts, with the last-done reading on a new one) and its instructions.
// Saved once (the button says so until the server answers); a refusal shows here with
// everything as typed.
function TaskEditCard({ r, task, lead, busy, failed, found = null, calculate = null, onCancel, onSubmit }) {
  const d = r.ref.decision;
  const [name, setName] = useState(task?.name || "");
  const [interval, setInterval_] = useState(task?.interval != null ? String(task.interval) : "");
  const [unit, setUnit] = useState(task?.unit || startUnit(d || {}));
  const [foundText, setFoundText] = useState(found?.text || "");
  // The kind of task is the decision's (the chip in step 3), never asked again here.
  const outcome = task?.outcome || (d && SCHEDULED.includes(d.outcome) ? d.outcome : "");
  const [instructions, setInstructions] = useState(task?.instructions || "");
  const [meas, setMeas] = useState({ body: null, error: null });
  const [trig, setTrig] = useState(() => triggerState(task));
  const setT = (k) => (e) => setTrig((x) => ({ ...x, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));
  const [points, setPoints] = useState(null);
  const foundId = `rim-found${useId()}`;
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
  const why = busy ? null : !name.trim() ? "Name the task first."
    : timed && interval.trim() === "" ? "Enter how often: an interval above 0."
    : !intervalOk ? "Enter an interval above 0." : triggerWhy(trig) || (meas.error ? "Settle the measurement first." : null);
  const acts = (
    <>
      <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
      <button type="submit" className="sm" disabled={!can} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save task"}</button>
    </>
  );
  return (
    <form className="rim-tform rim-onecard" aria-label={`Change “${task?.name || "the task"}”`} onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit({ name: name.trim(), ...(timed ? { interval: n, unit } : {}), outcome: outcome || null,
        instructions: instructions.trim(), ...(timed ? meas.body || {} : {}), trigger: triggerBody(trig) },
      found ? foundText.trim() : undefined);
    }}>
      <Row1 lead={lead} acts={acts}>
        <TextInput ref={nameBox} className="rim-in-name" value={name} readOnly={busy} aria-label="Task"
                   placeholder="What to do, e.g. Replace the acid pump" onChange={(e) => setName(e.target.value)} />
        {timed ? (
          <>
            <EveryInputs interval={interval} unit={unit} onInterval={setInterval_} onUnit={setUnit} busy={busy}
                         invalid={interval.trim() !== "" && !(Number.isFinite(n) && n > 0)} />
            {calculate?.((value, u) => { setInterval_(String(value)); setUnit(u); })}
          </>
        ) : <span className="rim-tevery">on an event (below)</span>}
      </Row1>
      {found && (
        <Row2 lead={found.label} id={foundId}>
          <TextInput id={foundId} value={foundText} readOnly={busy} placeholder={FOUND_EMPTY} maxLength={500}
                     onChange={(e) => setFoundText(e.target.value)} />
        </Row2>
      )}
      <div className="rim-r3">
        {task?.shared_with ? (
          <p className="rw-fhelp">It also serves {plural(task.shared_with, "other failure mode")}: the change applies to all of them.</p>
        ) : null}
        {/* What raises the task is the interval unless asked otherwise: a quiet link swaps
            to an event (a reading past a limit, or a logged event) and back (Derryn, 9 Nov 2026). */}
        {trig.mode === "event" ? (
          <fieldset className="rim-trigger">
            <legend>Raised by an event · <button type="button" className="link" disabled={busy}
                    onClick={() => setTrig((x) => ({ ...x, mode: "interval" }))}>Back to every interval</button></legend>
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
        ) : (
          <p className="rw-fhelp rim-trigger-swap">
            <button type="button" className="link" disabled={busy} onClick={() => setTrig((x) => ({ ...x, mode: "event" }))}>
              Raise it on an event instead…
            </button>
            {" "}(a reading past a limit, or an event someone logs)
          </p>
        )}
        {task?.id && timed && (
          <TaskMeasurementField taskId={task.id} unit={unit} disabled={busy} onChange={(body, error) => setMeas({ body, error })} />
        )}
        {meas.error && <p className="field-error" role="alert">{meas.error}</p>}
        <Field label="Instructions" optional>
          <TextArea value={instructions} readOnly={busy} onChange={(e) => setInstructions(e.target.value)} />
        </Field>
        {failed && <p className="field-error" role="alert">{failed}</p>}
        {why && <p className="rim-why">{why}</p>}
      </div>
    </form>
  );
}

// A check's row 2 on its card, shown: "Then, if found:" (or "Then, if failed:") and what's
// done when the check finds it, one line, kept when you leave it or press Enter, "✓ Saved"
// once it is; greyed "Say what's done when the check finds it" while empty. Read-only:
// the words, or that greyed line.
function FoundLine({ label, value, can, onSave, hideLabel = false }) {
  const [draft, setDraft] = useState(value || "");
  const [saved, setSaved] = useState(0);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const sent = useRef(null);
  useEffect(() => { setDraft(value || ""); setError(null); sent.current = null; }, [value]);
  const id = `rim-found${useId()}`;
  if (!can && !busy) {
    return (
      <div className="rim-r2">
        <span className={hideLabel ? "sr-only" : "rim-trole"}>{label}</span> {value || <span className="rim-empty">{FOUND_EMPTY}</span>}
      </div>
    );
  }
  const commit = async () => {
    const text = draft.trim();
    if (busy || text === (value || "") || text === sent.current) return;
    sent.current = text;
    setBusy(true);
    setError(null);
    try {
      await onSave(text);
      setSaved((n) => n + 1);
    } catch (e) {
      sent.current = null;
      setError(saveErrorText(e, { offline: navigator.onLine === false }));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Row2 lead={label} id={id} hideLabel={hideLabel}>
      <TextInput id={id} value={draft} readOnly={busy} placeholder={FOUND_EMPTY} maxLength={500}
                 aria-invalid={error ? "true" : undefined}
                 onChange={(e) => { setDraft(e.target.value); sent.current = null; }} onBlur={commit}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }} />
      <SavedMark saved={saved} />
      {error && <p className="field-error" role="alert">{error}</p>}
    </Row2>
  );
}

// A task's instructions in row 3: the first line, with "Show all" when there's more.
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
      <span ref={box} className={"rim-tinst" + (open ? "" : " clamped one")}>{text}</span>
      {(long || open) && (
        <button type="button" className="link rim-tmore" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
          {open ? "Show less" : "Show all"}
        </button>
      )}
    </>
  );
}

// Step 3's list of the decision's tasks: one line each, its name a link that picks its row
// in the tree (where it's changed), then its kind and how often, quietly.
function TaskList({ r, lines, label, onPick }) {
  return (
    <ul className="rim-tasklist" aria-label={label}>
      {lines.map((l) => {
        const t = l.task;
        const meta = [l.outcome ? OUTCOME_LABEL[l.outcome] || l.outcome : null, every(t) || null].filter(Boolean).join(" · ");
        return (
          <li key={l.key}>
            <svg className="rw-ic" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" aria-hidden="true">
              <path d="M10.6 2.3a3.2 3.2 0 0 0-3.9 4.1L2.4 10.7a1.4 1.4 0 0 0 2 2l4.3-4.3a3.2 3.2 0 0 0 4.1-3.9l-1.9 1.9-1.8-.4-.4-1.8z" strokeWidth="1.3" strokeLinejoin="round" />
            </svg>
            <span className="rim-tl-body">
              {onPick ? (
                <button type="button" className="link rim-tgo" onClick={() => onPick(taskKey(r.key, t.id))} title="Show this task in the tree">
                  {t.name || t.text}
                </button>
              ) : <span>{t.name || t.text}</span>}
              {meta && <span className="rim-tmeta"> · {meta}</span>}
              {t.shared_with ? <span className="rim-tmeta"> · shared with {plural(t.shared_with, "other failure mode")}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

// ---- a task's own details (the tree's fifth level) ------------------------------------
// The task row's panel (RcmWorksheet's Details for a task) has its title (the name, edited
// in place there), then these sections, each kept as you go:
// - Kind and interval: the kind in words, "every N unit" with Change (in place) and
//   Calculate… (the interval calculator its kind calls for); "Edit when it's done…" opens
//   the task's form (what raises it: its interval, or an event, with the form's "Raise it
//   on an event instead…"; and what a task by use counts).
// - Then, if found (a check; "Then, if failed" for failure finding): what's done when the
//   check finds it, saved with the decision.
// - Instructions.
// The evidence, the failure modes it serves and its logistics are Details' own sections.
//   r     the task's row; mode: its failure mode's row (the decision and the saves go through it)
//   ops   the Explorer's ops (editTask, decide, set)
export function RcmTaskSections({ r, mode, ops, readOnly = false, onSaid }) {
  const t = r.ref.task || {};
  const outcome = r.ref.outcome || null;
  const d = mode?.ref.decision || null;
  const can = !readOnly && !!ops?.editTask;
  const [form, setForm] = useState(null); // null | "interval" | "all" (the task's whole form)
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const [saved, setSaved] = useState({});
  const markSaved = (k) => setSaved((x) => ({ ...x, [k]: (x[k] || 0) + 1 }));
  useEffect(() => { setForm(null); setFailed(null); setSaved({}); }, [r.key]);
  const errorText = (e) => saveErrorText(e, { offline: navigator.onLine === false });
  const { link: calcLink, dialog: calcDialog } = useIntervalCalc({ r: mode, ops, can, busy, onSaid });
  const save = async (body, said, mark) => {
    if (busy) return false;
    setBusy(true);
    setFailed(null);
    try {
      await ops.editTask(t.id, body);
      setBusy(false);
      setForm(null);
      if (mark) markSaved(mark);
      onSaid?.(said);
      return true;
    } catch (e) {
      setBusy(false);
      setFailed(errorText(e));
      return false;
    }
  };
  const when = every(t);
  const eventOnly = onEventOnly(t);
  const found = r.ref.found && findsSomething(outcome) ? r.ref.found : null;
  const then = ROLE[outcome]?.then || "Then, if found:";
  return (
    <>
      <Section title="Kind and interval" className="rw-tsec" aside={<SavedMark saved={saved.interval} />}>
        {form === "all" ? (
          <div className="rim-card rim-one editing">
            <TaskEditCard key={t.id} r={mode} task={t} lead={ROLE[outcome]?.lead} busy={busy} failed={failed}
                          calculate={(fill) => calcLink(t, outcome, fill)}
                          onCancel={() => { setForm(null); setFailed(null); }}
                          onSubmit={(body) => save(body, "Saved the task.", "interval")} />
          </div>
        ) : (
          <>
            <p className="rim-tkind">{OUTCOME_LABEL[outcome] || "Not in a decision yet"}</p>
            {form === "interval" ? (
              <IntervalForm task={t} d={d} busy={busy} failed={failed} calculate={(fill) => calcLink(t, outcome, fill)}
                            onCancel={() => { setForm(null); setFailed(null); }}
                            onSave={(interval, unit) => save({ interval, unit }, "Saved the interval.", "interval")} />
            ) : (
              <p className="rim-tevery-line">
                <span className="rim-tevery">{when || "No interval yet"}</span>
                {can && !eventOnly && (
                  <> · <button type="button" className="link" onClick={() => { setFailed(null); setForm("interval"); }}
                               aria-label={`Change how often “${t.name}” is done`}>Change</button></>
                )}
                {!eventOnly && calcLink(t, outcome) && <> · {calcLink(t, outcome)}</>}
              </p>
            )}
            {can && form !== "interval" && (
              <p className="rw-fhelp rim-trigger-swap">
                <button type="button" className="link" onClick={() => { setFailed(null); setForm("all"); }}>
                  Edit when it's done…
                </button>
                {" "}(what raises it: the interval, a reading past a limit or an event someone logs; what it counts)
              </p>
            )}
          </>
        )}
      </Section>
      {found && (
        <Section title={then.replace(/:$/, "")} className="rw-tsec">
          <FoundLine key={`${r.key}:found`} label={then} value={found.text} can={!readOnly && !!ops?.decide && !!d} hideLabel
                     onSave={(text) => ops.decide(mode, { consequence: mode.ref.consequence || null, decision: decisionWithOnFound(d, found.at, text) })
                       .then(() => onSaid?.("Saved what's done when it's found."))} />
        </Section>
      )}
      <Section title="Instructions" className="rw-tsec" aside={<SavedMark saved={saved.instructions} />}>
        <PanelField key={`${r.key}:instructions`} label="Instructions" labelHidden area readOnly={!can} value={t.instructions || ""}
                    placeholder="How it's done: the steps, the limits, what to record"
                    onCommit={(raw) => ops.editTask(t.id, { instructions: raw.trim() })
                      .then(() => { markSaved("instructions"); onSaid?.("Saved the instructions."); return true; }, errorText)} />
      </Section>
      {calcDialog}
    </>
  );
}

// "every [N] [unit]" changed in place in a task's details: Enter or Save keeps it, Escape or
// Cancel drops it; Calculate… beside it fills it in.
function IntervalForm({ task, d, busy, failed, calculate, onCancel, onSave }) {
  const [interval, setInterval_] = useState(task?.interval != null ? String(task.interval) : "");
  const [unit, setUnit] = useState(task?.unit || startUnit(d || {}));
  const [tried, setTried] = useState(false);
  const why = intervalWhy(interval);
  return (
    <form className="rim-tform rim-ivform" aria-label="How often" onSubmit={(e) => {
      e.preventDefault();
      setTried(true);
      if (!why) onSave(Number(interval), unit);
    }} onKeyDown={(e) => {
      if (e.key !== "Escape" || busy) return;
      e.preventDefault();
      e.stopPropagation();
      onCancel();
    }}>
      <div className="rim-ivrow">
        <EveryInputs interval={interval} unit={unit} onInterval={setInterval_} onUnit={setUnit} busy={busy} invalid={tried && !!why} />
        {calculate?.((value, u) => { setInterval_(String(value)); setUnit(u); })}
      </div>
      <div className="rim-ivacts">
        <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="sm" disabled={busy} aria-busy={busy || undefined}>{busy ? "Saving…" : "Save"}</button>
      </div>
      {tried && why && !busy && <p className="rim-why">{why}</p>}
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </form>
  );
}
