import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import LoadFailed from "../components/LoadFailed.jsx";
import {
  addFailureMode,
  addPastFitment,
  fitMaintenanceItem,
  listMaintenanceItems,
  mergeFailureMode,
  updateFailureMode,
  getMaintenanceOverview,
  getMaintenancePosition,
  listMaintenanceLocations,
  addMeasurementPoint,
  addItemMeasurementPoint,
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
  updateMaintenancePosition,
  voidMaintenanceFitment,
  removePositionPart,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import ClampLines from "../components/ui/ClampLines.jsx";
import NewWorkOrderModal from "../components/NewWorkOrderModal.jsx";
import { PlusIcon, RowLink, rowOpen } from "../components/LibRows.jsx";
import {
  DocumentsCard, FailureModePicker, Field, FormModal, LifeTable, LocationPicker, OUTCOME_LABELS,
  PositionPicker,
  RoughDateField, flatten, fmtDate, fmtDated, roughDate, today,
} from "../components/MaintenanceParts.jsx";
import { failureModeBody, failureModeReady } from "../maintenanceModes.js";
import { roughDateValue } from "../maintenanceFields.js";
import { deviceClockDiffers, workspaceClock, workspaceMoment, workspaceZoneName } from "../workspaceDate.js";
import { NewPositionModal } from "./MaintenanceHome.jsx";
import Modal from "../components/Modal.jsx";
import { liveReadings, readingWhen } from "../maintenanceReadings.js";
import ReadingsTable from "../components/ReadingsTable.jsx";
import { READINGS_INTRO } from "../measuringPoint.js";
import { pointPagePath } from "../measurementsTab.js";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import { PartEntryModal } from "../components/PartForms.jsx";
import { roleLabel, stockText } from "../maintenanceSpares.js";
import { TasksCard } from "../components/MaintenanceTasks.jsx";
import { ConditionsCard, ConnectionConditions } from "../components/MaintenanceConditions.jsx";
import "./Maintenance.css";
import { DESCRIPTION_HINT, tooLong } from "../maintenanceText.js";
import { PageTitle } from "../components/usePageTitle.js";
import { productPath } from "../products.js";
import { DeleteTreeModal } from "../components/DeleteTree.jsx";
import { explorerPath } from "../assetTree.js";
import { ASSETS_LIST_PATH } from "../maintenanceAssets.js";
import { partsPath } from "../redirects.js";

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

  if (error && !p) return <div className="app"><LoadFailed header error={error} notFound="Position not found." to="/asset-register" label="See all assets" /></div>;
  if (!p) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <PageTitle name={p?.name} />
      <PageHeader
        crumbs={[{ label: "Assets", to: "/asset-register" }, ...p.path.map((a) => ({
          label: a.name, to: a.kind === "Item" ? `/asset-register/items/${a.id}` : `/asset-register/positions/${a.id}` }))]}
        title={p.name}
        meta={[p.tag, p.position_class].filter(Boolean).join(" · ") || "Position"}
        id={p.id}
        menu={
          <>
            <button className="ovm-item" onClick={() => setModal("edit")}>Edit position</button>
            <button className="ovm-item danger" onClick={() => setModal("delete")}>Delete…</button>
          </>
        }
        actions={
          <>
            {/* Back to the tree, this position picked (its tabs: RCM, Modelling, Failure reports…). */}
            <button className="secondary" onClick={() => navigate(explorerPath("positions", { sel: p.id }))}>Open in the Explorer</button>
            <button className="secondary" onClick={openChild}><PlusIcon /> Position inside</button>
          </>
        }
        primary={<button onClick={() => setModal("wo")}>New work order</button>}
      >
        {/* A long description folds to three lines, with Show all: the actions stay near the top. */}
        {p.description && <ClampLines text={p.description} lines={3} what="the description" className="ph-desc" />}
      </PageHeader>
      {error && <div className="card error">{error}</div>}

      <section className="card">
        <div className="maint-head">
          <h2>Fitted</h2>
          {p.fitted ? (
            <button className="secondary" onClick={() => setModal("remove")}>Remove</button>
          ) : p.in_design ? (
            // A product's design: nothing is fitted here; its items are built from it.
            <Link to={productPath(p.in_design.id, "items")}>The items built from {p.in_design.name}</Link>
          ) : (
            <button onClick={() => setModal("fit")}>Fit an item</button>
          )}
        </div>
        {p.fitted ? (
          <p>
            <strong>{p.fitted.item ? <Link to={`/asset-register/items/${p.fitted.item.id}`}>{p.fitted.item.name}</Link> : "?"}</strong>
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
            <Link to={`/asset-register/locations/${p.location.id}`}>{p.location.display}</Link>
            {p.location.inherited && p.location.inherited_from && (
              <span className="lib-date">
                {" · "}{p.location.inherited_from.kind === "Item" ? "from " : "inherited from "}
                <Link to={`/asset-register/${p.location.inherited_from.kind === "Item" ? "items" : "positions"}/${p.location.inherited_from.id}`}>
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
                 emptyText="No scheduled tasks. Add one (from the maker's manual, a regulation or your own practice), or decide the position's failure modes on the Explorer's RCM tab: a decision with an interval schedules its task." />

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
                <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, `/maintenance/work-orders/${w.id}`)}>
                  <td>{w.number}</td>
                  <td><RowLink to={`/maintenance/work-orders/${w.id}`}>{w.title}</RowLink>{w.under_warranty && <> <span className="maint-badge">warranty</span></>}</td>
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
          <p className="lib-date">None yet. They are added here or on the Explorer's RCM tab, or are recorded when
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
                  <td className="lib-date">{(m.outcomes?.length > 1 ? m.outcomes : [m.outcome]).map((o) => OUTCOME_LABELS[o]).filter(Boolean).join(" + ") || "—"}</td>
                  <td><button className="crumb-link" onClick={() => setModal({ mode: m })}>Edit</button></td>
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
            {p.children.map((c) => <li key={c.id}><Link to={`/asset-register/positions/${c.id}`}>{c.name}</Link></li>)}
          </ul>
        </section>
      )}

      {modal === "location" && <LocationModal p={p} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "edit" && <EditPositionModal p={p} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "delete" && (
        // Gone from the tree with everything inside it: the Explorer shows the toast with Undo.
        <DeleteTreeModal kind="position" id={p.id} name={p.name} onClose={() => setModal(null)}
                         onDone={(answer, done) => navigate(ASSETS_LIST_PATH, { state: { deleted: done } })} />
      )}
      {modal?.mode && <FailureModeModal p={p} mode={modal.mode} onClose={() => setModal(null)}
                                        onDone={() => { setModal(null); refresh(); }} />}
      {modal === "past" && <PastFitmentModal p={p} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal?.fix && <FixModal row={modal.fix} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "fit" && <FitModal positionId={id} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal === "remove" && <RemoveModal position={p} onClose={() => setModal(null)} onDone={(d) => { setP(d); setModal(null); }} />}
      {modal === "wo" && (
        <NewWorkOrderModal positionId={id} onClose={() => setModal(null)}
                           onDone={(wo) => navigate(`/maintenance/work-orders/${wo.id}`)} />
      )}
      {modal === "child" && (
        <NewPositionModal positions={positions} parentId={id} onClose={() => setModal(null)}
                          onCreated={(c) => navigate(`/asset-register/positions/${c.id}`)} />
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

// Where a position physically is: set here, or (not set) the same as the position above it.
function LocationModal({ p, onClose, onDone }) {
  const [locations, setLocations] = useState(null);
  const own = p.location && !p.location.inherited ? p.location.id : "";
  const [to, setTo] = useState(own);
  // A product's design is placed in its own layout only; a built item's positions at
  // the places you look after or the item's own locations.
  const layout = p.layout;
  useEffect(() => {
    const reads = layout?.kind === "design" ? [listMaintenanceLocations(layout.of)]
      : layout?.kind === "unit" ? [listMaintenanceLocations(layout.of), listMaintenanceLocations()] : [listMaintenanceLocations()];
    Promise.all(reads).then((all) => setLocations(all.flatMap((d) => d.locations || []))).catch(() => setLocations([]));
  }, [layout?.kind, layout?.of]);
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
      {locations?.length === 0 && (
        <p className="lib-date">{layout?.kind === "design"
          ? "No locations in the product's layout yet: add them on the product's page, by Locations."
          : "No locations yet: add them under Locations."}</p>
      )}
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
          consumables its maintenance uses, from the <Link to={partsPath()}>parts catalogue</Link>.</p>
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
            <li key={c.id}>From <Link to={`/asset-register/positions/${c.from.id}`}>{c.from.name}</Link>
              <span className="lib-date"> · {c.kind}{c.medium ? `, ${c.medium}` : ""}</span>{" "}
              <ConnectionConditions connection={c} name={`${c.from.name} → ${p.name}`} onChanged={onChanged} />{" "}
              <button className="crumb-link" onClick={() => act(() => disconnectPositions(c.id))}>remove</button></li>
          ))}
          {downstream.map((c) => (
            <li key={c.id}>To <Link to={`/asset-register/positions/${c.to.id}`}>{c.to.name}</Link>
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
          {rbdId && <Link to={`/systems/b/${rbdId}`}>Open the RBD</Link>}
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
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.5" />
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
                  <div className="lib-date">{c.kind === "counter" ? "counts use" : c.kind === "setting" ? "setting" : "condition"} · {c.source === "automated" ? `feed: ${c.tag}` : "read by hand"}</div></td>
                <td>{c.reading != null ? `${c.reading} ${c.unit}` : "—"}
                  {c.status !== "ok" && <span className="maint-overdue"> {c.status}</span>}
                  <div className="lib-date">{c.read_at ? readingWhen({ when: c.read_when, precision: c.read_precision, at: c.read_at }, fmtDate) : ""}</div></td>
                <td><Sparkline point={c} /></td>
                <td className="lib-date">
                  {c.kind === "counter"
                    ? (c.rate_per_day != null ? `${c.rate_per_day} ${c.unit} a day` : "needs two readings")
                    : c.kind === "setting" ? "holds until changed" : <>
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

// `kind`: the kind it starts as ("setting" from Add a setting…).
export function PointModal({ target, kind = "condition", onClose, onDone }) {
  const [f, setF] = useState({ name: "", kind, unit: "", source: "manual", tag: "", alarm_above: "", alarm_below: "",
    range_min: "", range_max: "" });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const counter = f.kind === "counter";
  const setting = f.kind === "setting";
  const blank = (v) => (v === "" ? null : v);
  return (
    <FormModal title={kind === "setting" ? "Add a setting" : "Add a measuring point"} submitLabel="Add" canSubmit={(counter ? !!f.unit : !!f.name.trim()) && !tooLong(f.name) && (f.source === "manual" || !!f.tag.trim())}
               onClose={onClose} onSubmit={async () => onDone(await (target.kind === "item" ? addItemMeasurementPoint : addMeasurementPoint)(target.id, {
                 ...f, alarm_above: f.kind === "condition" ? blank(f.alarm_above) : null,
                 alarm_below: f.kind === "condition" ? blank(f.alarm_below) : null,
                 range_min: setting ? blank(f.range_min) : null, range_max: setting ? blank(f.range_max) : null,
               }))}>
      <Field label="What it is">
        <select value={f.kind} onChange={set("kind")}>
          <option value="condition">Condition (vibration, temperature, wear)</option>
          <option value="counter">Counts use (run hours, cycles, km)</option>
          <option value="setting">Setting (output %, hours a day, a setpoint)</option>
        </select>
      </Field>
      <Field label="Name" text={f.name}><input value={f.name} placeholder={counter ? "e.g. Hour meter" : setting ? "e.g. Chlorinator output" : "e.g. Vibration"} onChange={set("name")} /></Field>
      {counter ? (
        <Field label="Counts"><select value={f.unit} onChange={set("unit")}>
          <option value="">Choose…</option>
          {["hours", "cycles", "km", "starts", "tonnes", "litres"].map((u) => <option key={u} value={u}>{u}</option>)}
        </select></Field>
      ) : setting ? (
        <>
          <p className="lib-date">A value someone sets. It holds until the next change: no alarm, never due. A work order can record each change.</p>
          <Field label="Unit"><input value={f.unit} placeholder="e.g. %, h/day, °C" onChange={set("unit")} /></Field>
          <Field label="Lowest allowed (optional)"><input type="number" step="any" value={f.range_min} onChange={set("range_min")} /></Field>
          <Field label="Highest allowed (optional)"><input type="number" step="any" value={f.range_max} onChange={set("range_max")} /></Field>
        </>
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

export function PointReadingModal({ point, onClose, onDone }) {
  const [value, setValue] = useState("");
  const [on, setOn] = useState(today());
  // The time of day it was read, now by default, on the workspace's clock (as the
  // date is: the device's own clock is hours out when it's in another time zone).
  // Clear it when it isn't known.
  const [time, setTime] = useState(() => workspaceClock());
  const zone = workspaceZoneName();
  const setting = point.kind === "setting";
  return (
    <FormModal title={`${setting ? "New setting" : "Reading"}: ${point.name}`} submitLabel="Save" canSubmit={value !== ""} onClose={onClose}
               onSubmit={async () => onDone(await recordMeasurementReading(point.id, Number(value), on, time ? workspaceMoment(on, time) : undefined))}>
      <Field label={`${setting ? "Set to" : "Reading"}${point.unit ? ` (${point.unit})` : ""}`}><input type="number" step="any" autoFocus value={value}
             placeholder={point.reading != null ? `${setting ? "now" : "last"}: ${point.reading}` : ""} onChange={(e) => setValue(e.target.value)} /></Field>
      <Field label={setting ? "Changed on" : "Read on"}><input type="date" value={on} max={today()} onChange={(e) => setOn(e.target.value)} /></Field>
      <Field label={`At, ${zone} time (clear it if not known)`}><input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
      {deviceClockDiffers() && (
        <p className="lib-date">The date and time are on this workspace&apos;s clock ({zone}), not this device&apos;s.</p>
      )}
    </FormModal>
  );
}

// A manual point's readings, newest first (the table its own page shows too),
// with the ones struck out or corrected marked, and a link to the point's page
// (its chart, limits and trend). A reading entered by mistake is voided; a
// wrong value or date is corrected (the original is kept, struck out). Both
// need a reason.
export function ReadingsModal({ point: initial, onClose }) {
  const [point, setPoint] = useState(initial);
  return (
    <Modal title={`Readings: ${point.name}`} onClose={onClose} className="readings-modal"
           footer={<button className="secondary" onClick={onClose}>Done</button>}>
      <div className="rt-modal-head">
        <p className="lib-date">{READINGS_INTRO}</p>
        <Link className="rt-open-page" to={pointPagePath(point)}>Open the full page</Link>
      </div>
      {point.readings.length
        ? <ReadingsTable point={point} onChanged={setPoint} idPrefix="rdm" />
        : <div className="card empty">No readings yet.</div>}
    </Modal>
  );
}
