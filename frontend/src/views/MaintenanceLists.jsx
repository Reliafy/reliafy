import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createMaintenanceLocation,
  fitClassModel,
  getClassLifeData,
  getPositionClass,
  setClassCosts,
  getMaintenanceLocation,
  getPositionClasses,
  listMaintenanceItems,
  listMaintenanceLocations,
  updateMaintenanceLocation,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import { Field, FormModal, LifeTable, MaintenanceTabs, Proposals, fmtDate } from "../components/MaintenanceParts.jsx";
import "./Maintenance.css";

const crumbs = [{ label: "Maintenance", to: "/maintenance" }];

// ---- items -------------------------------------------------------------------------------

export function MaintenanceItems() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  useEffect(() => {
    listMaintenanceItems().then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, []);
  const visible = (items || []).filter((i) => matches(query, i.name, i.serial, i.manufacturer, i.model, i.part_number));
  return (
    <div className="app">
      <PageHeader crumbs={crumbs} title="Items" meta="Every physical thing: where it's fitted, where it is." />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}
      {items === null ? <div className="card empty">Loading…</div> : items.length === 0 ? (
        <div className="card empty"><p>No items yet. Fit one to a position.</p></div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {items.length} items</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search items…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead><tr><th>Item</th><th>Make and model</th><th>Serial</th><th>Fitted to</th><th>Location</th></tr></thead>
              <tbody>
                {visible.map((i) => (
                  <tr key={i.id} className="lib-row" onClick={() => navigate(`/maintenance/items/${i.id}`)}>
                    <td>{i.name}</td>
                    <td className="lib-date">{[i.manufacturer, i.model].filter(Boolean).join(" ") || "—"}</td>
                    <td className="lib-date">{i.serial || "—"}</td>
                    <td>{i.fitted_to?.name || <span className="lib-date">not fitted</span>}</td>
                    <td className="lib-date">{i.location?.name || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ---- locations -------------------------------------------------------------------------

function LocNode({ node }) {
  return (
    <li>
      <div className="maint-node">
        <Link className="maint-node-name" to={`/maintenance/locations/${node.id}`}>{node.name}</Link>
        {node.items > 0 && <span className="lib-date">{node.items} item{node.items === 1 ? "" : "s"}</span>}
      </div>
      {node.children.length > 0 && <ul>{node.children.map((c) => <LocNode key={c.id} node={c} />)}</ul>}
    </li>
  );
}

export function NewLocationModal({ locations, parentId = null, onClose, onDone }) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState(parentId || "");
  return (
    <FormModal title="New location" submitLabel="Create" canSubmit={!!name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await createMaintenanceLocation({ name, parent_id: parent || null }))}>
      <Field label="Name"><input autoFocus value={name} placeholder="e.g. Laundry, Garage, Store A" onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Inside">
        <select value={parent} onChange={(e) => setParent(e.target.value)}>
          <option value="">None (top level)</option>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.parent ? `${l.parent.name} › ` : ""}{l.name}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}

export function MaintenanceLocations() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [modal, setModal] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    listMaintenanceLocations().then(setData).catch((e) => setError(e.message));
  }, []);
  return (
    <div className="app">
      <PageHeader crumbs={crumbs} title="Locations" meta="Physical places: sites, buildings, rooms and stores."
                  primary={<button onClick={() => setModal(true)}><PlusIcon /> New location</button>} />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}
      {data === null ? <div className="card empty">Loading…</div> : data.tree.length === 0 ? (
        <div className="card empty"><p>No locations yet. Add the house, its rooms, the shed.</p></div>
      ) : (
        <section className="card"><ul className="maint-tree">{data.tree.map((n) => <LocNode key={n.id} node={n} />)}</ul></section>
      )}
      {modal && <NewLocationModal locations={data?.locations || []} onClose={() => setModal(false)}
                                  onDone={(l) => navigate(`/maintenance/locations/${l.id}`)} />}
    </div>
  );
}

export function MaintenanceLocation() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [loc, setLoc] = useState(null);
  const [all, setAll] = useState([]);
  const [modal, setModal] = useState(null);
  const [error, setError] = useState(null);
  const refresh = useCallback(() => {
    getMaintenanceLocation(id).then(setLoc).catch((e) => setError(e.message));
  }, [id]);
  useEffect(() => refresh(), [refresh]);
  useEffect(() => {
    listMaintenanceLocations().then((d) => setAll(d.locations)).catch(() => {});
  }, []);
  if (error && !loc) return <div className="app"><div className="card error">{error}</div></div>;
  if (!loc) return <div className="app"><div className="card empty">Loading…</div></div>;
  return (
    <div className="app">
      <PageHeader
        crumbs={[...crumbs, { label: "Locations", to: "/maintenance/locations" },
          ...loc.path.map((a) => ({ label: a.name, to: `/maintenance/locations/${a.id}` }))]}
        title={loc.name} meta={loc.description || "Location"} id={loc.id}
        actions={<button className="secondary" onClick={() => setModal("child")}><PlusIcon /> Location inside</button>}
        primary={<button onClick={() => setModal("rename")}>Rename</button>}
      />
      <MaintenanceTabs />
      <section className="card">
        <div className="maint-head"><h2>Here now</h2></div>
        {loc.items.length === 0 ? <p className="lib-date">Nothing placed here. Place items from their page.</p> : (
          <ul className="maint-list">
            {loc.items.map((i) => (
              <li key={i.id}><Link to={`/maintenance/items/${i.id}`}>{i.name}</Link>
                <span className="lib-date"> · since {fmtDate(i.since)}</span></li>
            ))}
          </ul>
        )}
      </section>
      {loc.children.length > 0 && (
        <section className="card">
          <div className="maint-head"><h2>Inside it</h2></div>
          <ul className="maint-list">{loc.children.map((c) => <li key={c.id}><Link to={`/maintenance/locations/${c.id}`}>{c.name}</Link></li>)}</ul>
        </section>
      )}
      <MaintenancePhotos targetId={loc.id} targetName={loc.name} photos={loc.photos} onChanged={refresh} />
      {loc.coordinates && <p className="lib-date">Coordinates: {loc.coordinates.lat}, {loc.coordinates.lon}</p>}
      {modal === "child" && <NewLocationModal locations={all} parentId={loc.id} onClose={() => setModal(null)}
                                              onDone={(l) => { setModal(null); navigate(`/maintenance/locations/${l.id}`); }} />}
      {modal === "rename" && <RenameLocation loc={loc} onClose={() => setModal(null)} onDone={(d) => { setLoc(d); setModal(null); }} />}
    </div>
  );
}

