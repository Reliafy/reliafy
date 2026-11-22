import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createSubjectTask, openWorkOrder, retireMaintenanceTask, setTaskLastDone, updateMaintenanceTask,
} from "../api.js";
import { PlusIcon, RowLink, rowOpen } from "./LibRows.jsx";
import { DueChip, Field, FormModal, TASK_SOURCES, everyText, fmtDate, today } from "./MaintenanceParts.jsx";
import { subjectPath, taskUnits, whileStoredText } from "../maintenanceSubjects.js";
import { AGE_NOTE, TASK_HINT, tooLong } from "../maintenanceText.js";
import { TaskMeasurementField } from "./TaskMeasurement.jsx";
import HowOften from "./HowOften.jsx";
import { LAST_DONE_NOTE, planWords } from "../workManagement.js";
import { formFromTask, howOftenPreview, howOftenProblem, taskAnchor, taskBody } from "../howOften.js";
import { Checkbox, Select } from "./ui/Controls.jsx";

// What a task's "how often" shows under it: the next dates, from when it was last done (else today).
function preview(how, task) {
  const day = today();
  const p = howOftenPreview(how, { from: task?.last_done || day, after: !!task?.last_done, anchor: taskAnchor(task, day) });
  return { dates: p.dates, datesLead: p.lead, datesAfter: p.after, datesNote: p.note };
}

import { useWorkManagementOn } from "../ConfigProvider.jsx";
import { DateInput } from "./ui/DateTimeInput.jsx";

// What a task on each kind of subject is for, under the Add task form.
const SUBJECT_NOTES = {
  position: "It falls due, raises work orders and counts again from each new item fitted, like a task from an RCM decision.",
  item: "It follows this item wherever it goes (another position, or a store), and its work orders say where it is. "
    + "By use, it counts the item's own counter, else the use it has had at each position it was fitted to.",
  location: "It goes by the calendar and raises one work order for the place: a round or an area inspection.",
};
// The same with work management off (workManagement.js): a task in a hypothetical plan.
const PLAN_SUBJECT_NOTES = {
  position: "It goes in the plan the forecasts use, and counts again from each new item fitted, like a task from an RCM decision.",
  item: "It follows this item wherever it goes (another position, or a store). "
    + "By use, it counts the item's own counter, else the use it has had at each position it was fitted to.",
  location: "It goes by the calendar, for the place: a round or an area inspection.",
};

