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
  Field, FormModal, MaintenanceTabs, NotesCard, PositionPicker, flatten, fmtDate, today,
} from "../components/MaintenanceParts.jsx";
import "./Maintenance.css";

// One physical item: its details and nameplate, where it is and has been, its
// own positions, and its photos.
export default function MaintenanceItem() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [item, setItem] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);

  const refresh = useCallback(() => {
    getMaintenanceItem(id).then(setItem).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);

  if (error && !item) return <div className="app"><div className="card error">{error}</div></div>;
  if (!item) return <div className="app"><div className="card empty">Loading…</div></div>;

  const plate = Object.entries(item.nameplate || {});
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Maintenance", to: "/maintenance" }, { label: "Items", to: "/maintenance/items" }]}
        title={item.name}
        meta={[item.manufacturer, item.model, item.serial && `serial ${item.serial}`].filter(Boolean).join(" · ") || "Item"}
        id={item.id}
        actions={
          <>
            <button className="secondary" onClick={() => setModal("place")}>Place at a location</button>
            <button className="secondary" onClick={() => setModal("move")}>Move to a position</button>
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
          <dd>{item.location ? <Link to={`/maintenance/locations/${item.location.id}`}>{item.location.name}</Link> : "—"}</dd>
          {item.part_number && <><dt>Part number</dt><dd>{item.part_number}</dd></>}
          {plate.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}
        </dl>
        {plate.length === 0 && (
          <p className="lib-date">No nameplate details yet. Add a photo of the nameplate and ask Claude to read it, or edit them here.</p>
        )}
      </section>

      <NotesCard notes={item.notes} history={item.note_history}
                 onAppend={async (text) => setItem(await updateMaintenanceItem(item.id, { append_note: text }))} />

      <MaintenancePhotos title="Photos" targetId={item.id} targetName={item.name} photos={item.photos} onChanged={refresh} />

      <section className="card">
        <div className="maint-head"><h2>Where it has been</h2></div>
        {item.history.length === 0 ? <p className="lib-date">Never fitted.</p> : (
          <table className="lib-table">
            <thead><tr><th>Position</th><th>In</th><th>Out</th><th>Why it came out</th></tr></thead>
            <tbody>
              {item.history.map((h) => (
                <tr key={h.id}>
                  <td>{h.position && <Link to={`/maintenance/positions/${h.position.id}`}>{h.position.name}</Link>}</td>
                  <td className="lib-date">{fmtDate(h.from)}</td>
                  <td className="lib-date">{h.to ? fmtDate(h.to) : "still fitted"}</td>
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
      <Field label="Location">
        <select value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="">{locations === null ? "Loading…" : locations.length ? "Choose…" : "No locations yet: add one under Locations"}</option>
          {(locations || []).map((l) => <option key={l.id} value={l.id}>{l.parent ? `${l.parent.name} › ` : ""}{l.name}</option>)}
        </select>
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