function RenameLocation({ loc, onClose, onDone }) {
  const [name, setName] = useState(loc.name);
  const [description, setDescription] = useState(loc.description || "");
  return (
    <FormModal title="Rename location" submitLabel="Save" canSubmit={!!name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenanceLocation(loc.id, { name, description }))}>
      <Field label="Name"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
    </FormModal>
  );
}

// ---- position classes ----------------------------------------------------------------------

export function MaintenanceClasses() {
  const [classes, setClasses] = useState(null);
  const [open, setOpen] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    getPositionClasses().then((d) => setClasses(d.classes)).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!open) return;
    setData(null);
    getClassLifeData(open).then(setData).catch((e) => setError(e.message));
  }, [open]);
  return (
    <div className="app">
      <PageHeader crumbs={crumbs} title="Position classes"
                  meta="Like positions grouped, so their items' lives can be compared and pooled into one model." />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}
      {classes === null ? <div className="card empty">Loading…</div> : classes.length === 0 ? (
        <div className="card empty"><p>No classes yet. Give positions a class (e.g. “Pool pump”) when you create or edit them.</p></div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead><tr><th>Class</th><th>Positions</th><th>Fitments</th><th>Failures</th></tr></thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.position_class} className="lib-row" onClick={() => setOpen(c.position_class)}>
                  <td>{c.position_class}</td><td>{c.positions}</td><td>{c.fitments}</td><td>{c.failures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {open && <ClassPanel name={open} onChanged={() => getPositionClasses().then((d) => setClasses(d.classes))} />}
      {open && (
        <section className="card">
          <div className="maint-head">
            <h2>{open}: pooled life data</h2>
            {data && <span className="lib-date">{data.failures} failures · {data.suspensions} suspensions</span>}
          </div>
          {data === null ? <p className="lib-date">Loading…</p> : <LifeTable rows={data.rows} showPosition />}
        </section>
      )}
    </div>
  );
}