// A subject's tasks: what's scheduled on a position, an item or a location, with
// adding, editing, when each was last done and a work order for it. On a position,
// the fitted item's own tasks show too (they fall due on their own, and leave with it).
export function TasksCard({ subject, tasks, itemTasks = [], modes = [], counters = [], onChanged, emptyText }) {
  const navigate = useNavigate();
  // Work management off (workManagement.js): a hypothetical plan, with no work order
  // column; last done is a plan input, set on its row.
  const workOrders = useWorkManagementOn();
  const words = planWords(workOrders);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const done = () => { setModal(null); onChanged(); };

  const workOrderFor = async (task) => {
    try {
      // No title: the server makes it from the task's name, shortened if it's long.
      const wo = await openWorkOrder({ type: "preventive", task_id: task.id, due: task.next_due });
      navigate(`/maintenance/work-orders/${wo.id}`);
    } catch (e) {
      setError(e.message);
    }
  };

  const rows = (list, ofItem) => list.map((t) => (
    <tr key={t.id}>
      <td>{t.name}
        {ofItem && <> <Link to={subjectPath(t.subject)} className="maint-badge" title="The fitted item's own task: it leaves with the item">
          {t.subject.name}'s</Link></>}
        <div className="lib-date">{[TASK_SOURCES[t.source], t.reference, t.failure_mode && `prevents: ${t.failure_mode.text}`,
          t.trade && `needs: ${t.trade}`, whileStoredText(t), t.include_positions && "lists the positions here"]
          .filter(Boolean).join(" · ")}</div></td>
      <td className="lib-date">{everyText(t)}</td>
      <td className="lib-date">
        <button type="button" className="crumb-link" title="When was it last done?" onClick={() => setModal({ lastDone: t })}>
          {t.last_done ? fmtDate(t.last_done) : "set"}
        </button>
      </td>
      <td><DueChip task={t} />{t.proposal && <div><span className="maint-badge">change proposed</span></div>}</td>
      {workOrders && <td>{t.open_work_order
        ? <Link to={`/maintenance/work-orders/${t.open_work_order.id}`}>#{t.open_work_order.number}</Link>
        : <button className="secondary" onClick={() => workOrderFor(t)}>Create</button>}</td>}
      <td><button className="crumb-link" onClick={() => setModal({ task: t })}>Edit</button></td>
    </tr>
  ));

  return (
    <section className="card">
      <div className="maint-head">
        <h2>Tasks</h2>
        <button className="secondary" onClick={() => setModal("add")}><PlusIcon /> Add task</button>
      </div>
      {error && <div className="card error">{error}</div>}
      {tasks.length === 0 && itemTasks.length === 0 ? (
        <p className="lib-date">{emptyText || "No scheduled tasks yet."}</p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Task</th><th>Every</th><th>Last done</th><th>{words.next}</th>{workOrders && <th>Work order</th>}<th><span className="sr-only">Edit</span></th></tr></thead>
          <tbody>{rows(tasks, false)}{rows(itemTasks, true)}</tbody>
        </table></div>
      )}
      {!workOrders && (tasks.length > 0 || itemTasks.length > 0) && <p className="lib-date">{LAST_DONE_NOTE}</p>}
      {modal === "add" && <AddTaskModal subject={subject} modes={modes} counters={counters} onClose={() => setModal(null)} onDone={done} />}
      {modal?.task && <TaskModal task={modal.task} modes={modes} onClose={() => setModal(null)} onDone={done} />}
      {modal?.lastDone && <LastDoneModal task={modal.lastDone} onClose={() => setModal(null)} onDone={done} />}
    </section>
  );
}

// A scheduled task added by hand: from the maker's manual, a regulation, or practice.
function AddTaskModal({ subject, modes, counters, onClose, onDone }) {
  const workOrders = useWorkManagementOn();
  const kind = subject.kind;
  const units = taskUnits(kind);
  const [how, setHow] = useState(() => formFromTask(null));
  const [f, setF] = useState({
    name: "", outcome: "", source: "manual",
    reference: "", point_id: "", failure_mode_id: "", instructions: "", checklist: "", last_done: "", trade: "",
    while_stored: "run", include_positions: false,
  });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title={`Add a task to ${subject.name}`} submitLabel="Add task" canSubmit={!!f.name.trim() && !tooLong(f.name) && !howOftenProblem(how)}
               onClose={onClose} onSubmit={async () => onDone(await createSubjectTask(subject, {
                 name: f.name, ...taskBody(how, today()), outcome: f.outcome || null,
                 also_interval: how.also ? Number(how.also) : null,
                 source: f.source, reference: f.reference, point_id: f.point_id || null, trade: f.trade,
                 failure_mode_id: f.failure_mode_id || null, instructions: f.instructions,
                 checklist: f.checklist.split("\n").map((x) => x.trim()).filter(Boolean), last_done: f.last_done || null,
                 ...(kind === "item" ? { while_stored: f.while_stored } : {}),
                 ...(kind === "location" ? { include_positions: f.include_positions } : {}),
               }))}>
      <Field label="Task" text={f.name} hint={TASK_HINT}><input autoFocus value={f.name} onChange={set("name")}
             placeholder={kind === "item" ? "e.g. Calibrate, Statutory inspection, Overhaul"
               : kind === "location" ? "e.g. Area walkdown, Ex inspection" : "e.g. Replace sacrificial anode"} /></Field>
      <HowOften value={how} onChange={setHow} units={units} withAlso problem={how.every !== "" ? howOftenProblem(how) : null}
                {...preview(how, null)} />
      {counters.length > 0 && (
        <Field label="Measurement (for a task by use, optional)">
          <Select value={f.point_id} onChange={set("point_id")}>
            <option value="">{kind === "item" ? "Automatic: its own counter in that unit, else its use where fitted" : "Automatic: this position's counter in that unit"}</option>
            {counters.map((mp) => <option key={mp.id} value={mp.id}>{mp.name} ({mp.unit})</option>)}
          </Select>
        </Field>
      )}
      {kind === "item" && (
        <Field label="While it's out of a position (in a store, or away)">
          <Select value={f.while_stored} onChange={set("while_stored")}>
            <option value="run">Keep counting the calendar (it can fall due in the store)</option>
            <option value="pause">Pause: the days out of a position don't count</option>
          </Select>
        </Field>
      )}
      {kind === "location" && (
        <Checkbox className="maint-row" checked={f.include_positions} onChange={(e) => setF({ ...f, include_positions: e.target.checked })}
                  label={workOrders ? "List every position here on its work orders (a walkdown: one line each)"
                    : "List every position here (a walkdown: one line each)"} />
      )}
      <Field label="What kind of task">
        <Select value={f.outcome} onChange={set("outcome")}>
          <option value="">Routine work (lubricate, clean, adjust, inspect)</option>
          <option value="fixed_interval">Replace at age (every … since it was last done)</option>
          <option value="failure_finding">Check a hidden function (failure-finding)</option>
          <option value="on_condition">Check condition</option>
        </Select>
      </Field>
      {f.outcome === "fixed_interval" && <p className="lib-date">{AGE_NOTE}</p>}
      <Field label="Where it comes from">
        <Select value={f.source} onChange={set("source")}>
          {["manual", "oem", "statutory", "other"].map((k) => <option key={k} value={k}>{TASK_SOURCES[k]}</option>)}
        </Select>
      </Field>
      <Field label="Reference (optional)"><input value={f.reference} placeholder="e.g. Owner's manual §7, AS 1851 table 5" onChange={set("reference")} /></Field>
      {kind === "position" && modes.length > 0 && (
        <Field label="Failure mode it prevents (optional)">
          <Select value={f.failure_mode_id} onChange={set("failure_mode_id")}>
            <option value="">None</option>
            {modes.map((m) => <option key={m.id} value={m.id}>{m.text}</option>)}
          </Select>
        </Field>
      )}
      <Field label="Who may do it (optional)"><input value={f.trade} placeholder="e.g. licensed electrician" onChange={set("trade")} /></Field>
      <Field label="Instructions (optional)"><textarea rows={3} value={f.instructions} onChange={set("instructions")} /></Field>
      <Field label="Checklist, one step per line (optional)"><textarea rows={3} value={f.checklist} onChange={set("checklist")} /></Field>
      <Field label="Last done (optional)"><DateInput value={f.last_done} max={today()} onChange={set("last_done")} /></Field>
      <p className="lib-date">{(workOrders ? SUBJECT_NOTES : PLAN_SUBJECT_NOTES)[kind]}</p>
    </FormModal>
  );
}

