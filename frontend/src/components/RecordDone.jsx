import { useState } from "react";
import { recordWorkDone } from "../api.js";
import { fmtDate, today } from "./MaintenanceParts.jsx";
import WorkDoneForm from "./WorkDoneForm.jsx";
import { WorkDoneHistory } from "./MaintenanceTasks.jsx";
import { positionWorkSubject, taskDoneBody, taskDoneText, workDoneBody } from "../workDone.js";

// Recording work with work orders turned off (workOrdersFlag.js): shown only then,
// in the places a work order used to be raised or closed.

// "Record done" on a task, inline in its row: the day it was done (today unless
// changed), then Save. It renews the task as closing its work order would, so its
// next due date, forecasts and spares count from that day.
export function RecordDone({ task, onDone, label = "Record done" }) {
  const [open, setOpen] = useState(false);
  const [on, setOn] = useState(today());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await recordWorkDone(taskDoneBody(task, on));
      setDone(taskDoneText(out, fmtDate));
      setOpen(false);
      onDone?.(out);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <span className="maint-record-done">
        <button type="button" className="secondary sm" onClick={() => { setOpen(true); setDone(null); }}>{label}</button>
        {done && <span className="lib-date" role="status"> {done}</span>}
      </span>
    );
  }
  return (
    <span className="maint-record-done maint-row" style={{ marginTop: 0, gap: "var(--space-2)" }}>
      <input type="date" aria-label={`Day “${task.name || "the task"}” was done`} value={on} max={today()}
             onChange={(e) => setOn(e.target.value)} />
      <button type="button" className="sm" onClick={save} disabled={busy || !on}>{busy ? "Saving…" : "Save"}</button>
      <button type="button" className="ghost sm" onClick={() => setOpen(false)} disabled={busy}>Cancel</button>
      {error && <span className="field-error" role="alert">{error}</span>}
    </span>
  );
}

// "Record what was done" on a position: the same form a work order's close uses
// (what was done, a replacement's failure mode and new item, the day, notes), in
// place on the page. A replacement ends the fitted item's time and starts the new
// one's, as closing a work order does.
export function RecordWorkDone({ position, workOrders = [], onDone }) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState(null);
  const subject = positionWorkSubject(position);
  if (!subject) return <WorkDoneHistory workOrders={workOrders} />;
  return (
    <>
      {!open ? (
        <WorkDoneHistory workOrders={workOrders} action={
          <button type="button" className="secondary" onClick={() => { setOpen(true); setSaved(null); }}>
            Record what was done…
          </button>}>
          <p className="lib-date">
            Work orders are turned off for this workspace. Record a replacement, repair or inspection here; a
            task done is recorded on the task.
          </p>
          {saved && <p className="lib-date" role="status">Recorded on {fmtDate(saved.on)}.</p>}
        </WorkDoneHistory>
      ) : (
        <>
          <WorkDoneForm wo={subject} heading="Record what was done" submitLabel="Record it" busyLabel="Recording…"
                        notesLabel="Notes (optional)" back={false}
                        onSubmit={(payload) => recordWorkDone(workDoneBody(position.id, payload))}
                        onDone={(out) => { setOpen(false); setSaved(out); onDone?.(out); }} />
          <div className="maint-row">
            <button type="button" className="ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </>
      )}
    </>
  );
}
