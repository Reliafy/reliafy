import { useState } from "react";
import { Link } from "react-router-dom";
import { recordWorkOrderReadings } from "../api.js";
import { pointPagePath } from "../measurementsTab.js";
import { boxLabel, boxProblem, clearSent, progressText, readingRows, readingsToSend, rowDetail, takenText } from "../workOrderReadings.js";
import { fmtDate } from "./MaintenanceParts.jsx";

// A work order's "Readings and settings" (workOrderReadings.js): a value box for
// each point it asks for (its tasks' tools, trigger and counter, the settings
// where it is) and the other hand-read points there. Values go in when the work
// order closes (the page passes them to its close) or now, with Record. Nothing
// is forced: an empty box records nothing. A closed work order lists what was
// taken at it. `values` and `setValues` live on the page so the close sees them.
export default function WorkOrderReadings({ wo, values, setValues, onRecorded }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const open = !["closed", "cancelled"].includes(wo.status);
  const rows = readingRows(wo);
  const taken = wo.readings_taken || [];
  if (!rows.length && !taken.length) return null;
  const asked = rows.filter((r) => r.group === "asked");
  const other = rows.filter((r) => r.group === "other");
  const pending = readingsToSend(rows, values);
  const single = wo.task && wo.readings_by_task?.[wo.task.id];
  const set = (id, value) => setValues((v) => ({ ...v, [id]: { value, dirty: true } }));

  const record = async () => {
    setBusy(true);
    setError(null);
    try {
      const sent = pending;
      const fresh = await recordWorkOrderReadings(wo.id, sent);
      setValues((v) => clearSent(v, sent));
      onRecorded(fresh);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const problems = rows.filter((r) => values[r.id]?.dirty && boxProblem(r, values[r.id]?.value));
  const box = (r) => {
    const problem = values[r.id]?.dirty ? boxProblem(r, values[r.id]?.value) : "";
    return (
    <div key={r.id} className="wor-row">
      <label className="wor-label" htmlFor={`wor-${r.id}`}>
        <span className="wor-name">{boxLabel(r)}</span>
        <span className="lib-date wor-detail">{rowDetail(r)}</span>
      </label>
      <input id={`wor-${r.id}`} type="number" inputMode="decimal" step="any" className="wor-input"
             value={values[r.id]?.value ?? ""} placeholder={r.last != null ? `last: ${r.last}` : ""}
             min={r.range[0] ?? undefined} max={r.range[1] ?? undefined}
             aria-invalid={problem ? "true" : undefined} aria-describedby={problem ? `wor-${r.id}-why` : undefined}
             onChange={(e) => set(r.id, e.target.value)} />
      {problem && <p className="field-error wor-problem" id={`wor-${r.id}-why`} role="alert">{problem}</p>}
    </div>
    );
  };

  return (
    <section className="card" aria-label="Readings and settings">
      <div className="maint-head">
        <h2>Readings and settings</h2>
        {single && <span className="lib-date">{progressText(single)}</span>}
      </div>
      {error && <div className="card error" role="alert">{error}</div>}
      {open && (
        <>
          <p className="lib-date">Fill in what was read or set; an empty box records nothing. They're recorded when you close the
            work order, or now with Record, and each one's history names this work order.</p>
          {asked.map(box)}
          {other.length > 0 && (
            <details className="wor-other" open={!asked.length}>
              <summary>Other measurements here ({other.length})</summary>
              {other.map(box)}
            </details>
          )}
          <div className="maint-row">
            <button type="button" className="secondary" disabled={busy || !pending.length || problems.length > 0} onClick={record}>
              {busy ? "Recording…" : pending.length > 1 ? `Record ${pending.length} values` : "Record"}
            </button>
          </div>
        </>
      )}
      {taken.length > 0 && (
        <>
          <h3 className="wor-taken-head">Taken at this work order</h3>
          <ul className="maint-list">
            {taken.map((r) => (
              <li key={r.id}>
                <Link to={pointPagePath(r.point)}>{takenText(r)}</Link>
                <span className="lib-date"> · {fmtDate(r.on)}{r.task ? ` · ${r.task.name}` : ""}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