function TaskModal({ task, modes = [], onClose, onDone }) {
  const workOrders = useWorkManagementOn();
  const kind = task.subject?.kind || "position";
  const units = taskUnits(kind);
  const byHand = task.source !== "rcm";
  const [mode, setMode] = useState(task.failure_mode?.id || "");
  const [source, setSource] = useState(task.source);
  const [reference, setReference] = useState(task.reference || "");
  const [name, setName] = useState(task.name);
  const [how, setHow] = useState(() => formFromTask(task));
  const unit = how.unit;
  const [instructions, setInstructions] = useState(task.instructions || "");
  const [checklist, setChecklist] = useState((task.checklist || []).join("\n"));
  const [trade, setTrade] = useState(task.trade || "");
  const [whileStored, setWhileStored] = useState(task.while_stored || "run");
  const [includePositions, setIncludePositions] = useState(!!task.include_positions);
  const [meas, setMeas] = useState({ body: null, error: null });
  const [busy, setBusy] = useState(false);
  return (
    <FormModal title="Edit task" submitLabel="Save" canSubmit={!!name.trim() && !tooLong(name) && !howOftenProblem(how) && !meas.error} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenanceTask(task.id, {
                 ...(meas.body || {}),
                 name, ...taskBody(how, taskAnchor(task, today())),
                 instructions, checklist: checklist.split("\n").map((x) => x.trim()).filter(Boolean), trade,
                 ...(byHand ? { source, reference } : {}),
                 ...(byHand && kind === "position" ? { failure_mode_id: mode || null } : {}),
                 ...(kind === "item" ? { while_stored: whileStored } : {}),
                 ...(kind === "location" ? { include_positions: includePositions } : {}),
               }))}>
      {kind !== "position" && task.subject && (
        <p className="lib-date">On the {kind} <Link to={subjectPath(task.subject)}>{task.subject.name}</Link>.</p>
      )}
      <Field label="Task" text={name} hint={TASK_HINT}><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <HowOften value={how} onChange={setHow} units={units} withAlso problem={howOftenProblem(how)} {...preview(how, task)} />
      {kind !== "location" && (
        <TaskMeasurementField taskId={task.id} unit={unit} disabled={busy} onChange={(body, error) => setMeas({ body, error })} />
      )}
      {meas.error && <p className="lib-date">{meas.error}</p>}
      {kind === "item" && (
        <Field label="While it's out of a position (in a store, or away)">
          <Select value={whileStored} onChange={(e) => setWhileStored(e.target.value)}>
            <option value="run">Keep counting the calendar</option>
            <option value="pause">Pause: the days out of a position don't count</option>
          </Select>
        </Field>
      )}
      {kind === "location" && (
        <Checkbox className="maint-row" checked={includePositions} onChange={(e) => setIncludePositions(e.target.checked)}
                  label={workOrders ? "List every position here on its work orders" : "List every position here"} />
      )}
      <Field label="Who may do it: trade, licence or competency (optional)"><input value={trade}
             placeholder="e.g. Licensed electrician" onChange={(e) => setTrade(e.target.value)} /></Field>
      <Field label="Instructions (optional)"><textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} /></Field>
      <Field label="Checklist, one step per line (optional)"><textarea rows={4} value={checklist}
             placeholder={"Isolate power\nDrain 10 L\nFit the new anode"} onChange={(e) => setChecklist(e.target.value)} /></Field>
      {workOrders && <p className="lib-date">Each work order this task raises gets the trade, the instructions and the checklist to tick off.</p>}
      {byHand && <>
        <Field label="Where it comes from">
          <Select value={source} onChange={(e) => setSource(e.target.value)}>
            {["manual", "oem", "statutory", "other"].map((k) => <option key={k} value={k}>{TASK_SOURCES[k]}</option>)}
          </Select>
        </Field>
        <Field label="Reference (optional)"><input value={reference} onChange={(e) => setReference(e.target.value)} /></Field>
        {kind === "position" && modes.length > 0 && (
          <>
            <Field label="Failure mode it prevents">
              <Select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="">None</option>
                {modes.map((m) => <option key={m.id} value={m.id}>{m.text}</option>)}
              </Select>
            </Field>
            <p className="lib-date">Linked to a failure mode, this task is the one its RCM decision schedules.</p>
          </>
        )}
      </>}
      <button className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); await retireMaintenanceTask(task.id, ""); onDone();
      }}>Retire this task</button>
    </FormModal>
  );
}

