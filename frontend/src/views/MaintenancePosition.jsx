import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  applyRcmToPosition,
  fitMaintenanceItem,
  getMaintenanceOverview,
  getMaintenancePosition,
  listRcmStudies,
  openWorkOrder,
  addMeasurementPoint,
  recordMeasurementReading,
  connectPositions,
  createRedundancyGroup,
  disconnectPositions,
  generatePositionRbd,
  getPositionImpact,
  retireRedundancyGroup,
  setGroupDuty,
  correctMaintenanceFitment,
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
  DocumentsCard, DueChip, Field, FormModal, LifeTable, MaintenanceTabs, OUTCOME_LABELS, PositionPicker, RoughDateField,
  everyText, flatten, fmtDate, fmtDated, roughDate, today,
} from "../components/MaintenanceParts.jsx";
import { roughDateValue } from "../maintenanceFields.js";
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
            <span className="lib-date"> · since {fmtDated(p.fitted.from, p.fitted.from_precision)}</span>
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
      <DocumentsCard documents={p.documents} target={{ target_id: p.id }} onChanged={refresh}
                     title={p.fitted?.item ? `Documents for the ${p.name} position` : "Documents"} />
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
                  <td>{t.name}{t.trade && <div className="lib-date">needs: {t.trade}</div>}</td>
                  <td className="lib-date">{everyText(t)}</td>
                  <td className="lib-date">
                    <button type="button" className="crumb-link" title="When was it last done?"
                            onClick={() => setModal({ lastDone: t })}>
                      {t.last_done ? fmtDate(t.last_done) : "set"}
                    </button>
                  </td>
                  <td><DueChip task={t} />{t.proposal && <div><span className="maint-badge">change proposed</span></div>}</td>
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

      <MeasurementsCard p={p} onChanged={refresh} />

      <ConnectionsCard p={p} onChanged={refresh} />

      <section className="card">
        <div className="maint-head"><h2>Work orders</h2></div>
        {p.work_orders.length === 0 ? (
          <p className="lib-date">None yet.</p>
        ) : (
          <table className="lib-table">
            <thead><tr><th>#</th><th>Title</th><th>Type</th><th>Trade</th><th>Status</th><th>Opened</th><th>Closed</th></tr></thead>
            <tbody>
              {p.work_orders.map((w) => (
                <tr key={w.id} className="lib-row" onClick={() => navigate(`/maintenance/work-orders/${w.id}`)}>
                  <td>{w.number}</td>
                  <td>{w.title}{w.under_warranty && <> <span className="maint-badge">warranty</span></>}</td>
                  <td>{w.type}</td><td className="lib-date">{w.trade || "—"}</td><td>{w.status}</td>
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

      {p.children.length > 0 && <RbdCard p={p} onChanged={refresh} />}
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
  const [on, setOn] = useState(roughDate(today()));
  const onText = roughDateValue(on.text, on.precision);
  return (
    <FormModal title="Fit an item" submitLabel="Fit" canSubmit={!!name.trim() && !!onText} onClose={onClose}
               onSubmit={async () => onDone(await fitMaintenanceItem(positionId, {
                 new_item: { name, serial, part_number: partNumber, manufacturer }, on: onText,
                 from_precision: on.precision,
               }))}>
      <Field label="Item"><input autoFocus value={name} placeholder="e.g. Rheem 315 L electric" onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Serial (optional)"><input value={serial} onChange={(e) => setSerial(e.target.value)} /></Field>
      <Field label="Part or model number (optional)"><input value={partNumber} onChange={(e) => setPartNumber(e.target.value)} /></Field>
      <Field label="Manufacturer (optional)"><input value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} /></Field>
      <RoughDateField label="Fitted on" value={on} onChange={setOn} />
      <p className="lib-date">A new item counts as a renewal: this position's tasks count from the day it went in.
        Known only to the year or month? Say so: its life data becomes a range rather than a guessed day.</p>
    </FormModal>
  );
}

function RemoveModal({ position, onClose, onDone }) {
  const [on, setOn] = useState(roughDate(today()));
  const [reason, setReason] = useState("planned");
  const [mode, setMode] = useState("");
  const onText = roughDateValue(on.text, on.precision);
  return (
    <FormModal title={`Remove ${position.fitted.item?.name || "the item"}`} submitLabel="Remove" canSubmit={!!onText}
               onClose={onClose}
               onSubmit={async () => onDone(await removeMaintenanceItem(position.id, {
                 on: onText, to_precision: on.precision, reason, failure_mode_id: reason === "failure" ? mode || null : null,
               }))}>
      <p className="lib-date">For corrections and moves. Work done on it belongs on a work order.</p>
      <RoughDateField label="Removed on" value={on} onChange={setOn} />
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
  const [instructions, setInstructions] = useState(task.instructions || "");
  const [checklist, setChecklist] = useState((task.checklist || []).join("\n"));
  const [trade, setTrade] = useState(task.trade || "");
  const [busy, setBusy] = useState(false);
  const UNITS = ["days", "weeks", "months", "years", "hours", "cycles", "km", "starts"];
  return (
    <FormModal title="Edit task" submitLabel="Save" canSubmit={!!name.trim() && Number(interval) > 0} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenanceTask(task.id, {
                 name, interval: Number(interval), unit, also_interval: also ? Number(also) : 0, also_unit: alsoUnit,
                 instructions, checklist: checklist.split("\n").map((x) => x.trim()).filter(Boolean), trade,
               }))}>
      <Field label="Task"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Every">
        <div className="maint-row" style={{ marginTop: 0 }}>
          <input type="number" inputMode="decimal" min="0" step="any" value={interval} onChange={(e) => setInterval(e.target.value)} style={{ width: "6rem" }} />
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </Field>
      <Field label="Or every (whichever comes first, optional)">
        <div className="maint-row" style={{ marginTop: 0 }}>
          <input type="number" inputMode="decimal" min="0" step="any" value={also} placeholder="none" onChange={(e) => setAlso(e.target.value)} style={{ width: "6rem" }} />
          <select value={alsoUnit} onChange={(e) => setAlsoUnit(e.target.value)}>
            {UNITS.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
      </Field>
      <Field label="Who may do it: trade, licence or competency (optional)"><input value={trade}
             placeholder="e.g. Licensed electrician" onChange={(e) => setTrade(e.target.value)} /></Field>
      <Field label="Instructions (optional)"><textarea rows={3} value={instructions} onChange={(e) => setInstructions(e.target.value)} /></Field>
      <Field label="Checklist, one step per line (optional)"><textarea rows={4} value={checklist}
             placeholder={"Isolate power\nDrain 10 L\nFit the new anode"} onChange={(e) => setChecklist(e.target.value)} /></Field>
      <p className="lib-date">Each work order this task raises gets the trade, the instructions and the checklist to tick off.</p>
      <button className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); await retireMaintenanceTask(task.id, ""); onDone();
      }}>Retire this task</button>
    </FormModal>
  );
}

