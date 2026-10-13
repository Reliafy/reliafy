import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  addPartUsed, addWorkCost, cancelWorkOrder, checkWorkItem, closeWorkOrder, getWorkOrder, listMaintenanceLocations,
  listMaintenanceParts, logLabour, removeWorkEntry,
  setWorkStatus, updateWorkOrder,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { Field, FormModal, MaintenanceTabs, fmtDate, today } from "../components/MaintenanceParts.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import "./Maintenance.css";

const STATUS_LABELS = {
  open: "open", planned: "planned", in_progress: "in progress", waiting: "waiting", closed: "closed", cancelled: "cancelled",
};

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
  const [modal, setModal] = useState(null);

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
        meta={[wo.type, STATUS_LABELS[wo.status] || wo.status, `opened ${fmtDate(wo.opened)}`, wo.due && `due ${fmtDate(wo.due)}`,
          wo.closed && `closed ${fmtDate(wo.closed)}`].filter(Boolean).join(" · ")}
        id={wo.id}
        menu={wo.status === "open" ? (
          <>
            <button className="ovm-item" onClick={() => setModal("edit")}>Edit work order</button>
            <button className="ovm-item" onClick={() => setModal("cancel")}>Cancel work order</button>
          </>
        ) : null}
      />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}
      {modal === "edit" && <EditWorkOrder wo={wo} onClose={() => setModal(null)} onDone={(d) => { setWo(d); setModal(null); }} />}
      {modal === "cancel" && (
        <FormModal title={`Cancel #${wo.number}`} submitLabel="Cancel it" onClose={() => setModal(null)}
                   onSubmit={async () => { setWo(await cancelWorkOrder(wo.id, "")); setModal(null); }}>
          <p>For work that won't be done (a duplicate, raised by mistake). Work that was done is closed instead.</p>
        </FormModal>
      )}
      {wo.task && <p className="lib-date">From the task “{wo.task.name}”.</p>}
      {!["closed", "cancelled"].includes(wo.status) && (
        <section className="card">
          <div className="maint-row" style={{ marginTop: 0 }}>
            <label className="maint-row" style={{ marginTop: 0, gap: "0.4rem" }}>Status
              <select value={wo.status} onChange={async (e) => setWo(await setWorkStatus(wo.id, e.target.value))}>
                <option value="open">Open</option><option value="planned">Planned</option>
                <option value="in_progress">In progress</option><option value="waiting">Waiting (parts or access)</option>
              </select>
            </label>
            <span className="lib-date">{wo.assignee ? `Assigned to ${wo.assignee}` : "Not assigned"}
              {wo.planned_for ? ` · planned for ${fmtDate(wo.planned_for)}` : ""}</span>
            <button className="crumb-link" onClick={() => setModal("edit")}>Change</button>
          </div>
        </section>
      )}
      {(wo.instructions || wo.checklist.length > 0) && (
        <section className="card">
          <div className="maint-head"><h2>Instructions</h2></div>
          {wo.instructions && <p style={{ whiteSpace: "pre-wrap" }}>{wo.instructions}</p>}
          {wo.checklist.map((c, i) => (
            <label key={i} className="maint-row" style={{ marginTop: "0.25rem", gap: "0.5rem" }}>
              <input type="checkbox" checked={c.done} disabled={["closed", "cancelled"].includes(wo.status)}
                     onChange={async (e) => setWo(await checkWorkItem(wo.id, i, e.target.checked))} />
              <span style={c.done ? { textDecoration: "line-through", color: "var(--muted)" } : null}>{c.text}</span>
            </label>
          ))}
        </section>
      )}
      {wo.status !== "cancelled" && <CostsCard wo={wo} onChanged={setWo} />}

      <MaintenancePhotos title="Photos (before, after, damage)" targetId={wo.id} targetName={wo.position?.name}
                         photos={wo.photos || []} onChanged={refresh} />

      {wo.status === "cancelled" ? (
        <section className="card"><p>Cancelled {fmtDate(wo.closed)}{wo.notes ? `: ${wo.notes}` : ""}.</p></section>
      ) : wo.status === "closed" ? (
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
  const [readings, setReadings] = useState({});
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
      const meterReadings = Object.entries(readings).filter(([, v]) => v !== "")
        .map(([meter_id, value]) => ({ meter_id, value: Number(value) }));
      onClosed(await closeWorkOrder(wo.id, { actions: body, on, notes, readings: meterReadings }));
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
        {(wo.meters || []).map((mt) => (
          <Field key={mt.id} label={`${mt.name} now (${mt.unit}, optional)`}>
            <input type="number" min="0" step="any" value={readings[mt.id] ?? ""}
                   placeholder={mt.reading != null ? `last: ${mt.reading}` : ""}
                   onChange={(e) => setReadings({ ...readings, [mt.id]: e.target.value })} />
          </Field>
        ))}
        <Field label="Notes (optional)"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      </div>
      <div className="maint-row">
        <button onClick={submit} disabled={busy}>{busy ? "Closing…" : "Close work order"}</button>
        {wo.position && <Link to={`/maintenance/positions/${wo.position.id}`} className="lib-date">Back to {wo.position.name}</Link>}
      </div>
    </section>
  );
}

function EditWorkOrder({ wo, onClose, onDone }) {
  const [title, setTitle] = useState(wo.title);
  const [due, setDue] = useState(wo.due || "");
  const [assignee, setAssignee] = useState(wo.assignee || "");
  const [planned, setPlanned] = useState(wo.planned_for || "");
  return (
    <FormModal title="Edit work order" submitLabel="Save" canSubmit={!!title.trim()} onClose={onClose}
               onSubmit={async () => onDone(await updateWorkOrder(wo.id, { title, due, assignee, planned_for: planned }))}>
      <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Assigned to"><input value={assignee} placeholder="a name" onChange={(e) => setAssignee(e.target.value)} /></Field>
      <Field label="Planned for"><input type="date" value={planned} onChange={(e) => setPlanned(e.target.value)} /></Field>
      <Field label="Due"><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
    </FormModal>
  );
}

