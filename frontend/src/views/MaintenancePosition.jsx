import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  applyRcmToPosition,
  fitMaintenanceItem,
  getMaintenanceOverview,
  getMaintenancePosition,
  listRcmStudies,
  openWorkOrder,
  addMaintenanceMeter,
  correctMaintenanceFitment,
  recordMaintenanceReading,
  removeMaintenanceItem,
  retireMaintenancePosition,
  retireMaintenanceTask,
  setTaskLastDone,
  updateMaintenancePosition,
  updateMaintenanceTask,
  voidMaintenanceFitment,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import {
  DueChip, Field, FormModal, LifeTable, MaintenanceTabs, OUTCOME_LABELS, everyText, flatten, fmtDate, today,
} from "../components/MaintenanceParts.jsx";
import { NewPositionModal } from "./MaintenanceHome.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import "./Maintenance.css";

// One position: what's fitted, its RCM failure modes and tasks, its work
// orders, and the life data its fitments give.
export default function MaintenancePosition() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [positions, setPositions] = useState([]);

  const refresh = useCallback(() => {
    getMaintenancePosition(id).then(setP).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);

  const openChild = () => {
    getMaintenanceOverview().then((d) => setPositions(flatten(d.tree))).catch(() => {});
    setModal("child");
  };

  const workOrderForTask = async (task) => {
    try {
      const wo = await openWorkOrder({
        position_id: id, title: task.name, type: "preventive", task_id: task.id, due: task.next_due,
      });
      navigate(`/maintenance/work-orders/${wo.id}`);
    } catch (e) {
      setError(e.message);
    }
  };

  if (error && !p) return <div className="app"><div className="card error">{error}</div></div>;
  if (!p) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Maintenance", to: "/maintenance" }, ...p.path.map((a) => ({
          label: a.name, to: a.kind === "Item" ? `/maintenance/items/${a.id}` : `/maintenance/positions/${a.id}` }))]}
        title={p.name}
        meta={[p.tag, p.position_class, p.description].filter(Boolean).join(" · ") || "Position"}
        id={p.id}
        menu={
          <>
            <button className="ovm-item" onClick={() => setModal("edit")}>Edit position</button>
            <button className="ovm-item" onClick={() => setModal("retire")}>Retire position</button>
          </>
        }
        actions={
          <>
            <button className="secondary" onClick={openChild}><PlusIcon /> Position inside</button>
            <button className="secondary" onClick={() => setModal("rcm")}>Apply an RCM study</button>
          </>
        }
        primary={<button onClick={() => setModal("wo")}>New work order</button>}
      />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}

      <section className="card">
        <div className="maint-head">
          <h2>Fitted</h2>
          {p.fitted ? (
            <button className="secondary" onClick={() => setModal("remove")}>Remove</button>
          ) : (
            <button onClick={() => setModal("fit")}>Fit an item</button>
          )}
        </div>
        {p.fitted ? (
          <p>
            <strong>{p.fitted.item ? <Link to={`/maintenance/items/${p.fitted.item.id}`}>{p.fitted.item.name}</Link> : "?"}</strong>
            {p.fitted.item?.serial && <span className="lib-date"> · serial {p.fitted.item.serial}</span>}
            <span className="lib-date"> · since {fmtDate(p.fitted.from)}</span>
          </p>
        ) : (
          <p className="lib-date">Nothing fitted. Fit the item doing this job, with the date it went in.</p>
        )}
      </section>

      {p.fitted?.item && (
        <MaintenancePhotos title={`Photos of the ${p.fitted.item.name}`} targetId={p.fitted.item.id}
                           targetName={p.fitted.item.name} photos={p.item_photos} onChanged={refresh} />
      )}
      <MaintenancePhotos title={p.fitted?.item ? `Photos of the ${p.name} position` : "Photos"} targetId={p.id}
                         targetName={p.name} photos={p.photos} onChanged={refresh} />
      {p.coordinates && (
        <p className="lib-date">
          Location: {p.coordinates.lat}, {p.coordinates.lon}
          {p.coordinates.source === "photo" ? " (from a photo)" : ""}
        </p>
      )}

      <section className="card">
        <div className="maint-head"><h2>Tasks</h2></div>
        {p.tasks.length === 0 ? (
          <p className="lib-date">No scheduled tasks. Apply an RCM study whose decisions have intervals.</p>
        ) : (
          <table className="lib-table">
            <thead><tr><th>Task</th><th>Every</th><th>Last done</th><th>Next due</th><th>Work order</th><th><span className="sr-only">Edit</span></th></tr></thead>
            <tbody>
              {p.tasks.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td className="lib-date">{everyText(t)}</td>
                  <td className="lib-date">
                    <button type="button" className="crumb-link" title="When was it last done?"
                            onClick={() => setModal({ lastDone: t })}>
                      {t.last_done ? fmtDate(t.last_done) : "set"}
                    </button>
                  </td>
                  <td><DueChip task={t} /></td>
                  <td>{t.open_work_order
                    ? <Link to={`/maintenance/work-orders/${t.open_work_order.id}`}>#{t.open_work_order.number}</Link>
                    : <button className="secondary" onClick={() => workOrderForTask(t)}>Create</button>}</td>
                  <td><button className="crumb-link" onClick={() => setModal({ task: t })}>Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Meters</h2>
          <button className="secondary" onClick={() => setModal("meter")}>Add a meter</button>
        </div>
        {p.meters.length === 0 ? (
          <p className="lib-date">No meters. Add one (run hours, cycles, km) for tasks that go by use.</p>
        ) : (
          <table className="lib-table">
            <thead><tr><th>Meter</th><th>Reading</th><th>Read</th><th>Rate</th><th><span className="sr-only">Read</span></th></tr></thead>
            <tbody>
              {p.meters.map((mt) => (
                <tr key={mt.id}>
                  <td>{mt.name}</td>
                  <td>{mt.reading ?? "—"} {mt.reading != null ? mt.unit : ""}</td>
                  <td className="lib-date">{fmtDate(mt.read_on)}</td>
                  <td className="lib-date">{mt.rate_per_day != null ? `${mt.rate_per_day} ${mt.unit} a day` : "needs two readings"}</td>
                  <td><button className="secondary" onClick={() => setModal({ reading: mt })}>Record reading</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="maint-head"><h2>Work orders</h2></div>
        {p.work_orders.length === 0 ? (
          <p className="lib-date">None yet.</p>
        ) : (
          <table className="lib-table">
            <thead><tr><th>#</th><th>Title</th><th>Type</th><th>Status</th><th>Opened</th><th>Closed</th></tr></thead>
            <tbody>
              {p.work_orders.map((w) => (
                <tr key={w.id} className="lib-row" onClick={() => navigate(`/maintenance/work-orders/${w.id}`)}>
                  <td>{w.number}</td><td>{w.title}</td><td>{w.type}</td><td>{w.status}</td>
                  <td className="lib-date">{fmtDate(w.opened)}</td><td className="lib-date">{fmtDate(w.closed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="maint-head"><h2>Failure modes</h2></div>
        {p.failure_modes.length === 0 ? (
          <p className="lib-date">None. They come from an RCM study.</p>
        ) : (
          <table className="lib-table">
            <thead><tr><th>Failure mode</th><th>Functional failure</th><th>Consequence</th><th>Decision</th></tr></thead>
            <tbody>
              {p.failure_modes.map((m) => (
                <tr key={m.id}>
                  <td>{m.text}</td>
                  <td className="lib-date">{m.failure || "—"}</td>
                  <td className="lib-date">{m.consequence || "—"}</td>
                  <td className="lib-date">{OUTCOME_LABELS[m.outcome] || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Life data</h2>
          <span className="lib-date">one row per item fitted here</span>
        </div>
        {p.life_data.length === 0 ? (
          <p className="lib-date">No fitments yet.</p>
        ) : (
          <LifeTable rows={p.life_data} onFix={(r) => setModal({ fix: r })} />
        )}
      </section>

      {p.children.length > 0 && (
        <section className="card">
          <div className="maint-head"><h2>Positions inside</h2></div>
          <ul className="maint-list">
            {p.children.map((c) => <li key={c.id}><Link to={`/maintenance/positions/${c.id}`}>{c.name}</Link></li>)}
          </ul>
        </section>
      )}

      {modal === "edit" && <EditPositionModal p={p} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "retire" && (
        <FormModal title={`Retire ${p.name}`} submitLabel="Retire" onClose={() => setModal(null)}
                   onSubmit={async () => { await retireMaintenancePosition(p.id, ""); navigate("/maintenance"); }}>
          <p>It leaves the plant tree and stops scheduling tasks. Its history stays. Nothing may be fitted,
            nothing inside it in use, and no work order open.</p>
        </FormModal>
      )}
      {modal === "meter" && <MeterModal positionId={p.id} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.reading && <ReadingModal meter={modal.reading} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.task && <TaskModal task={modal.task} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.fix && <FixModal row={modal.fix} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal?.lastDone && (
        <LastDoneModal task={modal.lastDone} onClose={() => setModal(null)}
                       onDone={() => { setModal(null); refresh(); }} />
      )}
      {modal === "fit" && <FitModal positionId={id} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal === "remove" && <RemoveModal position={p} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal === "rcm" && <ApplyRcmModal positionId={id} onClose={() => setModal(null)} onDone={(d) => { setP(d.position); setModal(null); }} />}
      {modal === "wo" && (
        <NewWorkOrderModal positionId={id} onClose={() => setModal(null)}
                           onDone={(wo) => navigate(`/maintenance/work-orders/${wo.id}`)} />
      )}
      {modal === "child" && (
        <NewPositionModal positions={positions} parentId={id} onClose={() => setModal(null)}
                          onCreated={(c) => navigate(`/maintenance/positions/${c.id}`)} />
      )}
    </div>
  );
}

function FitModal({ positionId, onClose, onDone }) {
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [manufacturer, setManufacturer] = useState("");
  const [on, setOn] = useState(today());
  return (
    <FormModal title="Fit an item" submitLabel="Fit" canSubmit={!!name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await fitMaintenanceItem(positionId, {
                 new_item: { name, serial, part_number: partNumber, manufacturer }, on,
               }))}>
      <Field label="Item"><input autoFocus value={name} placeholder="e.g. Rheem 315 L electric" onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Serial (optional)"><input value={serial} onChange={(e) => setSerial(e.target.value)} /></Field>
      <Field label="Part or model number (optional)"><input value={partNumber} onChange={(e) => setPartNumber(e.target.value)} /></Field>
      <Field label="Manufacturer (optional)"><input value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} /></Field>
      <Field label="Fitted on"><input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      <p className="lib-date">A new item counts as a renewal: this position's tasks count from the day it went in.</p>
    </FormModal>
  );
}

function RemoveModal({ position, onClose, onDone }) {
  const [on, setOn] = useState(today());
  const [reason, setReason] = useState("planned");
  const [mode, setMode] = useState("");
  return (
    <FormModal title={`Remove ${position.fitted.item?.name || "the item"}`} submitLabel="Remove" onClose={onClose}
               onSubmit={async () => onDone(await removeMaintenanceItem(position.id, {
                 on, reason, failure_mode_id: reason === "failure" ? mode || null : null,
               }))}>
      <p className="lib-date">For corrections and moves. Work done on it belongs on a work order.</p>
      <Field label="Removed on"><input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
      <Field label="Why">
        <select value={reason} onChange={(e) => setReason(e.target.value)}>
          <option value="planned">Planned (still working)</option>
          <option value="failure">It failed</option>
          <option value="other">Other</option>
        </select>
      </Field>
      {reason === "failure" && position.failure_modes.length > 0 && (
        <Field label="Failure mode">
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Not known</option>
            {position.failure_modes.map((m) => <option key={m.id} value={m.id}>{m.text}</option>)}
          </select>
        </Field>
      )}
    </FormModal>
  );
}

function ApplyRcmModal({ positionId, onClose, onDone }) {
  const [studies, setStudies] = useState(null);
  const [studyId, setStudyId] = useState("");
  useEffect(() => {
    listRcmStudies().then((d) => setStudies(d.studies || [])).catch(() => setStudies([]));
  }, []);
  return (
    <FormModal title="Apply an RCM study" submitLabel="Apply" canSubmit={!!studyId} onClose={onClose}
               onSubmit={async () => onDone(await applyRcmToPosition(positionId, studyId))}>
      <p className="lib-date">Adds the study's failure modes and scheduled tasks here. Applying it again picks up changes.</p>
      <Field label="RCM study">
        <select value={studyId} onChange={(e) => setStudyId(e.target.value)}>
          <option value="">{studies === null ? "Loading…" : "Choose a study"}</option>
          {(studies || []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}

function NewWorkOrderModal({ positionId, onClose, onDone }) {
  const [title, setTitle] = useState("");
  const [type, setType] = useState("corrective");
  const [due, setDue] = useState("");
  return (
    <FormModal title="New work order" submitLabel="Open work order" canSubmit={!!title.trim()} onClose={onClose}
               onSubmit={async () => onDone(await openWorkOrder({ position_id: positionId, title, type, due: due || null }))}>
      <Field label="What needs doing"><input autoFocus value={title} placeholder="e.g. No hot water" onChange={(e) => setTitle(e.target.value)} /></Field>
      <Field label="Type">
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="corrective">Corrective (something's wrong)</option>
          <option value="preventive">Preventive</option>
          <option value="inspection">Inspection</option>
          <option value="other">Other</option>
        </select>
      </Field>
      <Field label="Due (optional)"><input type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
    </FormModal>
  );
}

function LastDoneModal({ task, onClose, onDone }) {
  const [on, setOn] = useState(task.last_done || today());
  return (
    <FormModal title={`Last done: ${task.name}`} submitLabel="Save" onClose={onClose}
               onSubmit={async () => onDone(await setTaskLastDone(task.id, on))}>
      <p className="lib-date">When this was last done, so the next due date counts from then.</p>
      <Field label="Last done on"><input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
    </FormModal>
  );
}

function EditPositionModal({ p, onClose, onDone }) {
  const [f, setF] = useState({ name: p.name, tag: p.tag || "", position_class: p.position_class || "", description: p.description || "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title="Edit position" submitLabel="Save" canSubmit={!!f.name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenancePosition(p.id, f))}>
      <Field label="Name"><input value={f.name} onChange={set("name")} /></Field>
      <Field label="Tag"><input value={f.tag} onChange={set("tag")} /></Field>
      <Field label="Class (to compare like positions)"><input value={f.position_class} onChange={set("position_class")} /></Field>
      <Field label="Description"><input value={f.description} onChange={set("description")} /></Field>
    </FormModal>
  );
}

function TaskModal({ task, onClose, onDone }) {
  const [name, setName] = useState(task.name);
  const [interval, setInterval] = useState(String(task.interval));
  const [unit, setUnit] = useState(task.unit);
  const [also, setAlso] = useState(task.also_interval ? String(task.also_interval) : "");
  const [alsoUnit, setAlsoUnit] = useState(task.also_unit || "months");
  const [busy, setBusy] = useState(false);
  const UNITS = ["days", "weeks", "months", "years", "hours", "cycles", "km", "starts"];
  return (
    <FormModal title="Edit task" submitLabel="Save" canSubmit={!!name.trim() && Number(interval) > 0} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenanceTask(task.id, {
                 name, interval: Number(interval), unit, also_interval: also ? Number(also) : 0, also_unit: alsoUnit,
               }))}>
      <Field label="Task"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Every">
        <div className="maint-row" style={{ marginTop: 0 }}>
          <input type="number" min="0" step="any" value={interval} onChange={(e) => setInterval(e.target.value)} style={{ width: "6rem" }} />
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </Field>
      <Field label="Or every (whichever comes first, optional)">
        <div className="maint-row" style={{ marginTop: 0 }}>
          <input type="number" min="0" step="any" value={also} placeholder="none" onChange={(e) => setAlso(e.target.value)} style={{ width: "6rem" }} />
          <select value={alsoUnit} onChange={(e) => setAlsoUnit(e.target.value)}>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </Field>
      <button className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); await retireMaintenanceTask(task.id, ""); onDone();
      }}>Retire this task</button>
    </FormModal>
  );
}

function FixModal({ row, onClose, onDone }) {
  const [start, setStart] = useState(row.from);
  const [end, setEnd] = useState(row.to || "");
  const [busy, setBusy] = useState(false);
  return (
    <FormModal title={`Fix: ${row.item}`} submitLabel="Save dates" onClose={onClose}
               onSubmit={async () => onDone(await correctMaintenanceFitment(row.fitment_id, { start, end: row.to ? end : null }))}>
      <Field label="Went in"><input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></Field>
      {row.to && <Field label="Came out"><input type="date" value={end} onChange={(e) => setEnd(e.target.value)} /></Field>}
      <p className="lib-date">Recorded by mistake (wrong item or position)? Strike it out: it leaves the history and the life data.</p>
      <button className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); await voidMaintenanceFitment(row.fitment_id, "recorded by mistake"); onDone();
      }}>Strike it out</button>
    </FormModal>
  );
}

function MeterModal({ positionId, onClose, onDone }) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("hours");
  return (
    <FormModal title="Add a meter" submitLabel="Add" onClose={onClose}
               onSubmit={async () => onDone(await addMaintenanceMeter(positionId, name, unit))}>
      <Field label="Counts"><select value={unit} onChange={(e) => setUnit(e.target.value)}>
        {["hours", "cycles", "km", "starts", "tonnes", "litres"].map((u) => <option key={u} value={u}>{u}</option>)}
      </select></Field>
      <Field label="Name (optional)"><input value={name} placeholder="e.g. Hour meter" onChange={(e) => setName(e.target.value)} /></Field>
    </FormModal>
  );
}

function ReadingModal({ meter, onClose, onDone }) {
  const [value, setValue] = useState("");
  const [on, setOn] = useState(today());
  return (
    <FormModal title={`Reading: ${meter.name}`} submitLabel="Save" canSubmit={value !== ""} onClose={onClose}
               onSubmit={async () => onDone(await recordMaintenanceReading(meter.id, Number(value), on))}>
      <Field label={`Reading (${meter.unit})`}><input type="number" min="0" step="any" autoFocus value={value}
             placeholder={meter.reading != null ? `last: ${meter.reading}` : ""} onChange={(e) => setValue(e.target.value)} /></Field>
      <Field label="Read on"><input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
    </FormModal>
  );
}
