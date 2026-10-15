import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createMaintenancePosition,
  getMaintenanceItem,
  getMaintenanceOverview,
  listMaintenanceLocations,
  moveMaintenanceItem,
  placeMaintenanceItem,
  updateMaintenanceItem,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import {
  DocumentsCard, Field, FormModal, LocationPicker, MaintenanceTabs, NotesCard, PositionPicker, RoughDateField, flatten, fmtDate,
  fmtDated, roughDate, today,
} from "../components/MaintenanceParts.jsx";
import { costText, costValue, roughDateValue } from "../maintenanceFields.js";
import { itemWhere } from "../maintenanceLocations.js";
import { TasksCard, WorkOrdersCard } from "../components/MaintenanceTasks.jsx";
import { MeasurementsCard } from "./MaintenancePosition.jsx";
import { ItemKindCard, useKinds } from "../components/MaintenanceItemClasses.jsx";
import { ConditionsCard } from "../components/MaintenanceConditions.jsx";
import "./Maintenance.css";

const ITEM_DATES = [
  { key: "purchase_date", label: "Bought" },
  { key: "in_service_date", label: "In service since" },
  { key: "manufacture_date", label: "Made" },
];

// One physical item: its details and nameplate, where it is and has been, its
// own positions, its photos, and its own tasks (they follow it wherever it goes),
// work orders and measurements.
export default function MaintenanceItem() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [kinds] = useKinds();

  const refresh = useCallback(() => {
    getMaintenanceItem(id).then(setItem).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);

  if (error && !item) return <div className="app"><div className="card error">{error}</div></div>;
  if (!item) return <div className="app"><div className="card empty">Loading…</div></div>;

  const plate = Object.entries(item.nameplate || {});
  const where = itemWhere(item, fmtDate);
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Maintenance", to: "/maintenance" }, { label: "Items", to: "/maintenance/items" }]}
        title={item.name}
        meta={[item.manufacturer, item.model, item.serial && `serial ${item.serial}`].filter(Boolean).join(" · ") || "Item"}
        id={item.id}
        actions={
          <>
            {/* A fitted item is where its position is: only an item that isn't fitted is placed. */}
            {!item.fitted_to && <button className="secondary" onClick={() => setModal("place")}>Place at a location</button>}
            <button className="secondary" onClick={() => setModal("move")}>Move to a position</button>
            <button className="secondary" onClick={() => setModal("more")}>Dates, cost and warranty</button>
          </>
        }
        primary={<button onClick={() => setModal("edit")}>Edit details</button>}
      />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}

      <section className="card">
        <div className="maint-head"><h2>Details</h2></div>
        <dl className="maint-plate">
          <dt>Fitted to</dt>
          <dd>{item.fitted_to ? <Link to={`/maintenance/positions/${item.fitted_to.id}`}>{item.fitted_to.name}</Link> : "Not fitted"}</dd>
          <dt>Location</dt>
          <dd>
            {where.locationId ? <Link to={`/maintenance/locations/${where.locationId}`}>{where.label}</Link> : where.label || "—"}
            {where.note && <span className="lib-date"> · {where.note}</span>}
          </dd>
          {item.part_number && <><dt>Part number</dt><dd>{item.part_number}</dd></>}
          {ITEM_DATES.filter((d) => item[d.key]).map((d) => (
            <Fragment key={d.key}>
              <dt>{d.label}</dt>
              <dd>{fmtDated(item[d.key].date, item[d.key].precision)}
                {item[d.key].source && <span className="lib-date"> ({item[d.key].source})</span>}</dd>
            </Fragment>
          ))}
          {(item.replacement_cost || item.class_replacement_cost) && <>
            <dt>Replacement cost</dt>
            <dd>{item.replacement_cost ? costText(item.replacement_cost, fmtDate) : <>
              {costText(item.class_replacement_cost, fmtDate)}
              <span className="lib-date"> (the {item.class_replacement_cost.position_class} default)</span></>}</dd>
          </>}
          {item.warranty && <>
            <dt>Warranty</dt>
            <dd>
              <span className={item.warranty.registration_overdue ? "maint-overdue" : undefined}>{item.warranty.summary}</span>
              {item.warranty.coverage && <div className="lib-date">Covers: {item.warranty.coverage}</div>}
              {item.warranty.terms && <div className="lib-date" style={{ whiteSpace: "pre-wrap" }}>{item.warranty.terms}</div>}
            </dd>
          </>}
          {plate.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
        </dl>
        {plate.length === 0 && (
          <p className="lib-date">No nameplate details yet. Add a photo of the nameplate and ask Claude to read it, or edit them here.</p>
        )}
      </section>

      <ItemKindCard item={item} kinds={kinds} onChanged={setItem} />

      <ConditionsCard target={{ id: item.id, name: item.name, kind: "Item" }} view={item} onChanged={refresh}
                      emptyText={`Nothing recorded. Fitted, ${item.name} takes its position's conditions; in a store, the store's. Add what applies to this item itself.`} />

      <NotesCard notes={item.notes} history={item.note_history}
                 onAppend={async (text) => setItem(await updateMaintenanceItem(item.id, { append_note: text }))} />
      <DocumentsCard documents={item.documents} target={{ target_id: item.id }} onChanged={refresh} />

      <MaintenancePhotos title="Photos" targetId={item.id} targetName={item.name} photos={item.photos} onChanged={refresh} />

      <TasksCard subject={{ kind: "item", id: item.id, name: item.name }} tasks={item.tasks || []}
                 counters={(item.measurements || []).filter((mp) => mp.kind === "counter")} onChanged={refresh}
                 emptyText={"No tasks on this item. Add one that follows this serial number wherever it goes: a statutory "
                   + "inspection or certificate, a calibration, warranty servicing, an overhaul every so many hours, or "
                   + "preserving it while it's a spare. Work on the job it does belongs on its position."} />
      <WorkOrdersCard workOrders={item.work_orders || []} />
      <MeasurementsCard measurements={item.measurements || []} target={{ kind: "item", id: item.id }} onChanged={refresh} />

      <section className="card">
        <div className="maint-head"><h2>Where it has been</h2></div>
        {item.history.length === 0 ? <p className="lib-date">Never fitted.</p> : (
          <table className="lib-table">
            <thead><tr><th>Position</th><th>In</th><th>Out</th><th>Why it came out</th></tr></thead>
            <tbody>
              {item.history.map((h) => (
                <tr key={h.id}>
                  <td>{h.position && <Link to={`/maintenance/positions/${h.position.id}`}>{h.position.name}</Link>}</td>
                  <td className="lib-date">{fmtDated(h.from, h.from_precision)}</td>
                  <td className="lib-date">{h.to ? fmtDated(h.to, h.to_precision) : "still fitted"}</td>
                  <td className="lib-date">{h.end_reason === "failure"
                    ? `failed${h.failure_mode ? `: ${h.failure_mode.text}` : ""}` : h.end_reason || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <div className="maint-head">
          <h2>Positions inside it</h2>
          <button className="secondary" onClick={() => setModal("child")}>Add a position inside it</button>
        </div>
        {item.positions.length === 0 ? (
          <p className="lib-date">None. For parts that travel with this item (an engine's turbos), add positions here.</p>
        ) : (
          <ul className="maint-list">
            {item.positions.map((p) => (
              <li key={p.id}>
                <Link to={`/maintenance/positions/${p.id}`}>{p.name}</Link>
                <span className="lib-date"> · {p.item ? p.item.name : "nothing fitted"}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {modal === "edit" && <EditItemModal item={item} onClose={() => setModal(null)} onDone={(d) => { setItem(d); setModal(null); }} />}
      {modal === "more" && <DetailsModal item={item} onClose={() => setModal(null)} onDone={(d) => { setItem(d); setModal(null); }} />}
      {modal === "move" && <MoveModal item={item} onClose={() => setModal(null)} onDone={(d) => { setItem(d); setModal(null); }} />}
      {modal === "place" && <PlaceModal item={item} onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
      {modal === "child" && (
        <ChildModal item={item} onClose={() => setModal(null)} onDone={(p) => navigate(`/maintenance/positions/${p.id}`)} />
      )}
    </div>
  );
}

function EditItemModal({ item, onClose, onDone }) {
  const [f, setF] = useState({
    name: item.name, manufacturer: item.manufacturer || "", model: item.model || "", serial: item.serial || "",
    part_number: item.part_number || "", notes: item.notes || "",
  });
  const [plate, setPlate] = useState(Object.entries(item.nameplate || {}).map(([k, v]) => ({ k, v })));
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = async () => {
    const nameplate = {};
    for (const key of Object.keys(item.nameplate || {})) nameplate[key] = "";  // cleared unless kept below
    for (const { k, v } of plate) if (k.trim()) nameplate[k.trim()] = v;
    onDone(await updateMaintenanceItem(item.id, { ...f, nameplate }));
  };
  return (
    <FormModal title="Edit item" submitLabel="Save" canSubmit={!!f.name.trim()} onClose={onClose} onSubmit={submit}>
      <Field label="Name"><input value={f.name} onChange={set("name")} /></Field>
      <Field label="Manufacturer"><input value={f.manufacturer} onChange={set("manufacturer")} /></Field>
      <Field label="Model"><input value={f.model} onChange={set("model")} /></Field>
      <Field label="Serial"><input value={f.serial} onChange={set("serial")} /></Field>
      <Field label="Part number"><input value={f.part_number} onChange={set("part_number")} /></Field>
      <div className="login-field">
        <span>Nameplate fields</span>
        {plate.map((row, i) => (
          <div key={i} className="maint-row" style={{ marginTop: "0.25rem" }}>
            <input placeholder="e.g. Capacity" value={row.k}
                   onChange={(e) => setPlate(plate.map((r, j) => (j === i ? { ...r, k: e.target.value } : r)))} />
            <input placeholder="e.g. 315 L" value={row.v}
                   onChange={(e) => setPlate(plate.map((r, j) => (j === i ? { ...r, v: e.target.value } : r)))} />
            <button className="secondary" onClick={() => setPlate(plate.filter((_, j) => j !== i))}>Remove</button>
          </div>
        ))}
        <button className="secondary" style={{ marginTop: "0.5rem" }} onClick={() => setPlate([...plate, { k: "", v: "" }])}>
          Add a field
        </button>
      </div>
      <Field label="Notes (to add a line instead, use Add note; earlier versions are kept)">
        <textarea rows={4} value={f.notes} onChange={set("notes")} />
      </Field>
    </FormModal>
  );
}

// Dates (each with how well it's known and where it came from), replacement cost
// and warranty: fields, not notes.
function DetailsModal({ item, onClose, onDone }) {
  const [dates, setDates] = useState(Object.fromEntries(ITEM_DATES.map(({ key }) => [key, {
    ...roughDate(item[key]?.date, item[key]?.precision), source: item[key]?.source || "",
  }])));
  const rc = item.replacement_cost || {};
  const [cost, setCost] = useState({ amount: rc.amount ?? "", currency: rc.currency || "", source: rc.source || "", as_of: rc.as_of || "" });
  const w = item.warranty || {};
  const [warranty, setWarranty] = useState({
    ends_on: w.ends_on || "", terms: w.terms || "", coverage: w.coverage || "",
    registration_required: !!w.registration_required, registered: !!w.registered, register_by: w.register_by || "",
  });
  const submit = async () => {
    const body = {};
    for (const { key } of ITEM_DATES) {
      const d = dates[key];
      const text = roughDateValue(d.text, d.precision);
      body[key] = text ? { date: text, precision: d.precision, source: d.source } : null;
    }
    body.replacement_cost = costValue(cost);
    body.warranty = warranty.ends_on ? { ...warranty, register_by: warranty.register_by || null } : null;
    onDone(await updateMaintenanceItem(item.id, body));
  };
  const setW = (k) => (e) => setWarranty({ ...warranty, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  return (
    <FormModal title={`${item.name}: dates, cost and warranty`} submitLabel="Save" onClose={onClose} onSubmit={submit}>
      <p className="lib-date">Known only roughly? Say so (a year, a month, or an estimate) rather than guessing a day.</p>
      {ITEM_DATES.map(({ key, label }) => (
        <div key={key}>
          <RoughDateField label={label} value={dates[key]} max={today()}
                          onChange={(v) => setDates({ ...dates, [key]: { ...dates[key], ...v } })} />
          <Field label="Where that came from (optional)">
            <input value={dates[key].source} placeholder="e.g. receipt, serial date code, owner's estimate"
                   onChange={(e) => setDates({ ...dates, [key]: { ...dates[key], source: e.target.value } })} />
          </Field>
        </div>
      ))}
      <Field label="Replacement cost">
        <div className="maint-row" style={{ marginTop: 0 }}>
          <input type="number" inputMode="decimal" min="0" step="any" value={cost.amount} placeholder="amount"
                 onChange={(e) => setCost({ ...cost, amount: e.target.value })} style={{ width: "8rem" }} />
          <input value={cost.currency} placeholder="AUD" maxLength={3} style={{ width: "5rem" }}
                 onChange={(e) => setCost({ ...cost, currency: e.target.value.toUpperCase() })} />
        </div>
      </Field>
      <Field label="Cost source (optional)"><input value={cost.source} placeholder="e.g. supplier quote"
             onChange={(e) => setCost({ ...cost, source: e.target.value })} /></Field>
      <Field label="Price as of"><input type="date" value={cost.as_of} max={today()}
             onChange={(e) => setCost({ ...cost, as_of: e.target.value })} /></Field>
      <Field label="Warranty ends on (blank: no warranty)"><input type="date" value={warranty.ends_on} onChange={setW("ends_on")} /></Field>
      {warranty.ends_on && <>
        <Field label="What it covers"><input value={warranty.coverage} placeholder="e.g. parts and labour, compressor 5 years"
               onChange={setW("coverage")} /></Field>
        <Field label="Terms"><textarea rows={2} value={warranty.terms} onChange={setW("terms")} /></Field>
        <label className="maint-row" style={{ gap: "0.4rem" }}>
          <input type="checkbox" checked={warranty.registration_required} onChange={setW("registration_required")} />
          It must be registered
        </label>
        {warranty.registration_required && <>
          <label className="maint-row" style={{ gap: "0.4rem" }}>
            <input type="checkbox" checked={warranty.registered} onChange={setW("registered")} /> Registered
          </label>
          {!warranty.registered && <Field label="Register by"><input type="date" value={warranty.register_by} onChange={setW("register_by")} /></Field>}
        </>}
      </>}
    </FormModal>
  );
}

function MoveModal({ item, onClose, onDone }) {
  const [positions, setPositions] = useState([]);
  const [to, setTo] = useState(null);
  const [on, setOn] = useState(today());
  useEffect(() => {
    getMaintenanceOverview().then((d) => setPositions(flatten(d.tree))).catch(() => {});
  }, []);
  return (
    <FormModal title={`Move ${item.name}`} submitLabel="Move" canSubmit={!!to} onClose={onClose}
               onSubmit={async () => onDone(await moveMaintenanceItem(item.id, to, on))}>
      <p className="lib-date">
        {item.fitted_to ? `It comes out of ${item.fitted_to.name} (a planned removal) and goes in here.` : "It goes in here."}
        {" "}The position must be empty.
      </p>
      <Field label="To position"><PositionPicker positions={positions} value={to} onChange={setTo} emptyLabel="Choose…" /></Field>
      <Field label="On"><input type="date" value={on} onChange={(e) => setOn(e.target.value)} /></Field>
    </FormModal>
  );
}

function PlaceModal({ item, onClose, onDone }) {
  const [locations, setLocations] = useState(null);
  const [to, setTo] = useState("");
  useEffect(() => {
    listMaintenanceLocations().then((d) => setLocations(d.locations || [])).catch(() => setLocations([]));
  }, []);
  return (
    <FormModal title={`Where is ${item.name}?`} submitLabel="Save" canSubmit={!!to} onClose={onClose}
               onSubmit={async () => onDone(await placeMaintenanceItem(item.id, to))}>
      <p className="lib-date">For an item that isn't fitted: a spare in a store, or one away for repair.</p>
      <Field label="Location">
        <LocationPicker locations={locations} value={to} onChange={(v) => setTo(v || "")}
                        emptyLabel={locations?.length === 0 ? "No locations yet: add one under Locations" : "Choose…"} />
      </Field>
    </FormModal>
  );
}

function ChildModal({ item, onClose, onDone }) {
  const [name, setName] = useState("");
  return (
    <FormModal title={`A position inside ${item.name}`} submitLabel="Create" canSubmit={!!name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await createMaintenancePosition({ name, parent_id: item.id }))}>
      <p className="lib-date">It travels with {item.name}: whatever is fitted to it goes where the item goes.</p>
      <Field label="Name"><input autoFocus value={name} placeholder="e.g. Turbo 1" onChange={(e) => setName(e.target.value)} /></Field>
    </FormModal>
  );
}
