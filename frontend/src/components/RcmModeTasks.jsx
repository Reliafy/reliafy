import { useEffect, useRef, useState } from "react";
import { LevelIcon } from "./RcmWorksheet.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { INTERVAL_UNITS, startUnit } from "../decisionCheck.js";
import { OUTCOME_LABEL, intervalText, tasksOf } from "../rcmWorksheet.js";
import { secondTaskHint } from "../explorerRcm.js";
import { TaskMeasurementField } from "./TaskMeasurement.jsx";
import Chip from "./ui/Chip.jsx";
import Field from "./ui/Field.jsx";
import InputGroup from "./ui/InputGroup.jsx";
import MoreMenu from "./ui/MoreMenu.jsx";
import Section from "./ui/Section.jsx";
import { InlineAddButton, InlineAddRow, useInlineAdd } from "./ui/InlineAdd.jsx";
import { Select, TextArea, TextInput } from "./ui/Controls.jsx";

// A failure mode's tasks, in its details (the Explorer's RCM tab): the decision's own
// task first, then any more (a combination: an inspection that catches the
// slow failures plus a replacement at a hard life), each with its interval,
// kind and instructions, and whether other failure modes share it. Add
// another from the dashed row at the end: it becomes a new task card, its
// name and how often (the two a task can't do without); Enter or leaving it
// writes it, and its kind, instructions and measurement are then its ⋯ Edit…,
// as for any other task. Change one (a shared task changes for every mode it serves),
// take one off (a shared task is unlinked and stays; one serving this mode
// alone is retired), or link a task that is on the position already, or on a
// position above it. Each write goes at once through `ops` (useTreeRcm) and
// the row is read again, so the list follows.
//
//   r       the failure mode's row (read afresh after each save)
//   ops     modeTasks, addTask, editTask, removeTask, linkTask
//   addStart  a value that, when it changes, opens the add row (the row menu's Add a task…)
//   onSaid  (text) a few words in the page's status line once something's done

const SCHEDULED = ["on_condition", "fixed_interval", "failure_finding"];
const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;
const every = (t) => (t.interval != null && t.unit ? `every ${intervalText({ interval: t.interval, interval_unit: t.unit })}` : "");

