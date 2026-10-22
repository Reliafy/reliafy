import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  addFailureMode,
  addPastFitment,
  applyRcmToPosition,
  fitMaintenanceItem,
  listMaintenanceItems,
  mergeFailureMode,
  updateFailureMode,
  getMaintenanceOverview,
  getMaintenancePosition,
  listMaintenanceLocations,
  listRcmStudies,
  openWorkOrder,
  addMeasurementPoint,
  addItemMeasurementPoint,
  recordMeasurementReading,
  correctMeasurementReading,
  voidMeasurementReading,
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
  updateMaintenancePosition,
  voidMaintenanceFitment,
  addPositionPart,
  listMaintenanceParts,
  removePositionPart,
  updatePositionPart,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import {
  DocumentsCard, FailureModePicker, Field, FormModal, LifeTable, LocationPicker, OUTCOME_LABELS,
  PositionPicker,
  RoughDateField, flatten, fmtDate, fmtDated, roughDate, today,
} from "../components/MaintenanceParts.jsx";
import { failureModeBody, failureModeReady } from "../maintenanceModes.js";
import { roughDateValue } from "../maintenanceFields.js";
import { NewPositionModal } from "./MaintenanceHome.jsx";
import Modal from "../components/Modal.jsx";
import { isStruck, liveReadings, readingClock, readingStatusText, readingWhen } from "../maintenanceReadings.js";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import { PART_ROLES, roleLabel, stockText } from "../maintenanceSpares.js";
import { TasksCard } from "../components/MaintenanceTasks.jsx";
import { ConditionsCard, ConnectionConditions } from "../components/MaintenanceConditions.jsx";
import "./Maintenance.css";
import { DESCRIPTION_HINT, tooLong } from "../maintenanceText.js";