function money(v) {
  return Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Labour, parts and other costs, with totals. Entries can be added after closing.
function CostsCard({ wo, onChanged }) {
  const [form, setForm] = useState(null); // "labour" | "part" | "cost"
  const [f, setF] = useState({});
  const [error, setError] = useState(null);
  const [catalogue, setCatalogue] = useState(null);
  const [places, setPlaces] = useState([]);
  const openPart = () => {
    setForm("part"); setF({ quantity: 1 });
    if (catalogue === null) {
      listMaintenanceParts().then((d) => setCatalogue(d.parts)).catch(() => setCatalogue([]));
      listMaintenanceLocations().then((d) => setPlaces(d.locations)).catch(() => {});
    }
  };
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async () => {
    setError(null);
    try {
      if (form === "labour") onChanged(await logLabour(wo.id, { hours: Number(f.hours), who: f.who || "", rate: f.rate ? Number(f.rate) : null }));
      if (form === "part") onChanged(await addPartUsed(wo.id, {
        part: f.part_id ? null : f.part, part_id: f.part_id || null, from_location_id: f.part_id && f.from ? f.from : null,
        quantity: Number(f.quantity || 1), unit_cost: f.unit_cost ? Number(f.unit_cost) : null,
      }));
      if (form === "cost") onChanged(await addWorkCost(wo.id, { description: f.description, amount: Number(f.amount) }));
      setForm(null); setF({});
    } catch (e) { setError(e.message); }
  };
  const remove = async (id) => onChanged(await removeWorkEntry(id));
  const t = wo.totals;
  const rows = [
    ...wo.labour.map((e) => ({ id: e.id, what: `Labour${e.who ? `: ${e.who}` : ""}`, detail: `${e.hours} h${e.rate ? ` at ${money(e.rate)}` : ""}`, cost: (e.rate || 0) * e.hours })),
    ...wo.parts.map((e) => ({ id: e.id, what: e.part, detail: `${e.quantity}${e.unit_cost ? ` at ${money(e.unit_cost)}` : ""}`, cost: (e.unit_cost || 0) * e.quantity })),
    ...wo.other_costs.map((e) => ({ id: e.id, what: e.description, detail: "", cost: e.amount })),
  ];
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Labour, parts and costs</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={() => { setForm("labour"); setF({}); }}>Log labour</button>
          <button className="secondary" onClick={openPart}>Part used</button>
          <button className="secondary" onClick={() => { setForm("cost"); setF({}); }}>Other cost</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      {form && (
        <div className="maint-action">
          <div className="rcm-form">
            {form === "labour" && <>
              <Field label="Hours"><input type="number" min="0" step="any" autoFocus value={f.hours || ""} onChange={set("hours")} /></Field>
              <Field label="Who (optional)"><input value={f.who || ""} onChange={set("who")} /></Field>
              <Field label="Hourly rate (optional)"><input type="number" min="0" step="any" value={f.rate || ""} onChange={set("rate")} /></Field>
            </>}
            {form === "part" && <>
              {catalogue?.length > 0 && (
                <Field label="From the catalogue (optional)">
                  <select value={f.part_id || ""} onChange={set("part_id")}>
                    <option value="">No: type it below</option>
                    {catalogue.map((pt) => <option key={pt.id} value={pt.id}>{pt.part_number}: {pt.name} ({pt.on_hand} on hand)</option>)}
                  </select>
                </Field>
              )}
              {f.part_id ? (
                <Field label="Take it from stock at (optional)">
                  <select value={f.from || ""} onChange={set("from")}>
                    <option value="">Don't change stock</option>
                    {places.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                  </select>
                </Field>
              ) : (
                <Field label="Part"><input autoFocus value={f.part || ""} placeholder="e.g. 6203 bearing" onChange={set("part")} /></Field>
              )}
              <Field label="Quantity"><input type="number" min="0" step="any" value={f.quantity || ""} onChange={set("quantity")} /></Field>
              <Field label="Cost each (optional)"><input type="number" min="0" step="any" value={f.unit_cost || ""} onChange={set("unit_cost")} /></Field>
            </>}
            {form === "cost" && <>
              <Field label="What for"><input autoFocus value={f.description || ""} placeholder="e.g. Plumber call-out" onChange={set("description")} /></Field>
              <Field label="Amount"><input type="number" min="0" step="any" value={f.amount || ""} onChange={set("amount")} /></Field>
            </>}
          </div>
          <div className="maint-row">
            <button onClick={submit}>Add</button>
            <button className="secondary" onClick={() => setForm(null)}>Cancel</button>
          </div>
        </div>
      )}
      {rows.length === 0 ? <p className="lib-date">Nothing recorded yet.</p> : (
        <table className="lib-table">
          <thead><tr><th>What</th><th>Detail</th><th>Cost</th><th><span className="sr-only">Remove</span></th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}><td>{r.what}</td><td className="lib-date">{r.detail}</td><td>{money(r.cost)}</td>
                <td><button className="crumb-link" onClick={() => remove(r.id)}>remove</button></td></tr>
            ))}
            <tr><td><strong>Total</strong></td><td className="lib-date">{t.hours} h</td><td><strong>{money(t.total)}</strong></td><td /></tr>
          </tbody>
        </table>
      )}
    </section>
  );
}