export default function RcmModeTasks({ r, ops, addStart = null, onSaid }) {
  const confirm = useConfirm();
  const d = r.ref.decision;
  const tasks = tasksOf(r.ref).filter((t) => t.id);
  const [form, setForm] = useState(null); // {mode: "edit", task} | {mode: "link"}
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const run = async (go, said) => {
    if (busy) return false;
    setBusy(true);
    setFailed(null);
    try {
      await go();
      if (alive.current) {
        setBusy(false);
        setForm(null);
      }
      onSaid?.(said);
      return true;
    } catch (e) {
      if (alive.current) {
        setBusy(false);
        setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
      }
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

  // The add row: a task's name and how often, in a new card of the list.
  const [interval, setInterval_] = useState("");
  const [unit, setUnit] = useState(() => startUnit(d || {}));
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  const add = useInlineAdd({
    disabled: busy,
    startToken: addStart,
    check: () => intervalWhy(interval) || null,
    onSave: (name) => ops.addTask(r, { name, interval: Number(interval), unit }).then(() => {
      setInterval_("");
      onSaid?.("Added the task.");
    }),
    errorText: (e) => saveErrorText(e, { offline: navigator.onLine === false }),
  });
  const hint = secondTaskHint(r);
  const link = () => { setFailed(null); setForm({ mode: "link" }); };
  const submitTask = (task) => (body) => run(
    () => (task ? ops.editTask(task.id, body) : ops.addTask(r, body)),
    task ? "Saved the task." : "Added the task.",
  );
  return (
    <Section title="Tasks" count={tasks.length} className="rim-tasks">
      {tasks.length === 0 && !add.open && (
        <p className="rw-fhelp">
          {d && SCHEDULED.includes(d.outcome)
            ? "The decision schedules work, but no task does it yet: add one, or use an existing task."
            : "No tasks yet."}
        </p>
      )}
      {(tasks.length > 0 || add.open) && (
        <ul className="rim-tlist">
          {tasks.map((t, i) => (
            <li key={t.id} className={"rim-card" + (form?.mode === "edit" && form.task.id === t.id ? " editing" : "")}>
              {form?.mode === "edit" && form.task.id === t.id ? (
                <TaskForm key={t.id} r={r} task={t} busy={busy} failed={failed}
                          onCancel={() => { setForm(null); setFailed(null); }} onSubmit={submitTask(t)} />
              ) : (
                <>
                  <div className="rim-chead">
                    <LevelIcon type="task" className="rw-ic rw-ic-task" />
                    <span className="rim-tname">{t.text || t.name}</span>
                    <MoreMenu label={`Actions for ${t.name}`} disabled={busy} items={[
                      { id: "edit", label: "Edit…", onSelect: () => { setFailed(null); setForm({ mode: "edit", task: t }); } },
                      { id: "remove", label: t.shared_with ? "Remove from this failure mode…" : "Remove…", danger: true, onSelect: () => remove(t) },
                    ]} />
                  </div>
                  <div className="rim-chips">
                    {every(t) && <Chip tone="accent">{every(t)}</Chip>}
                    {OUTCOME_LABEL[t.outcome] && <Chip>{OUTCOME_LABEL[t.outcome]}</Chip>}
                    {i === 0 && tasks.length > 1 && <Chip>The decision's own</Chip>}
                    {t.shared_with ? <Chip>Shared with {plural(t.shared_with, "other failure mode")}</Chip> : null}
                  </div>
                  {t.instructions && <Instructions text={t.instructions} />}
                </>
              )}
            </li>
          ))}
          {add.open && (
            <InlineAddRow add={add} as="li" className="rim-card rim-new" lead={<LevelIcon type="task" className="rw-ic rw-ic-task" />}
                          label="New task" placeholder="e.g. Replace the acid pump" help={hint}>
              <span className="rim-every">
                <span className="rim-every-word" aria-hidden="true">every</span>
                <InputGroup label="How often">
                  <TextInput type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={add.busy} aria-label="Interval"
                             aria-invalid={add.error && !add.onText ? "true" : undefined} placeholder="e.g. 6" onChange={(e) => setInterval_(e.target.value)} />
                  <Select value={unit} disabled={add.busy} aria-label="Interval unit" onChange={(e) => setUnit(e.target.value)}>
                    {units.map((u) => <option key={u} value={u}>{u}</option>)}
                  </Select>
                </InputGroup>
              </span>
            </InlineAddRow>
          )}
        </ul>
      )}
      {form?.mode === "link" ? (
        <div className="rim-card editing">
          <LinkForm r={r} ops={ops} busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                    onFailed={(e) => setFailed(saveErrorText(e, { offline: navigator.onLine === false }))}
                    onSubmit={(taskId) => run(() => ops.linkTask(r, taskId), "Linked the task.")} />
        </div>
      ) : !form && (
        <div className="rim-tadd">
          {!add.open && <InlineAddButton add={add}>Add a task</InlineAddButton>}
          <button type="button" className="link" disabled={busy} onClick={(e) => { if (e.detail < 2) link(); }}>
            Use an existing task…
          </button>
        </div>
      )}
      {failed && !form && <p className="field-error" role="alert">{failed}</p>}
    </Section>
  );
}

// The reason an interval can't be kept ("" when it can).
function intervalWhy(raw) {
  const n = Number(raw);
  if (String(raw).trim() === "") return "Enter how often: an interval above 0.";
  return Number.isFinite(n) && n > 0 ? "" : "Enter an interval above 0.";
}

// Changing a task (its ⋯ Edit…): its name, interval and unit, what kind of
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
  const nameBox = useRef(null);
  useEffect(() => {
    // Focused, its start in view (a long name isn't shown scrolled to its end).
    const el = nameBox.current;
    el?.focus();
    if (el) el.scrollLeft = 0;
  }, []);
  const n = Number(interval);
  const can = !!name.trim() && interval.trim() !== "" && Number.isFinite(n) && n > 0 && !busy && !meas.error;
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  const why = busy ? null : !name.trim() ? "Name the task first."
    : interval.trim() === "" ? "Enter how often: an interval above 0."
    : !(Number.isFinite(n) && n > 0) ? "Enter an interval above 0." : meas.error ? "Settle the measurement first." : null;
  return (
    <form className="rim-tform" onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit({ name: name.trim(), interval: n, unit, outcome: outcome || null, instructions: instructions.trim(), ...(meas.body || {}) });
    }}>
      <h4>Change the task</h4>
      {task?.shared_with ? (
        <p className="rw-fhelp">It also serves {plural(task.shared_with, "other failure mode")}: the change applies to all of them.</p>
      ) : null}
      <Field label="Task">
        <TextInput ref={nameBox} value={name} readOnly={busy} placeholder="What to do, e.g. Replace the acid pump"
                   onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="rim-trow">
        <Field label="Every" as="fieldset" error={interval.trim() !== "" && !(Number.isFinite(n) && n > 0) ? "Enter an interval above 0." : null}>
          <InputGroup label="Every">
            <TextInput type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={busy} aria-label="Interval"
                       onChange={(e) => setInterval_(e.target.value)} />
            <Select value={unit} disabled={busy} aria-label="Interval unit" onChange={(e) => setUnit(e.target.value)}>
              {units.map((u) => <option key={u} value={u}>{u}</option>)}
            </Select>
          </InputGroup>
        </Field>
        <Field label="Kind of task">
          <Select value={outcome} disabled={busy} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Routine work</option>
            {SCHEDULED.map((o) => <option key={o} value={o}>{OUTCOME_LABEL[o]}</option>)}
          </Select>
        </Field>
      </div>
      {task?.id && (
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

// Linking a task the position has already, or one on a position above it
// (a task serves the failure modes on its position and inside it): the list
// is read when the form opens, each task with where it is and how many modes
// it serves already.
function LinkForm({ r, ops, busy, failed, onCancel, onFailed, onSubmit }) {
  const [choices, setChoices] = useState(null);
  const [picked, setPicked] = useState("");
  useEffect(() => {
    let on = true;
    ops.modeTasks(r).then((out) => { if (on) setChoices(out.available || []); }, (e) => { if (on) { setChoices([]); onFailed(e); } });
    return () => { on = false; };
  }, [r, ops, onFailed]);
  const here = r.ref.position_id;
  return (
    <form className="rim-tform" onSubmit={(e) => { e.preventDefault(); if (picked && !busy) onSubmit(picked); }}>
      <h4>Use an existing task</h4>
      <p className="rw-fhelp">A task on this position, or on a position above it, can serve this failure mode too. It keeps its own interval for every mode it serves.</p>
      {choices === null ? <p className="rw-fhelp">Reading the tasks…</p> : choices.length === 0 ? (
        <p className="rw-fhelp">No other task on this position or above it. Add a task instead.</p>
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
      {failed && <p className="field-error" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary sm" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="sm" disabled={!picked || busy} aria-busy={busy || undefined}>{busy ? "Linking…" : "Link task"}</button>
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
