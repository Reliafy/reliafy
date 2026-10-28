import { useEffect, useRef, useState } from "react";
import { LevelIcon } from "./RcmWorksheet.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import { saveErrorText } from "../confirm.js";
import { INTERVAL_UNITS, startUnit } from "../decisionCheck.js";
import { OUTCOME_LABEL, intervalText, tasksOf } from "../rcmWorksheet.js";
import { secondTaskHint } from "../explorerRcm.js";

// A failure mode's tasks, in its dialog (RcmItemModal): the decision's own
// task first, then any more (a combination: an inspection that catches the
// slow failures plus a replacement at a hard life), each with its interval,
// kind and instructions, and whether other failure modes share it. Add
// another task, change one (a shared task changes for every mode it serves),
// take one off (a shared task is unlinked and stays; one serving this mode
// alone is retired), or link a task that is on the position already, or on a
// position above it. Each write goes at once through `ops` (useTreeRcm) and
// the row is read again, so the list follows.
//
//   r       the failure mode's row (read afresh after each save)
//   ops     modeTasks, addTask, editTask, removeTask, linkTask
//   start   {tasks: true}: open on the add form (the row menu's Add a task…)
//   onSaid  (text) a few words in the page's status line once something's done

const SCHEDULED = ["on_condition", "fixed_interval", "failure_finding"];
const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;
const every = (t) => (t.interval != null && t.unit ? `every ${intervalText({ interval: t.interval, interval_unit: t.unit })}` : "");

