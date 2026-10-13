import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { closeWorkOrder, getWorkOrder } from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { Field, fmtDate, today } from "../components/MaintenanceParts.jsx";
import "./Maintenance.css";

const KINDS = [
  { id: "replace", label: "Replaced it" },
  { id: "repair", label: "Repaired it" },
  { id: "inspect", label: "Inspected it" },
  { id: "other", label: "Other work" },
];

// A work order: what it's for, and closing it with what was done. A
// replacement ends the fitted item's time here and starts the new one's.
export default function MaintenanceWorkOrder() {
  const { id } = useParams();
  const [wo, setWo] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    getWorkOrder(id).then(setWo).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);

  if (error && !wo) return <div className="app"><div className="card error">{error}</div></div>;
  if (!wo) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Maintenance", to: "/maintenance" },
          ...(wo.position ? [{ label: wo.position.name, to: `/maintenance/positions/${wo.position.id}` }] : [])]}
        title={`#${wo.number} ${wo.title}`}
        meta={[wo.type, wo.status, `opened ${fmtDate(wo.opened)}`, wo.due && `due ${fmtDate(wo.due)}`,
          wo.closed && `closed ${fmtDate(wo.closed)}`].filter(Boolean).join(" · ")}
        id={wo.id}
      />
      {error && <div className="card error">{error}</div>}
      {wo.task && <p className="lib-date">From the task “{wo.task.name}”.</p>}

      {wo.status === "closed" ? (
        <section className="card">
          <div className="maint-head"><h2>What was done</h2></div>
          {wo.actions.length === 0 ? <p className="lib-date">Closed with no actions recorded.</p> : (
            <ul className="maint-list">
              {wo.actions.map((a) => (
                <li key={a.id}>
                  <strong>{KINDS.find((k) => k.id === a.kind)?.label || a.kind}</strong>
                  {a.finding && <span> · finding: {a.finding.replace("_", " ")}</span>}
                  {a.failure_mode && <span> · failure mode: {a.failure_mode.text}</span>}
                  {a.removed && <span> · out: {a.removed.name}{a.removed.serial ? ` (${a.removed.serial})` : ""}</span>}
                  {a.fitted && <span> · in: {a.fitted.name}{a.fitted.serial ? ` (${a.fitted.serial})` : ""}</span>}
                  {a.notes && <div className="lib-date">{a.notes}</div>}
                </li>
              ))}
            </ul>
          )}
          {wo.notes && <p>{wo.notes}</p>}
        </section>
      ) : (
        <CloseForm wo={wo} onClosed={setWo} />
      )}
    </div>
  );
}

function CloseForm({ wo, onClosed }) {
  const [on, setOn] = useState(today());
  const [notes, setNotes] = useState("");
  const [actions, setActions] = useState([{ kind: wo.type === "inspection" ? "inspect" : "replace" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const update = (i, patch) => setActions((as) => as.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const removeAt = (i) => setActions((as) => as.filter((_, j) => j !== i));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = actions.map((a) => ({
        kind: a.kind,
        failure_mode_id: a.failure_mode_id || null,
        finding: a.kind === "inspect" ? a.finding || null : null,
        notes: a.notes || "",
        new_item: a.kind === "replace" && a.new_name ? { name: a.new_name, serial: a.new_serial || "" } : null,
      }));
      onClosed(await closeWorkOrder(wo.id, { actions: body, on, notes }));
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  return (
    <section className="card">
      <div className="maint-head"><h2>Close it</h2></div>
      {error && <div className="card error">{error}</div>}
      <p className="lib-date">
        Fitted now: {wo.fitted ? <strong>{wo.fitted.item?.name}</strong> : "nothing"}
        {wo.fitted?.item?.serial && ` (${wo.fitted.item.serial})`}
      </p>
      {actions.map((a, i) => (
        <div key={i} className="maint-action">
          <div className="rcm-form">
            <Field label="What was done">
              <select value={a.kind} onChange={(e) => update(i, { kind: e.target.value })}>
                {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
              </select>
            </Field>
            {a.kind === "inspect" && (
              <Field label="Finding">
                <select value={a.finding || ""} onChange={(e) => update(i, { finding: e.target.value })}>
                  <option value="">Choose…</option>
                  <option value="ok">OK</option>
                  <option value="degraded">Degraded</option>
                  <option value="found_failed">Found failed</option>
                </select>
              </Field>
            )}
            {wo.failure_modes.length > 0 && a.kind !== "other" && (
              <Field label={a.kind === "replace" ? "Did it fail? Which way" : "Failure mode (optional)"}>
                <select value={a.failure_mode_id || ""} onChange={(e) => update(i, { failure_mode_id: e.target.value })}>
                  <option value="">{a.kind === "replace" ? "No, a planned replacement" : "None"}</option>
                  {wo.failure_modes.map((m) => <option key={m.id} value={m.id}>{m.text}</option>)}
                </select>
              </Field>
            )}
            {a.kind === "replace" && (
              <>
                <Field label="New item">
                  <input value={a.new_name || ""} placeholder={wo.fitted?.item?.name || "e.g. Rheem 315 L"}
                         onChange={(e) => update(i, { new_name: e.target.value })} />
                </Field>
                <Field label="New item's serial (optional)">
                  <input value={a.new_serial || ""} onChange={(e) => update(i, { new_serial: e.target.value })} />
                </Field>
              </>
            )}
            <Field label="Notes (optional)">
              <input value={a.notes || ""} onChange={(e) => update(i, { notes: e.target.value })} />
            </Field>
          </div>
          {actions.length > 1 && <button className="secondary" onClick={() => removeAt(i)}>Remove this action</button>}
        </div>
      ))}
      <div className="maint-row">
        <button className="secondary" onClick={() => setActions((as) => [...as, { kind: "repair" }])}>Add another action</button>
      </div>
      <div className="rcm-form">
        <Field label="Done on"><input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
        <Field label="Notes (optional)"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <div className="maint-row">
        <button onClick={submit} disabled={busy}>{busy ? "Closing…" : "Close work order"}</button>
        {wo.position && <Link to={`/maintenance/positions/${wo.position.id}`} className="lib-date">Back to {wo.position.name}</Link>}
      </div>
    </section>
  );
}