function FixModal({ row, onClose, onDone }) {
  const [start, setStart] = useState(roughDate(row.from, row.from_precision));
  const [end, setEnd] = useState(roughDate(row.to, row.to_precision));
  const [busy, setBusy] = useState(false);
  const startText = roughDateValue(start.text, start.precision);
  const endText = roughDateValue(end.text, end.precision);
  return (
    <FormModal title={`Fix: ${row.item}`} submitLabel="Save dates" canSubmit={!!startText && (!row.to || !!endText)}
               onClose={onClose}
               onSubmit={async () => onDone(await correctMaintenanceFitment(row.fitment_id, {
                 start: startText, from_precision: start.precision,
                 ...(row.to ? { end: endText, to_precision: end.precision } : {}),
               }))}>
      <RoughDateField label="Went in" value={start} onChange={setStart} />
      {row.to && <RoughDateField label="Came out" value={end} onChange={setEnd} />}
      <p className="lib-date">Recorded by mistake (wrong item or position)? Strike it out: it leaves the history and the life data.</p>
      <button className="secondary" disabled={busy} onClick={async () => {
        setBusy(true); await voidMaintenanceFitment(row.fitment_id, "recorded by mistake"); onDone();
      }}>Strike it out</button>
    </FormModal>
  );
}



// Connections in and out, redundancy groups, and what depends on this position.
function ConnectionsCard({ p, onChanged }) {
  const [modal, setModal] = useState(null);
  const [impact, setImpact] = useState(null);
  const [positions, setPositions] = useState([]);
  const [error, setError] = useState(null);
  const open = (kind) => {
    getMaintenanceOverview().then((d) => setPositions(flatten(d.tree).filter((x) => x.id !== p.id))).catch(() => {});
    setModal(kind);
  };
  const act = async (fn) => {
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError(e.message); }
  };
  const { upstream, downstream } = p.connections;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Connections and redundancy</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          <button className="secondary" onClick={() => getPositionImpact(p.id).then(setImpact).catch((e) => setError(e.message))}>
            What depends on it?
          </button>
          <button className="secondary" onClick={() => open("group")}>Redundancy group</button>
          <button onClick={() => open("connect")}>Connect</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      {upstream.length + downstream.length === 0 ? (
        <p className="lib-date">Not connected. Say what feeds it and what it feeds (water, power, signals): the generated RBD and the impact use it.</p>
      ) : (
        <ul className="maint-list">
          {upstream.map((c) => (
            <li key={c.id}>From <Link to={`/maintenance/positions/${c.from.id}`}>{c.from.name}</Link>
              <span className="lib-date"> · {c.kind}{c.medium ? `, ${c.medium}` : ""}</span>{" "}
              <button className="crumb-link" onClick={() => act(() => disconnectPositions(c.id))}>remove</button></li>
          ))}
          {downstream.map((c) => (
            <li key={c.id}>To <Link to={`/maintenance/positions/${c.to.id}`}>{c.to.name}</Link>
              <span className="lib-date"> · {c.kind}{c.medium ? `, ${c.medium}` : ""}</span>{" "}
              <button className="crumb-link" onClick={() => act(() => disconnectPositions(c.id))}>remove</button></li>
          ))}
        </ul>
      )}
      {p.groups.map((g) => (
        <div key={g.id} className="maint-ask" style={{ marginTop: "0.75rem" }}>
          <p><strong>{g.name}</strong>: {g.k} of {g.n} needed{g.mode === "standby" ? ` (${g.standby} standby)` : ""}.
            {" "}Members: {g.members.map((mm) => mm.name).join(", ")}.
            {g.mode === "standby" && <> On duty: {g.members.find((mm) => mm.id === g.duty)?.name || "not set"}.</>}</p>
          <div className="maint-row" style={{ marginTop: 0 }}>
            {g.mode === "standby" && g.duty !== p.id && (
              <button className="secondary" onClick={() => act(() => setGroupDuty(g.id, p.id))}>Put {p.name} on duty</button>
            )}
            <button className="secondary" onClick={() => act(() => retireRedundancyGroup(g.id))}>Remove the group</button>
          </div>
        </div>
      ))}
      {impact && <p className="lib-date" style={{ marginTop: "0.75rem" }}>{impact.summary}
        {impact.downstream.length > 0 && <> ({impact.downstream.map((d) => d.name).join(", ")})</>}</p>}
      {modal === "connect" && <ConnectModal p={p} positions={positions} onClose={() => setModal(null)}
                                            onDone={() => { setModal(null); onChanged(); }} />}
      {modal === "group" && <GroupModal p={p} positions={positions} onClose={() => setModal(null)}
                                        onDone={() => { setModal(null); onChanged(); }} />}
    </section>
  );
}