export default function RcmModeTasks({ r, ops, start = null, onSaid }) {
  const confirm = useConfirm();
  const d = r.ref.decision;
  const tasks = tasksOf(r.ref).filter((t) => t.id);
  const [form, setForm] = useState(() => (start?.tasks ? { mode: "add" } : null));
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

  return (
    <section className="rim-tasks" aria-label="Tasks">
      <h3>{tasks.length > 1 ? `Tasks (${tasks.length})` : "Tasks"}</h3>
      {tasks.length === 0 ? (
        <p className="rw-fhelp">
          {d && SCHEDULED.includes(d.outcome)
            ? "The decision schedules work, but no task does it yet: add one, or use an existing task."
            : "No tasks yet."}
        </p>
      ) : (
        <ul className="rim-tlist">
          {tasks.map((t, i) => (
            <li key={t.id}>
              <span className="rim-tmain">
                <LevelIcon type="task" className="rw-ic rw-ic-task" />
                <span className="rim-tbody">
                  <span className="rim-tname">{t.text || t.name}</span>
                  <span className="rw-fhelp">
                    {[every(t), OUTCOME_LABEL[t.outcome] || null, i === 0 && tasks.length > 1 ? "the decision's own" : null,
                      t.shared_with ? `shared with ${plural(t.shared_with, "other failure mode")}` : null].filter(Boolean).join(" · ")}
                  </span>
                  {t.instructions && <span className="rim-tinst">{t.instructions}</span>}
                </span>
              </span>
              <span className="rim-tacts">
                <button type="button" className="link" disabled={busy} onClick={() => { setFailed(null); setForm({ mode: "edit", task: t }); }}
                        aria-label={`Edit ${t.name}`}>Edit…</button>
                <button type="button" className="link" disabled={busy} onClick={() => remove(t)} aria-label={`Remove ${t.name}`}>Remove</button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {form?.mode === "add" || form?.mode === "edit" ? (
        <TaskForm key={form.task?.id || "add"} r={r} task={form.task || null} hint={form.mode === "add" ? secondTaskHint(r) : null}
                  busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                  onSubmit={(body) => run(
                    () => (form.task ? ops.editTask(form.task.id, body) : ops.addTask(r, body)),
                    form.task ? "Saved the task." : "Added the task.",
                  )} />
      ) : form?.mode === "link" ? (
        <LinkForm r={r} ops={ops} busy={busy} failed={failed} onCancel={() => { setForm(null); setFailed(null); }}
                  onFailed={(e) => setFailed(saveErrorText(e, { offline: navigator.onLine === false }))}
                  onSubmit={(taskId) => run(() => ops.linkTask(r, taskId), "Linked the task.")} />
      ) : (
        <div className="rim-tadd">
          <button type="button" className="secondary" disabled={busy} onClick={(e) => { if (e.detail < 2) { setFailed(null); setForm({ mode: "add" }); } }}>
            {tasks.length ? "Add another task…" : "Add a task…"}
          </button>
          <button type="button" className="link" disabled={busy} onClick={(e) => { if (e.detail < 2) { setFailed(null); setForm({ mode: "link" }); } }}>
            Use an existing task…
          </button>
        </div>
      )}
      {failed && !form && <p className="rw-ferr" role="alert">{failed}</p>}
    </section>
  );
}

// Adding a task, or changing one: its name, interval and unit, what kind of
// task it is, its instructions. Saved once (the button says so until the
// server answers); a refusal shows here with everything as typed.
function TaskForm({ r, task, hint, busy, failed, onCancel, onSubmit }) {
  const d = r.ref.decision;
  const [name, setName] = useState(task?.name || "");
  const [interval, setInterval_] = useState(task?.interval != null ? String(task.interval) : "");
  const [unit, setUnit] = useState(task?.unit || startUnit(d || {}));
  const [outcome, setOutcome] = useState(task?.outcome || (d && SCHEDULED.includes(d.outcome) ? d.outcome : ""));
  const [instructions, setInstructions] = useState(task?.instructions || "");
  const nameBox = useRef(null);
  useEffect(() => { nameBox.current?.focus(); }, []);
  const n = Number(interval);
  const can = !!name.trim() && interval.trim() !== "" && Number.isFinite(n) && n > 0 && !busy;
  const units = INTERVAL_UNITS.includes(unit) ? INTERVAL_UNITS : [unit, ...INTERVAL_UNITS];
  return (
    <form className="rim-tform" onSubmit={(e) => {
      e.preventDefault();
      if (!can) return;
      onSubmit({ name: name.trim(), interval: n, unit, outcome: outcome || null, instructions: instructions.trim() });
    }}>
      <h4>{task ? "Change the task" : "Another task for this failure mode"}</h4>
      {task?.shared_with ? (
        <p className="rw-fhelp">It also serves {plural(task.shared_with, "other failure mode")}: the change applies to all of them.</p>
      ) : null}
      {hint && <p className="rw-fhelp rim-thint">{hint}</p>}
      <label className="rw-field">
        <span className="rw-flabel">Task</span>
        <input ref={nameBox} value={name} readOnly={busy} placeholder="e.g. Replace the acid pump at its rated life"
               onChange={(e) => setName(e.target.value)} />
      </label>
      <div className="rim-trow">
        <label className="rw-field">
          <span className="rw-flabel">Every</span>
          <span className="rw-fin">
            <input type="number" inputMode="decimal" min="0" step="any" value={interval} readOnly={busy} aria-label="Interval"
                   onChange={(e) => setInterval_(e.target.value)} />
            <select value={unit} disabled={busy} aria-label="Interval unit" onChange={(e) => setUnit(e.target.value)}>
              {units.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </span>
        </label>
        <label className="rw-field">
          <span className="rw-flabel">Kind of task</span>
          <select value={outcome} disabled={busy} onChange={(e) => setOutcome(e.target.value)}>
            <option value="">Routine work</option>
            {SCHEDULED.map((o) => <option key={o} value={o}>{OUTCOME_LABEL[o]}</option>)}
          </select>
        </label>
      </div>
      <label className="rw-field">
        <span className="rw-flabel">Instructions (optional)</span>
        <textarea rows={2} value={instructions} readOnly={busy} onChange={(e) => setInstructions(e.target.value)} />
      </label>
      {failed && <p className="rw-ferr" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" disabled={!can} aria-busy={busy || undefined}>{busy ? "Saving…" : task ? "Save task" : "Add task"}</button>
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
        <label className="rw-field">
          <span className="rw-flabel">Task</span>
          <select value={picked} disabled={busy} onChange={(e) => setPicked(e.target.value)} aria-label="Existing task">
            <option value="">Choose a task…</option>
            {choices.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}{every(t) ? ` · ${every(t)}` : ""}{t.position?.id !== here ? ` · on ${t.position?.name}` : ""}{t.serves ? ` · serves ${plural(t.serves, "failure mode")}` : ""}
              </option>
            ))}
          </select>
        </label>
      )}
      {failed && <p className="rw-ferr" role="alert">{failed}</p>}
      <div className="rim-tform-acts">
        <button type="button" className="secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" disabled={!picked || busy} aria-busy={busy || undefined}>{busy ? "Linking…" : "Link task"}</button>
      </div>
    </form>
  );
}