// When a task was last done. With work management off it's a plan input only (the
// forecasts count from it), and it can be cleared to fall back to the default.
function LastDoneModal({ task, onClose, onDone }) {
  const workOrders = useWorkManagementOn();
  const [on, setOn] = useState(task.last_done || today());
  return (
    <FormModal title={`Last done: ${task.name}`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => onDone(await setTaskLastDone(task.id, on || "none"))}>
      <p className="lib-date">{workOrders ? "When this was last done, so the next due date counts from then." : LAST_DONE_NOTE}</p>
      <Field label={workOrders ? "Last done on" : "Last done on (optional)"}>
        <DateInput value={on} max={today()} onChange={(e) => setOn(e.target.value)} />
      </Field>
      {!workOrders && task.last_done && (
        <button type="button" className="ghost sm" onClick={() => setOn("")}>Clear it</button>
      )}
    </FormModal>
  );
}

// The work orders on an item or a location, newest first.
export function WorkOrdersCard({ workOrders, emptyText = "None yet." }) {
  const navigate = useNavigate();
  // Work management off (workManagement.js): the work orders are kept, only not shown.
  const shown = useWorkManagementOn();
  if (!shown) return null;
  return (
    <section className="card">
      <div className="maint-head"><h2>Work orders</h2></div>
      {workOrders.length === 0 ? <p className="lib-date">{emptyText}</p> : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>#</th><th>Title</th><th>Type</th><th>Status</th><th>Opened</th><th>Closed</th></tr></thead>
          <tbody>
            {workOrders.map((w) => (
              <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, `/maintenance/work-orders/${w.id}`)}>
                <td>{w.number}</td>
                <td><RowLink to={`/maintenance/work-orders/${w.id}`}>{w.title}</RowLink>{w.under_warranty && <> <span className="maint-badge">warranty</span></>}</td>
                <td>{w.type}</td><td>{w.status}</td>
                <td className="lib-date">{fmtDate(w.opened)}</td><td className="lib-date">{fmtDate(w.closed)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}