// One position: what's fitted, its failure modes and tasks (from RCM or added
// here), its work orders, and the life data its fitments give.
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

      <section className="card">
        <div className="maint-head">
          <h2>Location</h2>
          <button className="secondary" onClick={() => setModal("location")}>
            {p.location && !p.location.inherited ? "Change" : "Set location"}
          </button>
        </div>
        {p.location ? (
          <p>
            <Link to={`/maintenance/locations/${p.location.id}`}>{p.location.display}</Link>
            {p.location.inherited && p.location.inherited_from && (
              <span className="lib-date">
                {" · "}{p.location.inherited_from.kind === "Item" ? "from " : "inherited from "}
                <Link to={`/maintenance/${p.location.inherited_from.kind === "Item" ? "items" : "positions"}/${p.location.inherited_from.id}`}>
                  {p.location.inherited_from.name}</Link>
                {p.location.inherited_from.kind === "Item" ? ", the item it's inside" : ""}
              </span>
            )}
          </p>
        ) : (
          <p className="lib-date">Not set. Say where this position physically is: the positions inside it, and whatever is
            fitted, are there too unless they say otherwise.</p>
        )}
      </section>

      <ConditionsCard target={{ id: p.id, name: p.name, kind: "Position" }} view={p} onChanged={refresh} />

      {p.fitted?.item && (
        <MaintenancePhotos title={`Photos of the ${p.fitted.item.name}`} targetId={p.fitted.item.id} targetKind="Item"
                           targetName={p.fitted.item.name} photos={p.item_photos} onChanged={refresh}
                           related={[{ id: p.id, kind: "Position", name: p.name },
                             p.location && { ...p.location, kind: "Location" }]} />
      )}
      <MaintenancePhotos title={p.fitted?.item ? `Photos of the ${p.name} position` : "Photos"} targetId={p.id} targetKind="Position"
                         targetName={p.name} photos={p.photos} onChanged={refresh}
                         related={[p.location && { ...p.location, kind: "Location" },
                           p.fitted?.item && { ...p.fitted.item, kind: "Item" }]} />
      <DocumentsCard documents={p.documents} target={{ target_id: p.id }} onChanged={refresh}
                     title={p.fitted?.item ? `Documents for the ${p.name} position` : "Documents"} />
      {p.coordinates && (
        <p className="lib-date">
          Location: {p.coordinates.lat}, {p.coordinates.lon}
          {p.coordinates.source === "photo" ? " (from a photo)" : ""}
        </p>
      )}

      <PartsListCard p={p} onChanged={refresh} />

      <TasksCard subject={{ kind: "position", id: p.id, name: p.name }} tasks={p.tasks} itemTasks={p.item_tasks || []}
                 modes={p.failure_modes} counters={p.measurements.filter((mp) => mp.kind === "counter")}
                 onChanged={refresh}
                 emptyText="No scheduled tasks. Add one (from the maker's manual, a regulation or your own practice), or apply an RCM study whose decisions have intervals." />

      <MeasurementsCard measurements={p.measurements} target={{ kind: "position", id: p.id }} onChanged={refresh} />

      <ConnectionsCard p={p} onChanged={refresh} />

      <section className="card">
        <div className="maint-head"><h2>Work orders</h2></div>
        {p.work_orders.length === 0 ? (
          <p className="lib-date">None yet.</p>
        ) : (
          <div className="maint-scroll"><table className="lib-table">
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
          </table></div>
        )}
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Failure modes</h2>
          <button className="secondary" onClick={() => setModal({ mode: {} })}><PlusIcon /> Add failure mode</button>
        </div>
        {p.failure_modes.length === 0 ? (
          <p className="lib-date">None yet. They come from an RCM study, are added here, or are recorded when
            something fails.</p>
        ) : (
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Failure mode</th><th>Functional failure</th><th>Consequence</th><th>Decision</th><th><span className="sr-only">Edit</span></th></tr></thead>
            <tbody>
              {p.failure_modes.map((m) => (
                <tr key={m.id}>
                  <td>{m.text}{m.ad_hoc && <> <span className="maint-badge" title="Recorded at a failure: confirm it or merge it into another">ad hoc</span></>}</td>
                  <td className="lib-date">{m.failure || "—"}</td>
                  <td className="lib-date">{m.consequence || "—"}</td>
                  <td className="lib-date">{OUTCOME_LABELS[m.outcome] || "—"}</td>
                  <td>{!m.from_rcm && <button className="crumb-link" onClick={() => setModal({ mode: m })}>Edit</button>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Life data</h2>
          <div className="maint-row" style={{ marginTop: 0 }}>
            <span className="lib-date">one row per item fitted here</span>
            <button className="secondary" onClick={() => setModal("past")}>Add past fitment</button>
          </div>
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

      {modal === "location" && <LocationModal p={p} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "edit" && <EditPositionModal p={p} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "retire" && (
        <FormModal title={`Retire ${p.name}`} submitLabel="Retire" onClose={() => setModal(null)}
                   onSubmit={async () => { await retireMaintenancePosition(p.id, ""); navigate("/maintenance"); }}>
          <p>It leaves the plant tree and stops scheduling tasks. Its history stays. Nothing may be fitted,
            nothing inside it in use, and no work order open.</p>
        </FormModal>
      )}
      {modal?.mode && <FailureModeModal p={p} mode={modal.mode} onClose={() => setModal(null)}
                                        onDone={() => { setModal(null); refresh(); }} />}
      {modal === "past" && <PastFitmentModal p={p} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal?.fix && <FixModal row={modal.fix} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
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
  const [mode, setMode] = useState(null);
  const onText = roughDateValue(on.text, on.precision);
  return (
    <FormModal title={`Remove ${position.fitted.item?.name || "the item"}`} submitLabel="Remove" onClose={onClose}
               canSubmit={!!onText && (reason !== "failure" || failureModeReady(mode))}
               onSubmit={async () => onDone(await removeMaintenanceItem(position.id, {
                 on: onText, to_precision: on.precision, reason, ...(reason === "failure" ? failureModeBody(mode) : {}),
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
      {reason === "failure" && (
        <Field label="How it failed">
          <FailureModePicker modes={position.failure_modes} classModes={position.class_failure_modes}
                             value={mode} onChange={setMode} />
        </Field>
      )}
    </FormModal>
  );
}

// Add a failure mode, or edit one added here or recorded at a failure (and
// merge it into another).
function FailureModeModal({ p, mode, onClose, onDone }) {
  const adding = !mode.id;
  const [f, setF] = useState({ text: mode.text || "", failure: mode.failure || "", consequence: mode.consequence || "" });
  const [into, setInto] = useState("");
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const others = p.failure_modes.filter((m) => m.id !== mode.id);
  return (
    <FormModal title={adding ? "Add a failure mode" : `Failure mode: ${mode.text}`}
               submitLabel={into ? "Merge" : adding ? "Add" : mode.ad_hoc ? "Confirm" : "Save"}
               canSubmit={!!f.text.trim()} onClose={onClose}
               onSubmit={async () => onDone(into ? await mergeFailureMode(mode.id, into)
                 : adding ? await addFailureMode(p.id, f) : await updateFailureMode(mode.id, f))}>
      {mode.ad_hoc && <p className="lib-date">Recorded when something failed. Confirm it (edit the words if
        you like), or merge it into the failure mode it really is.</p>}
      <Field label="How it fails"><input autoFocus value={f.text} placeholder="e.g. Bearing worn" onChange={set("text")} disabled={!!into} /></Field>
      <Field label="Functional failure (optional)"><input value={f.failure} placeholder="e.g. No flow" onChange={set("failure")} disabled={!!into} /></Field>
      <Field label="Consequence (optional)"><input value={f.consequence} placeholder="e.g. operational" onChange={set("consequence")} disabled={!!into} /></Field>
      {!adding && others.length > 0 && (
        <Field label="Or merge it into (its failures and tasks move across)">
          <select value={into} onChange={(e) => setInto(e.target.value)}>
            <option value="">Don't merge</option>
            {others.map((m) => <option key={m.id} value={m.id}>{m.text}</option>)}
          </select>
        </Field>
      )}
    </FormModal>
  );
}

// An earlier item into the history: in and out, with why it came out.
function PastFitmentModal({ p, onClose, onDone }) {
  const [items, setItems] = useState(null);
  const [f, setF] = useState({ item_id: "", name: "", serial: "", reason: "planned" });
  const [start, setStart] = useState(roughDate(""));
  const [end, setEnd] = useState(roughDate(""));
  const [mode, setMode] = useState(null);
  const startText = roughDateValue(start.text, start.precision);
  const endText = roughDateValue(end.text, end.precision);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  useEffect(() => {
    listMaintenanceItems().then((d) => setItems(d.items || [])).catch(() => setItems([]));
  }, []);
  const ready = (f.item_id || f.name.trim()) && startText && endText && (f.reason !== "failure" || failureModeReady(mode));
  return (
    <FormModal title="Add a past fitment" submitLabel="Add" canSubmit={!!ready} onClose={onClose}
               onSubmit={async () => onDone(await addPastFitment(p.id, {
                 start: startText, end: endText, from_precision: start.precision, to_precision: end.precision,
                 reason: f.reason, item_id: f.item_id || null,
                 new_item: f.item_id ? null : { name: f.name, serial: f.serial },
                 ...(f.reason === "failure" ? failureModeBody(mode) : {}),
               }))}>
      <p className="lib-date">An item that was here before (from old records). It must not overlap another
        fitment here; what's fitted now and the tasks stay as they are.</p>
      {items?.length > 0 && (
        <Field label="Item">
          <select value={f.item_id} onChange={set("item_id")}>
            <option value="">A new item (below)</option>
            {items.map((i) => <option key={i.id} value={i.id}>{i.name}{i.serial ? ` (${i.serial})` : ""}</option>)}
          </select>
        </Field>
      )}
      {!f.item_id && <>
        <Field label="New item"><input value={f.name} placeholder="e.g. Astral CTX 280" onChange={set("name")} /></Field>
        <Field label="Serial (optional)"><input value={f.serial} onChange={set("serial")} /></Field>
      </>}
      <RoughDateField label="Went in" value={start} max={today()} onChange={setStart} />
      <RoughDateField label="Came out" value={end} max={today()} onChange={setEnd} />
      <Field label="Why it came out">
        <select value={f.reason} onChange={set("reason")}>
          <option value="planned">Planned (still working)</option>
          <option value="failure">It failed</option>
          <option value="other">Other</option>
        </select>
      </Field>
      {f.reason === "failure" && (
        <Field label="How it failed">
          <FailureModePicker modes={p.failure_modes} classModes={p.class_failure_modes} value={mode} onChange={setMode} />
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
    <FormModal title="New work order" submitLabel="Open work order" canSubmit={!!title.trim() && !tooLong(title)} onClose={onClose}
               onSubmit={async () => onDone(await openWorkOrder({ position_id: positionId, title, type, due: due || null }))}>
      <Field label="What needs doing" text={title} hint="add the detail to the notes once it's open"><input autoFocus value={title} placeholder="e.g. No hot water" onChange={(e) => setTitle(e.target.value)} /></Field>
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

// Where a position physically is: set here, or (not set) the same as the position above it.
function LocationModal({ p, onClose, onDone }) {
  const [locations, setLocations] = useState(null);
  const own = p.location && !p.location.inherited ? p.location.id : "";
  const [to, setTo] = useState(own);
  useEffect(() => {
    listMaintenanceLocations().then((d) => setLocations(d.locations || [])).catch(() => setLocations([]));
  }, []);
  const above = p.path.length > 0;
  return (
    <FormModal title={`Where is ${p.name}?`} submitLabel="Save" canSubmit={to !== own} onClose={onClose}
               onSubmit={async () => { await updateMaintenancePosition(p.id, { location_id: to || null }); onDone(); }}>
      <p className="lib-date">
        The physical place: a site, area, room or substation. Positions inside it, and the items fitted, are there too
        unless they say otherwise.
      </p>
      <Field label="Location">
        <LocationPicker locations={locations} value={to} onChange={(v) => setTo(v || "")}
                        emptyLabel={above ? "Not set here (where the position above it is)" : "Not set"} />
      </Field>
      {locations?.length === 0 && <p className="lib-date">No locations yet: add them under Locations.</p>}
    </FormModal>
  );
}

function EditPositionModal({ p, onClose, onDone }) {
  const [f, setF] = useState({ name: p.name, tag: p.tag || "", position_class: p.position_class || "", description: p.description || "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title="Edit position" submitLabel="Save" canSubmit={!!f.name.trim() && !tooLong(f.name)} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenancePosition(p.id, f))}>
      <Field label="Name" text={f.name} hint={DESCRIPTION_HINT}><input value={f.name} onChange={set("name")} /></Field>
      <Field label="Tag"><input value={f.tag} onChange={set("tag")} /></Field>
      <Field label="Class (to compare like positions)"><input value={f.position_class} onChange={set("position_class")} /></Field>
      <Field label="Description"><input value={f.description} onChange={set("description")} /></Field>
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
// The position's parts list (its bill of materials): the part that replaces
// what's fitted, and the components and consumables its maintenance uses, each
// with the stock on hand, what to use if it's been superseded, and alternatives.
function PartsListCard({ p, onChanged }) {
  const [modal, setModal] = useState(null); // {} to add, or the entry to change
  const [error, setError] = useState(null);
  const list = p.parts_list || [];
  const remove = async (entry) => {
    setError(null);
    try { await removePositionPart(entry.id); onChanged(); } catch (e) { setError(e.message); }
  };
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Parts</h2>
        <button className="secondary" onClick={() => setModal({})}><PlusIcon /> Add part</button>
      </div>
      {error && <div className="card error">{error}</div>}
      {list.length === 0 ? (
        <p className="lib-date">No parts listed. Add the part that replaces what's fitted, and the kits and
          consumables its maintenance uses, from the <Link to="/maintenance/parts">parts catalogue</Link>.</p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Part</th><th>Role</th><th>Per job</th><th>Stock</th><th>Compatibility notes</th><th><span className="sr-only">Change</span></th></tr></thead>
          <tbody>
            {list.map((e) => (
              <tr key={e.id}>
                <td>{e.part.part_number}: {e.part.name}
                  {e.use_instead && <div className="lib-date"><strong>Superseded: use {e.use_instead.part_number}</strong>
                    {` · ${stockText(e.use_instead)}`}</div>}
                  {e.alternatives.length > 0 && (
                    <div className="lib-date">Alternatives: {e.alternatives.map((a) => `${a.part_number}: ${stockText(a)}`).join("; ")}</div>
                  )}
                </td>
                <td>{roleLabel(e.role)}{e.critical && <div><span className="maint-badge">critical spare</span></div>}</td>
                <td>{e.quantity}</td>
                <td className="lib-date">{stockText(e.part)}
                  {e.critical && <div className={e.short ? "maint-overdue" : "lib-date"}>
                    keep {e.min_on_hand}; {e.usable_on_hand} usable{e.short ? " (short)" : ""}</div>}</td>
                <td className="lib-date" style={{ whiteSpace: "pre-wrap" }}>{e.notes || "—"}</td>
                <td>
                  <button className="crumb-link" onClick={() => setModal(e)}>Edit</button>{" "}
                  <button className="crumb-link" onClick={() => remove(e)}>remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
      {modal && <PartEntryModal p={p} entry={modal.id ? modal : null} onClose={() => setModal(null)}
                                onDone={() => { setModal(null); onChanged(); }} />}
    </section>
  );
}

function PartEntryModal({ p, entry, onClose, onDone }) {
  const [catalogue, setCatalogue] = useState(null);
  const [f, setF] = useState({
    part_id: "", role: entry?.role || (p.parts_list?.some((x) => x.role === "replacement") ? "component" : "replacement"),
    quantity: entry?.quantity ?? 1, critical: !!entry?.critical, min: entry?.min_on_hand ?? "", notes: entry?.notes || "",
  });
  useEffect(() => {
    if (!entry) listMaintenanceParts().then((d) => setCatalogue(d.parts)).catch(() => setCatalogue([]));
  }, [entry]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const listed = new Set((p.parts_list || []).map((x) => x.part.id));
  const body = {
    role: f.role, quantity: Number(f.quantity), critical: f.critical, notes: f.notes,
    ...(f.critical ? { min_on_hand: f.min === "" ? null : Number(f.min) } : {}),
  };
  return (
    <FormModal title={entry ? `${entry.part.part_number} on ${p.name}` : `Add a part to ${p.name}`}
               submitLabel={entry ? "Save" : "Add"} onClose={onClose}
               canSubmit={!!(entry || f.part_id) && Number(f.quantity) > 0}
               onSubmit={async () => onDone(entry ? await updatePositionPart(entry.id, body)
                 : await addPositionPart(p.id, { ...body, part_id: f.part_id }))}>
      {!entry && (
        <Field label="Part">
          {catalogue === null ? <span className="lib-date">Loading…</span> : catalogue.length === 0 ? (
            <span className="lib-date">The catalogue is empty: add parts on the <Link to="/maintenance/parts">Parts</Link> page first.</span>
          ) : (
            <select autoFocus value={f.part_id} onChange={set("part_id")}>
              <option value="">Choose…</option>
              {catalogue.filter((pt) => !listed.has(pt.id)).map((pt) => (
                <option key={pt.id} value={pt.id}>{pt.part_number}: {pt.name}{pt.superseded_by ? " (superseded)" : ""}</option>
              ))}
            </select>
          )}
        </Field>
      )}
      <Field label="Role">
        <select value={f.role} onChange={set("role")}>
          {PART_ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
        </select>
      </Field>
      <Field label="Quantity per job"><input type="number" inputMode="decimal" min="0" step="any" value={f.quantity}
             onChange={set("quantity")} /></Field>
      <label className="maint-row" style={{ gap: "0.5rem" }}>
        <input type="checkbox" checked={f.critical} onChange={(e) => setF({ ...f, critical: e.target.checked })} />
        Critical spare: keep some in stock
      </label>
      {f.critical && (
        <Field label="Keep at least (blank: one job's worth)"><input type="number" inputMode="decimal" min="0" step="any"
               value={f.min} onChange={set("min")} /></Field>
      )}
      <Field label="Compatibility notes (optional)"><textarea rows={2} value={f.notes}
             placeholder="e.g. needs the matching button kit; fits from serial 4000 on" onChange={set("notes")} /></Field>
      <p className="lib-date">What supersedes a part, and the parts interchangeable with it, come from the catalogue.</p>
    </FormModal>
  );
}

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
              <ConnectionConditions connection={c} name={`${c.from.name} → ${p.name}`} onChanged={onChanged} />{" "}
              <button className="crumb-link" onClick={() => act(() => disconnectPositions(c.id))}>remove</button></li>
          ))}
          {downstream.map((c) => (
            <li key={c.id}>To <Link to={`/maintenance/positions/${c.to.id}`}>{c.to.name}</Link>
              <span className="lib-date"> · {c.kind}{c.medium ? `, ${c.medium}` : ""}</span>{" "}
              <ConnectionConditions connection={c} name={`${p.name} → ${c.to.name}`} onChanged={onChanged} />{" "}
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
      <p className="lib-date">The positions inside {p.name} become blocks, wired by their connections, with redundancy groups as k of n. Blocks take their class's fitted non-repairable model.</p>
      {result?.notes?.length > 0 && <ul className="maint-list">{result.notes.map((n, i) => <li key={i} className="lib-date">{n}</li>)}</ul>}
    </section>
  );
}

// A small chart of a point's readings, with its alarm limits.
function Sparkline({ point }) {
  const rs = liveReadings(point.readings).reverse();
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
// What's measured on a position or an item (target: {kind, id}), with its latest
// readings: counters for tasks by use, condition with alarm limits.
export function MeasurementsCard({ measurements, target, onChanged }) {
  const [modal, setModal] = useState(null);
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Measurements</h2>
        <button className="secondary" onClick={() => setModal("add")}>Add a measurement</button>
      </div>
      {measurements.length === 0 ? (
        <p className="lib-date">
          Nothing measured. Add a counter (run hours, cycles) for tasks that go by use, or a condition
          measurement (vibration, temperature) with alarm limits. Either can be read by hand or fed
          automatically (Home Assistant, a PLC) through the ingest API.
        </p>
      ) : (
        <div className="maint-scroll">
        <table className="lib-table">
          <thead><tr><th>Measurement</th><th>Latest</th><th>Trend</th><th>Rate or alarm</th><th /></tr></thead>
          <tbody>
            {measurements.map((c) => (
              <tr key={c.id}>
                <td>{c.name}
                  <div className="lib-date">{c.kind === "counter" ? "counts use" : "condition"} · {c.source === "automated" ? `feed: ${c.tag}` : "read by hand"}</div></td>
                <td>{c.reading != null ? `${c.reading} ${c.unit}` : "—"}
                  {c.status !== "ok" && <span className="maint-overdue"> {c.status}</span>}
                  <div className="lib-date">{c.read_at ? readingWhen({ when: c.read_when, precision: c.read_precision, at: c.read_at }, fmtDate) : ""}</div></td>
                <td><Sparkline point={c} /></td>
                <td className="lib-date">
                  {c.kind === "counter"
                    ? (c.rate_per_day != null ? `${c.rate_per_day} ${c.unit} a day` : "needs two readings")
                    : <>
                      {[c.alarm_above != null && `above ${c.alarm_above}`, c.alarm_below != null && `below ${c.alarm_below}`].filter(Boolean).join(", ") || "no limits"}
                      {c.projected_alarm && <div>reaches it about {fmtDate(c.projected_alarm)}</div>}
                      {c.alarm_work_order && <div><Link to={`/maintenance/work-orders/${c.alarm_work_order.id}`}>#{c.alarm_work_order.number} open</Link></div>}
                    </>}
                </td>
                <td>{c.source === "manual" && (
                  <div className="maint-row" style={{ marginTop: 0 }}>
                    <button className="secondary" onClick={() => setModal({ read: c })}>Record</button>
                    {c.readings.length > 0 && <button className="secondary" onClick={() => setModal({ list: c })}>Readings</button>}
                  </div>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {modal === "add" && <PointModal target={target} onClose={() => setModal(null)} onDone={() => { setModal(null); onChanged(); }} />}
      {modal?.read && <PointReadingModal point={modal.read} onClose={() => setModal(null)} onDone={() => { setModal(null); onChanged(); }} />}
      {modal?.list && <ReadingsModal point={modal.list} onClose={() => { setModal(null); onChanged(); }} />}
    </section>
  );
}

function PointModal({ target, onClose, onDone }) {
  const [f, setF] = useState({ name: "", kind: "condition", unit: "", source: "manual", tag: "", alarm_above: "", alarm_below: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const counter = f.kind === "counter";
  return (
    <FormModal title="Add a measurement" submitLabel="Add" canSubmit={(counter ? !!f.unit : !!f.name.trim()) && !tooLong(f.name) && (f.source === "manual" || !!f.tag.trim())}
               onClose={onClose} onSubmit={async () => onDone(await (target.kind === "item" ? addItemMeasurementPoint : addMeasurementPoint)(target.id, {
                 ...f, alarm_above: counter ? null : f.alarm_above, alarm_below: counter ? null : f.alarm_below,
               }))}>
      <Field label="What it is">
        <select value={f.kind} onChange={set("kind")}>
          <option value="condition">Condition (vibration, temperature, wear)</option>
          <option value="counter">Counts use (run hours, cycles, km)</option>
        </select>
      </Field>
      <Field label="Name" text={f.name}><input value={f.name} placeholder={counter ? "e.g. Hour meter" : "e.g. Vibration"} onChange={set("name")} /></Field>
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
  // The time of day it was read, now by default: clear it when it isn't known.
  const [time, setTime] = useState(() => new Date().toTimeString().slice(0, 5));
  return (
    <FormModal title={`Reading: ${point.name}`} submitLabel="Save" canSubmit={value !== ""} onClose={onClose}
               onSubmit={async () => onDone(await recordMeasurementReading(point.id, Number(value), on, time ? `${on}T${time}` : undefined))}>
      <Field label={`Reading${point.unit ? ` (${point.unit})` : ""}`}><input type="number" step="any" autoFocus value={value}
             placeholder={point.reading != null ? `last: ${point.reading}` : ""} onChange={(e) => setValue(e.target.value)} /></Field>
      <Field label="Read on"><input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
      <Field label="At (clear it if not known)"><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
    </FormModal>
  );
}

// A manual point's readings, newest first, with the ones struck out or corrected
// marked. A reading entered by mistake is voided; a wrong value or date is
// corrected (the original is kept, struck out). Both need a reason.
function ReadingsModal({ point: initial, onClose }) {
  const [point, setPoint] = useState(initial);
  const [edit, setEdit] = useState(null); // { id, mode: "void" | "correct", value, on, reason }
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const unit = point.unit ? ` ${point.unit}` : "";
  const start = (r, mode) => {
    setError(null);
    setEdit({ id: r.id, mode, value: String(r.value), on: r.on || r.at.slice(0, 10), time: readingClock(r), reason: "" });
  };
  const save = async () => {
    setBusy(true); setError(null);
    try {
      setPoint(edit.mode === "void"
        ? await voidMeasurementReading(edit.id, edit.reason)
        : await correctMeasurementReading(edit.id, { value: Number(edit.value), on: edit.on,
          at: edit.time ? `${edit.on}T${edit.time}` : undefined, reason: edit.reason }));
      setEdit(null);
    } catch (e) { setError(e.message); }
    setBusy(false);
  };
  const set = (k) => (e) => setEdit({ ...edit, [k]: e.target.value });
  return (
    <Modal title={`Readings: ${point.name}`} onClose={onClose} locked={busy}
           footer={<button className="secondary" onClick={onClose} disabled={busy}>Done</button>}>
      {error && <div className="card error">{error}</div>}
      <p className="lib-date">The latest {point.readings.length}. Struck-out readings stay here, marked; rates, due dates
        and alarms leave them out.</p>
      <div className="maint-scroll">
        <table className="lib-table">
          <thead><tr><th>Read on</th><th>Value</th><th>What happened</th><th /></tr></thead>
          <tbody>
            {point.readings.map((r) => (
              <tr key={r.id}>
                <td className={isStruck(r) ? "maint-reading-struck" : ""}>{readingWhen(r, fmtDate)}</td>
                <td className={isStruck(r) ? "maint-reading-struck" : ""}>{r.value}{unit}</td>
                <td className="lib-date">{readingStatusText(r, fmtDate) || r.note || ""}</td>
                <td>{!isStruck(r) && (
                  <div className="maint-row" style={{ marginTop: 0 }}>
                    <button className="crumb-link" onClick={() => start(r, "correct")}>Correct</button>
                    <button className="crumb-link" onClick={() => start(r, "void")}>Void</button>
                  </div>
                )}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {edit && (
        <div className="maint-action">
          <div className="rcm-form">
            {edit.mode === "correct" && <>
              <Field label={`Right value${unit ? ` (${point.unit})` : ""}`}>
                <input type="number" inputMode="decimal" step="any" value={edit.value} onChange={set("value")} />
              </Field>
              <Field label="Really read on"><input type="date" value={edit.on} max={today()} onChange={set("on")} /></Field>
              <Field label="At (optional)"><input type="time" value={edit.time} onChange={set("time")} /></Field>
            </>}
            <Field label={edit.mode === "void" ? "Why it's struck out" : "Why it's corrected"}>
              <input autoFocus value={edit.reason} placeholder={edit.mode === "void" ? "e.g. entered twice" : "e.g. an old reading entered as today"}
                     onChange={set("reason")} />
            </Field>
          </div>
          <div className="maint-row">
            <button onClick={save} disabled={busy || !edit.reason.trim() || (edit.mode === "correct" && edit.value === "")}>
              {busy ? "Saving…" : edit.mode === "void" ? "Void the reading" : "Save the correction"}
            </button>
            <button className="secondary" onClick={() => setEdit(null)} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </Modal>
  );
}