function ConnectModal({ p, positions, onClose, onDone }) {
  const [other, setOther] = useState(null);
  const [direction, setDirection] = useState("out");
  const [kind, setKind] = useState("flow");
  const [medium, setMedium] = useState("");
  return (
    <FormModal title={`Connect ${p.name}`} submitLabel="Connect" canSubmit={!!other} onClose={onClose}
               onSubmit={async () => onDone(await connectPositions({
                 from_id: direction === "out" ? p.id : other, to_id: direction === "out" ? other : p.id, kind, medium,
               }))}>
      <Field label="Direction">
        <select value={direction} onChange={(e) => setDirection(e.target.value)}>
          <option value="out">{p.name} feeds…</option>
          <option value="in">{p.name} is fed by…</option>
        </select>
      </Field>
      <Field label="Position"><PositionPicker positions={positions} value={other} onChange={setOther} emptyLabel="Choose…" /></Field>
      <Field label="What passes">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          {["flow", "electrical", "mechanical", "signal", "data", "other"].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </Field>
      <Field label="Medium or rating (optional)"><input value={medium} placeholder="e.g. water, 240 V, 4-20 mA" onChange={(e) => setMedium(e.target.value)} /></Field>
    </FormModal>
  );
}

function GroupModal({ p, positions, onClose, onDone }) {
  const [chosen, setChosen] = useState([]);
  const [k, setK] = useState(1);
  const [mode, setMode] = useState("active");
  const [name, setName] = useState("");
  const n = chosen.length + 1;
  return (
    <FormModal title="Redundancy group" submitLabel="Create" canSubmit={chosen.length >= 1 && k >= 1 && k < n} onClose={onClose}
               onSubmit={async () => onDone(await createRedundancyGroup({ name, member_ids: [p.id, ...chosen], k, mode }))}>
      <p className="lib-date">Positions doing the same job as {p.name}, where only some are needed (two pumps, either will do).</p>
      <div className="login-field">
        <span>With</span>
        {positions.map((x) => (
          <label key={x.id} className="maint-row" style={{ marginTop: 0, gap: "0.4rem" }}>
            <input type="checkbox" checked={chosen.includes(x.id)}
                   onChange={(e) => setChosen(e.target.checked ? [...chosen, x.id] : chosen.filter((c) => c !== x.id))} />
            {"\u00a0\u00a0".repeat(x.depth)}{x.name}
          </label>
        ))}
      </div>
      <Field label={`How many of the ${n} are needed`}><input type="number" inputMode="numeric" min="1" max={Math.max(1, n - 1)} value={k}
             onChange={(e) => setK(Number(e.target.value))} /></Field>
      <Field label="The others">
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="active">run all the time (active)</option>
          <option value="standby">wait to take over (standby)</option>
        </select>
      </Field>
      <Field label="Name (optional)"><input value={name} placeholder="e.g. Pool pumps" onChange={(e) => setName(e.target.value)} /></Field>
    </FormModal>
  );
}

function RbdCard({ p, onChanged }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const make = async () => {
    setBusy(true); setError(null);
    try { setResult(await generatePositionRbd(p.id)); onChanged(); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const rbdId = result?.rbd_id || p.rbd_id;
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Reliability block diagram</h2>
        <div className="maint-row" style={{ marginTop: 0 }}>
          {rbdId && <Link to={`/rbds/b/${rbdId}`}>Open the RBD</Link>}
          <button onClick={make} disabled={busy}>{busy ? "Generating…" : rbdId ? "Regenerate from the plant" : "Generate from the plant"}</button>
        </div>
      </div>
      {error && <div className="card error">{error}</div>}
      <p className="lib-date">The positions inside {p.name} become blocks, wired by their connections, with redundancy groups as k of n. Blocks take their class's fitted life model.</p>
      {result?.notes?.length > 0 && <ul className="maint-list">{result.notes.map((n, i) => <li key={i} className="lib-date">{n}</li>)}</ul>}
    </section>
  );
}

// A small chart of a point's readings, with its alarm limits.
function Sparkline({ point }) {
  const rs = [...point.readings].reverse();
  if (rs.length < 2) return null;
  const W = 160, H = 40;
  const vals = rs.map((r) => r.value).concat([point.alarm_above, point.alarm_below].filter((v) => v != null));
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  const x = (i) => 2 + (i / (rs.length - 1)) * (W - 4);
  const d = rs.map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r.value).toFixed(1)}`).join(" ");
  return (
    <svg width={W} height={H} role="img" aria-label={`${point.name} readings`}>
      {point.alarm_above != null && <line x1="0" x2={W} y1={y(point.alarm_above)} y2={y(point.alarm_above)} stroke="var(--danger)" strokeDasharray="3 3" />}
      {point.alarm_below != null && <line x1="0" x2={W} y1={y(point.alarm_below)} y2={y(point.alarm_below)} stroke="var(--danger)" strokeDasharray="3 3" />}
      <path d={d} fill="none" stroke="var(--acc)" strokeWidth="1.5" />
    </svg>
  );
}




// Measurement points: counters (use: hours, cycles) and condition (vibration,
// temperature), read by hand or fed automatically.
function MeasurementsCard({ p, onChanged }) {
  const [modal, setModal] = useState(null);
  const sparkPoint = (c) => ({ ...c, readings: c.readings.map((r) => ({ ...r, value: r.value })) });
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Measurements</h2>
        <button className="secondary" onClick={() => setModal("add")}>Add a measurement</button>
      </div>
      {p.measurements.length === 0 ? (
        <p className="lib-date">
          Nothing measured. Add a counter (run hours, cycles) for tasks that go by use, or a condition
          measurement (vibration, temperature) with alarm limits. Either can be read by hand or fed
          automatically (Home Assistant, a PLC) through the ingest API.
        </p>
      ) : (
        <table className="lib-table">
          <thead><tr><th>Measurement</th><th>Latest</th><th>Trend</th><th>Rate or alarm</th><th /></tr></thead>
          <tbody>
            {p.measurements.map((c) => (
              <tr key={c.id}>
                <td>{c.name}
                  <div className="lib-date">{c.kind === "counter" ? "counts use" : "condition"} · {c.source === "automated" ? `feed: ${c.tag}` : "read by hand"}</div></td>
                <td>{c.reading != null ? `${c.reading} ${c.unit}` : "—"}
                  {c.status !== "ok" && <span className="maint-overdue"> {c.status}</span>}
                  <div className="lib-date">{c.read_at ? fmtDate(c.read_at.slice(0, 10)) : ""}</div></td>
                <td><Sparkline point={sparkPoint(c)} /></td>
                <td className="lib-date">
                  {c.kind === "counter"
                    ? (c.rate_per_day != null ? `${c.rate_per_day} ${c.unit} a day` : "needs two readings")
                    : <>
                      {[c.alarm_above != null && `above ${c.alarm_above}`, c.alarm_below != null && `below ${c.alarm_below}`].filter(Boolean).join(", ") || "no limits"}
                      {c.projected_alarm && <div>reaches it about {fmtDate(c.projected_alarm)}</div>}
                      {c.alarm_work_order && <div><Link to={`/maintenance/work-orders/${c.alarm_work_order.id}`}>#{c.alarm_work_order.number} open</Link></div>}
                    </>}
                </td>
                <td>{c.source === "manual" && <button className="secondary" onClick={() => setModal({ read: c })}>Record</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {modal === "add" && <PointModal positionId={p.id} onClose={() => setModal(null)} onDone={() => { setModal(null); onChanged(); }} />}
      {modal?.read && <PointReadingModal point={modal.read} onClose={() => setModal(null)} onDone={() => { setModal(null); onChanged(); }} />}
    </section>
  );
}

function PointModal({ positionId, onClose, onDone }) {
  const [f, setF] = useState({ name: "", kind: "condition", unit: "", source: "manual", tag: "", alarm_above: "", alarm_below: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const counter = f.kind === "counter";
  return (
    <FormModal title="Add a measurement" submitLabel="Add" canSubmit={(counter ? !!f.unit : !!f.name.trim()) && (f.source === "manual" || !!f.tag.trim())}
               onClose={onClose} onSubmit={async () => onDone(await addMeasurementPoint(positionId, {
                 ...f, alarm_above: counter ? null : f.alarm_above, alarm_below: counter ? null : f.alarm_below,
               }))}>
      <Field label="What it is">
        <select value={f.kind} onChange={set("kind")}>
          <option value="condition">Condition (vibration, temperature, wear)</option>
          <option value="counter">Counts use (run hours, cycles, km)</option>
        </select>
      </Field>
      <Field label="Name"><input value={f.name} placeholder={counter ? "e.g. Hour meter" : "e.g. Vibration"} onChange={set("name")} /></Field>
      {counter ? (
        <Field label="Counts"><select value={f.unit} onChange={set("unit")}>
          <option value="">Choose…</option>
          {["hours", "cycles", "km", "starts", "tonnes", "litres"].map((u) => <option key={u} value={u}>{u}</option>)}
        </select></Field>
      ) : (
        <>
          <Field label="Unit"><input value={f.unit} placeholder="e.g. mm/s, °C" onChange={set("unit")} /></Field>
          <Field label="Alarm above (optional)"><input type="number" step="any" value={f.alarm_above} onChange={set("alarm_above")} /></Field>
          <Field label="Alarm below (optional)"><input type="number" step="any" value={f.alarm_below} onChange={set("alarm_below")} /></Field>
        </>
      )}
      <Field label="Readings come from">
        <select value={f.source} onChange={set("source")}>
          <option value="manual">Someone reads it</option>
          <option value="automated">A feed (Home Assistant, a PLC, a historian)</option>
        </select>
      </Field>
      {f.source === "automated" && (
        <Field label="Tag the feed sends"><input value={f.tag} placeholder="e.g. sensor.pool_pump_hours" onChange={set("tag")} /></Field>
      )}
      {f.source === "automated" && (
        <p className="lib-date">The feed posts readings to /api/ingest/maintenance/readings with an API token that has the ingest scope (Settings → API access).</p>
      )}
    </FormModal>
  );
}

function PointReadingModal({ point, onClose, onDone }) {
  const [value, setValue] = useState("");
  const [on, setOn] = useState(today());
  return (
    <FormModal title={`Reading: ${point.name}`} submitLabel="Save" canSubmit={value !== ""} onClose={onClose}
               onSubmit={async () => onDone(await recordMeasurementReading(point.id, Number(value), on))}>
      <Field label={`Reading${point.unit ? ` (${point.unit})` : ""}`}><input type="number" step="any" autoFocus value={value}
             placeholder={point.reading != null ? `last: ${point.reading}` : ""} onChange={(e) => setValue(e.target.value)} /></Field>
      <Field label="Read on"><input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
    </FormModal>
  );
}