function ClassPanel({ name, onChanged }) {
  const [c, setC] = useState(null);
  const [costs, setCosts] = useState({ planned_cost: "", failure_cost: "", availability_target: "" });
  const [distribution, setDistribution] = useState("weibull");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [made, setMade] = useState(null);
  const load = useCallback(() => {
    getPositionClass(name).then((d) => {
      setC(d);
      setCosts({
        planned_cost: d.costs?.planned_cost ?? "", failure_cost: d.costs?.failure_cost ?? "",
        availability_target: d.costs?.availability_target ?? "",
      });
    }).catch((e) => setError(e.message));
  }, [name]);
  useEffect(() => { setMade(null); load(); }, [load]);
  const save = async () => {
    setBusy("costs"); setError(null);
    try { setC(await setClassCosts({ position_class: name, ...costs })); onChanged?.(); } catch (e) { setError(e.message); }
    setBusy(null);
  };
  const fit = async () => {
    setBusy("fit"); setError(null);
    try { const d = await fitClassModel(name, distribution); setMade(d.proposals.length); load(); onChanged?.(); } catch (e) { setError(e.message); }
    setBusy(null);
  };
  if (!c) return <section className="card">{error ? <div className="card error">{error}</div> : <p className="lib-date">Loading…</p>}</section>;
  const model = c.model;
  return (
    <>
      <section className="card">
        <div className="maint-head"><h2>{name}: life model and costs</h2></div>
        {error && <div className="card error">{error}</div>}
        <div className="rcm-form">
          <Field label="A planned replacement costs"><input type="number" min="0" step="any" value={costs.planned_cost}
                 onChange={(e) => setCosts({ ...costs, planned_cost: e.target.value })} /></Field>
          <Field label="A failure costs (repair, downtime, damage)"><input type="number" min="0" step="any" value={costs.failure_cost}
                 onChange={(e) => setCosts({ ...costs, failure_cost: e.target.value })} /></Field>
          <Field label="Hidden functions must be available (e.g. 0.99)"><input type="number" min="0" max="1" step="any"
                 value={costs.availability_target} onChange={(e) => setCosts({ ...costs, availability_target: e.target.value })} /></Field>
        </div>
        <div className="maint-row">
          <button className="secondary" onClick={save} disabled={busy === "costs"}>{busy === "costs" ? "Saving…" : "Save costs"}</button>
          <select value={distribution} onChange={(e) => setDistribution(e.target.value)}>
            <option value="weibull">Weibull</option><option value="best">Best fit</option>
            <option value="lognormal">Lognormal</option><option value="exponential">Exponential</option>
          </select>
          <button onClick={fit} disabled={busy === "fit" || c.failures < 2}>
            {busy === "fit" ? "Fitting…" : model ? "Refit the life model" : "Fit a life model"}
          </button>
          {c.failures < 2 && <span className="lib-date">Needs at least 2 failures on record ({c.failures} so far).</span>}
        </div>
        {model && (
          <p className="lib-date" style={{ marginTop: "0.75rem" }}>
            {model.distribution} fitted {fmtDate(model.fitted_on)} to {model.failures} failures and {model.suspensions} suspensions:{" "}
            {(model.params || []).map((p) => `${p.name} ${Number(p.value).toPrecision(4)}`).join(", ")} (days).{" "}
            <Link to={`/modelling/m/${model.model_id}`}>Open the model</Link>
          </p>
        )}
        {made !== null && <p className="lib-date">{made ? `${made} change${made === 1 ? "" : "s"} proposed.` : "No changes to propose: the tasks already match."}</p>}
      </section>
      <Proposals proposals={c.proposals} onDecided={load} />
    </>
  );
}
