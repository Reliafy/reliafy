import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createMaintenanceLocation,
  fitClassModel,
  getClassEconomics,
  getClassForecast,
  getClassLifeData,
  getPositionClass,
  setClassCosts,
  setClassReplacementCost,
  getMaintenanceLocation,
  getPositionClasses,
  adjustMaintenanceStock,
  createMaintenancePart,
  getSparesCover,
  listMaintenanceItems,
  listMaintenanceParts,
  setMaintenanceReorder,
  listMaintenanceLocations,
  updateMaintenanceLocation,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { SectionHeader } from "../components/SectionPage.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import {
  DocumentsCard, Field, FormModal, LifeTable, Proposals, fmtDate,
} from "../components/MaintenanceParts.jsx";
import { costText, costValue } from "../maintenanceFields.js";
import { roleLabel } from "../maintenanceSpares.js";
import { countsText, inheritedText, itemWhere } from "../maintenanceLocations.js";
import { TasksCard, WorkOrdersCard } from "../components/MaintenanceTasks.jsx";
import {
  ClassPicker, ItemClassesSection, KindFilters, PartKindModal, useKinds,
} from "../components/MaintenanceItemClasses.jsx";
import { ConditionsCard, ConditionsSection } from "../components/MaintenanceConditions.jsx";
import { ClassStocking } from "../components/MaintenanceStocking.jsx";
import { ImportBomModal, LevelsModal, StructureTree } from "../components/MaintenanceStructure.jsx";
import { partsForest } from "../maintenanceStructure.js";
import SegmentedControl from "../components/ui/SegmentedControl.jsx";
import Plot from "../components/Plot.jsx";
import ResultSummary from "../components/ui/ResultSummary.jsx";
import { ACCENT, INK } from "../plotTheme.js";
import { formatNumber, formatPercent } from "../format.js";
import {
  FORECAST_PERIODS, horizonText, money, moneyRange, periodLabels, rangeText, spareCover,
} from "../maintenanceForecast.js";
import "./Maintenance.css";

const crumbs = [{ label: "Maintenance", to: "/maintenance" }];

// ---- items -------------------------------------------------------------------------------

export function MaintenanceItems() {
  const navigate = useNavigate();
  const [items, setItems] = useState(null);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState({ itemClassId: null, manufacturerId: null });
  const [kinds] = useKinds();
  const [error, setError] = useState(null);
  useEffect(() => {
    listMaintenanceItems(filter).then((d) => setItems(d.items)).catch((e) => setError(e.message));
  }, [filter]);
  const filtered = !!(filter.itemClassId || filter.manufacturerId);
  // The class column only once items have classes.
  const showClass = (items || []).some((i) => i.item_class);
  const visible = (items || []).filter((i) => matches(query, i.name, i.serial, i.manufacturer, i.model, i.part_number,
    i.item_class?.name, i.manufacturer_entry?.name));
  return (
    <div className="app">
      <SectionHeader section="maintenance" title="Items" purpose="Every physical thing: where it's fitted, where it is." />
      {error && <div className="card error">{error}</div>}
      {items === null ? <div className="card empty">Loading…</div> : items.length === 0 && !filtered ? (
        <div className="card empty"><p>No items yet. Fit one to a position.</p></div>
      ) : (
        <>
          <div className="tablebar section-tablebar">
            <span className="count">{visible.length} of {items.length} items</span>
            <span className="grow" />
            <KindFilters classes={kinds.classes} makers={kinds.makers} value={filter} onChange={setFilter} />
            <ListSearch value={query} onChange={setQuery} placeholder="Search items…" />
          </div>
          <div className="lib maint-scroll">
            <table className="lib-table">
              <thead><tr><th>Item</th>{showClass && <th>Class</th>}<th>Make and model</th><th>Serial</th><th>Fitted to</th><th>Location</th></tr></thead>
              <tbody>
                {visible.map((i) => (
                  <tr key={i.id} className="lib-row" onClick={() => navigate(`/maintenance/items/${i.id}`)}>
                    <td>{i.name}</td>
                    {showClass && <td className="lib-date">{i.item_class?.name || "—"}</td>}
                    <td className="lib-date">{[i.manufacturer_entry?.name || i.manufacturer, i.model].filter(Boolean).join(" ") || "—"}</td>
                    <td className="lib-date">{i.serial || "—"}</td>
                    <td>{i.fitted_to?.name || <span className="lib-date">not fitted</span>}</td>
                    <td className="lib-date">{itemWhere(i).label || "—"}</td>
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
        {node.all_positions > 0 && (
          <span className="lib-date">{node.all_positions} position{node.all_positions === 1 ? "" : "s"}</span>
        )}
        {node.all_items > 0 && <span className="lib-date">{node.all_items} item{node.all_items === 1 ? "" : "s"} placed</span>}
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
      <SectionHeader section="maintenance" title="Locations"
                  purpose="Physical places: sites, areas, rooms and stores. Positions are located in them; spares are placed in them."
                  primary={<button onClick={() => setModal(true)}><PlusIcon /> New location</button>} />
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
        title={loc.name} meta={[loc.description, countsText(loc.counts)].filter(Boolean).join(" · ") || "Location"} id={loc.id}
        actions={<>
          {loc.counts.open_work_orders > 0 && (
            <button className="secondary" onClick={() => navigate(`/maintenance?location=${loc.id}`)}>
              Open work orders here ({loc.counts.open_work_orders})</button>
          )}
          <button className="secondary" onClick={() => setModal("child")}><PlusIcon /> Location inside</button>
        </>}
        primary={<button onClick={() => setModal("rename")}>Rename</button>}
      />
      <TasksCard subject={{ kind: "location", id: loc.id, name: loc.name }} tasks={loc.tasks || []} onChanged={refresh}
                 emptyText={"No tasks on this place. Add a round or walkdown, an Ex (hazardous-area) inspection, or a "
                   + "building or area check: it raises one work order here, and can list every position here to check."} />
      {(loc.work_orders || []).length > 0 && <WorkOrdersCard workOrders={loc.work_orders} />}
      <ConditionsCard target={{ id: loc.id, name: loc.name, kind: "Location" }} view={loc} onChanged={refresh} />
      <LocationPositions loc={loc} />
      <section className="card">
        <div className="maint-head"><h2>Items placed here</h2></div>
        {loc.items.length === 0 ? (
          <p className="lib-date">No spares or items away from their positions here. (Fitted items are where their
            positions are; place an item that isn't fitted from its page.)</p>
        ) : (
          <ul className="maint-list">
            {loc.items.map((i) => (
              <li key={i.id}><Link to={`/maintenance/items/${i.id}`}>{i.name}</Link>
                <span className="lib-date">
                  {i.location.id !== loc.id && <> · in <Link to={`/maintenance/locations/${i.location.id}`}>{i.location.name}</Link></>}
                  {" "}· since {fmtDate(i.since)}</span></li>
            ))}
          </ul>
        )}
      </section>
      {loc.children.length > 0 && (
        <section className="card">
          <div className="maint-head"><h2>Inside it</h2></div>
          <ul className="maint-list">{loc.children.map((c) => (
            <li key={c.id}><Link to={`/maintenance/locations/${c.id}`}>{c.name}</Link>
              {(c.positions > 0 || c.items > 0) && (
                <span className="lib-date"> · {[c.positions && `${c.positions} position${c.positions === 1 ? "" : "s"}`,
                  c.items && `${c.items} item${c.items === 1 ? "" : "s"} placed`].filter(Boolean).join(", ")}</span>
              )}</li>
          ))}</ul>
        </section>
      )}
      <MaintenancePhotos targetId={loc.id} targetKind="Location" targetName={loc.name} photos={loc.photos} onChanged={refresh} />
      {loc.coordinates && <p className="lib-date">Coordinates: {loc.coordinates.lat}, {loc.coordinates.lon}</p>}
      {modal === "child" && <NewLocationModal locations={all} parentId={loc.id} onClose={() => setModal(null)}
                                              onDone={(l) => { setModal(null); navigate(`/maintenance/locations/${l.id}`); }} />}
      {modal === "rename" && <RenameLocation loc={loc} onClose={() => setModal(null)} onDone={(d) => { setLoc(d); setModal(null); }} />}
    </div>
  );
}

// The positions at a location (set on them or inherited, here or inside it), by the
// system each belongs to, with what's fitted to each.
function LocationPositions({ loc }) {
  return (
    <section className="card">
      <div className="maint-head"><h2>Positions here</h2></div>
      {loc.systems.length === 0 ? (
        <p className="lib-date">No positions here yet. Set a position's location on its page: the positions inside it
          follow, and so does whatever is fitted.</p>
      ) : loc.systems.map((g) => (
        <div key={g.system.id} className="maint-group">
          <h3>
            <Link to={`/maintenance/${g.system.kind === "Item" ? "items" : "positions"}/${g.system.id}`}>{g.system.name}</Link>
            <span className="lib-date"> · {g.count} here</span>
          </h3>
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Position</th><th>Where</th><th>Fitted</th><th>Work</th></tr></thead>
            <tbody>
              {g.positions.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/maintenance/positions/${r.id}`}>{r.path}</Link>{r.tag && <span className="lib-date"> · {r.tag}</span>}</td>
                  <td className="lib-date">
                    {r.location.id !== loc.id && <><Link to={`/maintenance/locations/${r.location.id}`}>{r.location.name}</Link> · </>}
                    {r.direct ? "set here" : inheritedText({ inherited: true, inherited_from: r.inherited_from })}
                  </td>
                  <td>{r.item ? <Link to={`/maintenance/items/${r.item.id}`}>{r.item.name}</Link> : <span className="lib-date">nothing fitted</span>}</td>
                  <td>{r.open_work_orders > 0 ? <span className="maint-badge">{r.open_work_orders} open</span> : <span className="lib-date">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </div>
      ))}
      {loc.positions_truncated && (
        <p className="lib-date">Showing the first {loc.systems.reduce((n, g) => n + g.positions.length, 0)} of{" "}
          {loc.counts.positions} positions.</p>
      )}
    </section>
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
  const navigate = useNavigate();
  // A class's own page (/maintenance/classes/Pool%20pump) opens its panel.
  const { name: open = null } = useParams();
  const setOpen = (name) => navigate(`/maintenance/classes/${encodeURIComponent(name)}`);
  const [classes, setClasses] = useState(null);
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
      <SectionHeader section="maintenance" title="Classes"
                  purpose="Position classes group like positions by their duty, so their items' lives can be compared and pooled into one model. Item classes (optional) say what kind of thing each item is; conditions (optional), what things are exposed to." />
      {error && <div className="card error">{error}</div>}
      <h2 className="maint-section">Position classes</h2>
      {classes === null ? <div className="card empty">Loading…</div> : classes.length === 0 ? (
        <div className="card empty"><p>No classes yet. Give positions a class (e.g. “Pool pump”) when you create or edit them.</p></div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead><tr><th>Class</th><th>Positions</th><th>Fitments</th><th>Failures</th></tr></thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.position_class} className="lib-row" onClick={() => setOpen(c.position_class)}
                    aria-current={c.position_class === open ? "true" : undefined}>
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
            {data && <span className="lib-date">{data.failures} failures · {data.suspensions} suspensions
              {data.uncertain ? ` · ${data.uncertain} with dates known only roughly (fitted as ranges)` : ""}</span>}
          </div>
          {data === null ? <p className="lib-date">Loading…</p> : <LifeTable rows={data.rows} showPosition />}
        </section>
      )}
      <h2 className="maint-section">What kind of thing</h2>
      <ItemClassesSection />
      <h2 className="maint-section">What things are exposed to</h2>
      <ConditionsSection />
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
        <div className="maint-head"><h2>{name}: non-repairable model and costs</h2></div>
        {error && <div className="card error">{error}</div>}
        <div className="rcm-form">
          <Field label="A planned replacement costs"><input type="number" inputMode="decimal" min="0" step="any" value={costs.planned_cost}
                 onChange={(e) => setCosts({ ...costs, planned_cost: e.target.value })} /></Field>
          <Field label="A failure costs (repair, downtime, damage)"><input type="number" inputMode="decimal" min="0" step="any" value={costs.failure_cost}
                 onChange={(e) => setCosts({ ...costs, failure_cost: e.target.value })} /></Field>
          <Field label="Hidden functions must be available (e.g. 0.99)"><input type="number" inputMode="decimal" min="0" max="1" step="any"
                 value={costs.availability_target} onChange={(e) => setCosts({ ...costs, availability_target: e.target.value })} /></Field>
        </div>
        <div className="maint-row">
          <button className="secondary" onClick={save} disabled={busy === "costs"}>{busy === "costs" ? "Saving…" : "Save costs"}</button>
          <select value={distribution} onChange={(e) => setDistribution(e.target.value)}>
            <option value="weibull">Weibull</option><option value="best">Best fit</option>
            <option value="lognormal">Lognormal</option><option value="exponential">Exponential</option>
          </select>
          <button onClick={fit} disabled={busy === "fit" || c.failures < 2}>
            {busy === "fit" ? "Fitting…" : model ? "Refit the non-repairable model" : "Fit a non-repairable model"}
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
        {made !== null && <p className="lib-date">{made ? `${made} change${made === 1 ? "" : "s"} proposed.` : "No changes to propose (no scheduled tasks here, or they already match)."}</p>}
      </section>
      {model && <ForecastCard key={model.model_id} name={name} />}
      <Proposals proposals={c.proposals} onDecided={load} />
      {model && c.costs?.planned_cost != null && c.costs?.failure_cost != null && <EconomicsCard name={name} />}
      <ReplacementCostCard name={name} cost={c.replacement_cost} onSaved={(d) => { setC(d); onChanged?.(); }} />
      <DocumentsCard title={`${name}: documents`} documents={c.documents} target={{ position_class: name }} onChanged={load} />
    </>
  );
}

// What an item doing this class's job costs to replace: the default for items with
// no replacement cost of their own (for renewal planning).
function ReplacementCostCard({ name, cost, onSaved }) {
  const [f, setF] = useState({ amount: cost?.amount ?? "", currency: cost?.currency || "", source: cost?.source || "",
    as_of: cost?.as_of || "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const save = async () => {
    setBusy(true); setError(null);
    try { onSaved(await setClassReplacementCost(name, costValue(f))); } catch (e) { setError(e.message); }
    setBusy(false);
  };
  return (
    <section className="card">
      <div className="maint-head"><h2>{name}: replacement cost</h2>
        <span className="lib-date">{cost ? costText(cost, fmtDate) : "not set"}</span></div>
      {error && <div className="card error">{error}</div>}
      <p className="lib-date">The default for items in these positions with no replacement cost of their own.</p>
      <div className="maint-row" style={{ marginTop: 0 }}>
        <input type="number" inputMode="decimal" min="0" step="any" placeholder="amount" value={f.amount} style={{ width: "8rem" }}
               onChange={(e) => setF({ ...f, amount: e.target.value })} />
        <input placeholder="AUD" maxLength={3} value={f.currency} style={{ width: "5rem" }}
               onChange={(e) => setF({ ...f, currency: e.target.value.toUpperCase() })} />
        <input placeholder="source, e.g. list price" value={f.source} onChange={(e) => setF({ ...f, source: e.target.value })} />
        <button className="secondary" onClick={save} disabled={busy}>{busy ? "Saving…" : f.amount === "" ? "Clear" : "Save"}</button>
      </div>
    </section>
  );
}

function EconomicsCard({ name }) {
  const [data, setData] = useState(null);
  const [whatIf, setWhatIf] = useState("");
  const [unit, setUnit] = useState("months");
  const [years, setYears] = useState(10);
  const [rate, setRate] = useState(7);
  const [error, setError] = useState(null);
  const load = useCallback(() => {
    getClassEconomics(name, { interval: whatIf || undefined, unit, horizonYears: years, discountRate: Number(rate) / 100 })
      .then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  }, [name, whatIf, unit, years, rate]);
  useEffect(() => { load(); }, [name]);  // eslint-disable-line react-hooks/exhaustive-deps
  const money = (v) => Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });
  return (
    <section className="card">
      <div className="maint-head"><h2>{name}: what the plan costs</h2></div>
      {error && <div className="card error">{error}</div>}
      <div className="maint-row" style={{ marginTop: 0 }}>
        <span className="lib-date">What if every</span>
        <input type="number" inputMode="decimal" min="0" step="any" value={whatIf} style={{ width: "5rem" }} onChange={(e) => setWhatIf(e.target.value)} />
        <select value={unit} onChange={(e) => setUnit(e.target.value)}>
          {["days", "weeks", "months", "years"].map((u) => <option key={u} value={u}>{u}</option>)}
        </select>
        <span className="lib-date">over</span>
        <input type="number" inputMode="numeric" min="1" max="100" value={years} style={{ width: "4rem" }} onChange={(e) => setYears(e.target.value)} />
        <span className="lib-date">years at</span>
        <input type="number" inputMode="decimal" min="0" max="99" step="any" value={rate} style={{ width: "4rem" }} onChange={(e) => setRate(e.target.value)} />
        <span className="lib-date">%</span>
        <button className="secondary" onClick={load}>Work it out</button>
      </div>
      {data && (
        <>
          <table className="lib-table" style={{ marginTop: "0.75rem" }}>
            <thead><tr><th>Plan</th><th>Interval</th><th>Per year</th><th>Net present cost</th></tr></thead>
            <tbody>
              {data.options.map((o) => (
                <tr key={o.plan}>
                  <td>{o.plan === data.cheapest ? <strong>{o.plan}</strong> : o.plan}</td>
                  <td className="lib-date">{o.interval}</td>
                  <td>{money(o.per_year)}</td>
                  <td>{money(o.net_present_cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="lib-date">{data.note}</p>
        </>
      )}
    </section>
  );
}

// The class's failure forecast from the register (#407): the answer first, then
// the periods, the positions most at risk, the spares and the budget.
function ForecastCard({ name }) {
  const [period, setPeriod] = useState("month");
  const [periods, setPeriods] = useState(12);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [allRisk, setAllRisk] = useState(false);
  // The spares' stock levels (#31): a service level for every part, and how often stock is checked.
  const [stocking, setStocking] = useState({ serviceLevel: "", reviewDays: "" });
  const load = useCallback(() => {
    setError(null);
    getClassForecast(name, { period, periods, ...stocking })
      .then(setData).catch((e) => { setData(null); setError(e.message); });
  }, [name, period, periods, stocking]);
  useEffect(() => { load(); }, [name, stocking]);  // eslint-disable-line react-hooks/exhaustive-deps
  const most = FORECAST_PERIODS.find((p) => p.id === period)?.most || 120;
  const shown = data?.period || period;  // the period the answer shown is in
  const horizon = data ? horizonText(data.periods, data.period) : "";
  const labels = data ? periodLabels(data.per_period, data.period) : [];
  const busy = data?.per_period?.some((r) => r.expected > 0);
  const risk = data ? (allRisk ? data.at_risk : data.at_risk.slice(0, 10)) : [];
  const budget = data?.budget;
  return (
    <section className="card" data-testid="class-forecast">
      <div className="maint-head"><h2>{name}: failure forecast</h2></div>
      <div className="maint-row" style={{ marginTop: 0 }}>
        <span className="lib-date">Next</span>
        <input type="number" inputMode="numeric" min="1" max={most} value={periods} style={{ width: "4.5rem" }}
               aria-label="How many periods" onChange={(e) => setPeriods(e.target.value)} />
        <select value={period} aria-label="Period"
                onChange={(e) => { setPeriod(e.target.value); setPeriods({ month: 12, quarter: 4, year: 3 }[e.target.value]); }}>
          {FORECAST_PERIODS.map((p) => <option key={p.id} value={p.id}>{p.label.toLowerCase()}</option>)}
        </select>
        <button className="secondary" onClick={load}>Forecast</button>
      </div>
      {error && <div className="card error">{error}</div>}
      {data === null && !error && <p className="lib-date">Working it out…</p>}
      {data && (
        <>
          <ResultSummary
            sentence={data.n_forecast ? (
              <>≈ <b>{formatNumber(data.expected)}</b> failures in the next <b>{horizon}</b> (likely {rangeText(data.interval)}).</>
            ) : data.headline}
            stats={[
              data.n_forecast > 0 && { label: "Likely range (80%)", value: rangeText(data.interval), hint: "P10–P90, counting replacements that fail again" },
              data.n_forecast > 0 && data.periods > 1 && { label: `Average a ${shown}`, value: `≈ ${formatNumber(data.expected / data.periods, { sig: 2 })}` },
              { label: "Positions forecast", value: `${data.n_forecast} of ${data.n_positions}` },
              budget && { label: "Budget", value: `≈ ${money(budget.expected, budget.currency)}`, hint: `likely ${moneyRange(budget.interval, budget.currency)}` },
            ]}
          >
            {data.basis}
          </ResultSummary>
          {busy && (
            <>
              <Plot
                data={[{
                  // On a date axis, so the ticks thin out on a phone; the hover names the period.
                  type: "bar", x: data.per_period.map((r) => r.start), y: data.per_period.map((r) => r.expected),
                  marker: { color: ACCENT },
                  error_y: {
                    type: "data", symmetric: false, color: INK, thickness: 1, width: 3,
                    array: data.per_period.map((r) => Math.max(0, r.p90 - r.expected)),
                    arrayminus: data.per_period.map((r) => Math.max(0, r.expected - r.p10)),
                  },
                  customdata: data.per_period.map((r, i) => [labels[i], r.p10, r.p90]),
                  hovertemplate: "%{customdata[0]}: %{y:.2f} expected (likely %{customdata[1]}–%{customdata[2]})<extra></extra>",
                }]}
                layout={{
                  height: 260, bargap: 0.35,
                  xaxis: { title: { text: `${shown[0].toUpperCase()}${shown.slice(1)} starting` }, type: "date" },
                  yaxis: { title: { text: `Expected failures a ${shown}` }, rangemode: "tozero" },
                }}
                download={`${name} — failure forecast`}
              />
              <p className="rs-note">Whiskers: each {shown}’s likely range (80%).</p>
            </>
          )}

          {risk.length > 0 && (
            <>
              <h3 className="maint-sub">Positions most at risk</h3>
              <div className="maint-scroll"><table className="lib-table">
                <thead><tr><th>Position</th><th>Item</th><th>In service</th><th>Chance it fails next {shown}</th><th>Failures in {horizon}</th></tr></thead>
                <tbody>
                  {risk.map((r) => (
                    <tr key={r.position.id}>
                      <td><Link to={`/maintenance/positions/${r.position.id}`}>{r.position.name}</Link></td>
                      <td>{r.item?.name || "—"}</td>
                      <td className="lib-date">{formatNumber(r.age)} {data.model.unit}{r.rate_basis === "counter" ? ` (+${formatNumber(r.rate_per_period)} a ${shown})` : ""}</td>
                      <td>{formatPercent(r.prob_next_period)}</td>
                      <td className="lib-date">≈ {formatNumber(r.expected_failures, { sig: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table></div>
              {data.at_risk.length > 10 && (
                <button className="link" onClick={() => setAllRisk(!allRisk)}>
                  {allRisk ? "Show the top 10" : `Show all ${data.at_risk.length}`}
                </button>
              )}
            </>
          )}
          {data.not_forecast.length > 0 && (
            <p className="lib-date">Not forecast: {data.not_forecast.slice(0, 12).map((s) => `${s.position.name} (${s.reason})`).join("; ")}
              {data.n_not_forecast > 12 ? `; and ${data.n_not_forecast - 12} more` : ""}.</p>
          )}

          <h3 className="maint-sub">Spares</h3>
          {data.spares.length === 0 ? (
            <p className="lib-date">No replacement part or critical spare on these positions’ parts lists.</p>
          ) : (
            <div className="maint-scroll"><table className="lib-table">
              <thead><tr><th>Part</th><th>Per failure</th><th>Usable in stock</th><th>Next {shown}</th><th>In {horizon}</th><th>Stock</th></tr></thead>
              <tbody>
                {data.spares.map((s) => (
                  <tr key={s.part.id}>
                    <td>{s.part.part_number} {s.part.name}{s.critical ? <span className="lib-date"> · critical</span> : null}</td>
                    <td>{s.per_job.map((q) => formatNumber(q)).join(" / ")} {s.unit}</td>
                    <td>{formatNumber(s.usable_on_hand)}
                      {s.min_on_hand != null && <span className="lib-date"> (keep {formatNumber(s.min_on_hand)})</span>}</td>
                    <td>≈ {formatNumber(s.per_period[0].mean, { sig: 2 })}
                      {s.per_period[0].p90 > 0 && <span className="lib-date"> (likely up to {formatNumber(s.per_period[0].p90)})</span>}</td>
                    <td>≈ {formatNumber(s.expected, { sig: 2 })} <span className="lib-date">(likely {rangeText(s.interval)})</span></td>
                    <td className={s.short ? "maint-overdue" : "lib-date"}>{spareCover(s, data.period)}</td>
                  </tr>
                ))}
              </tbody>
            </table></div>
          )}
          <ClassStocking data={data} name={name} serviceLevel={stocking.serviceLevel} reviewDays={stocking.reviewDays}
                         onOptions={(o) => setStocking((s) => ({ ...s, ...o }))} onChanged={load} />

          <h3 className="maint-sub">Budget</h3>
          {!budget ? (
            <p className="lib-date">Set the class’s costs above (a failure, a planned replacement) to see what this costs.</p>
          ) : (
            <div className="maint-scroll"><table className="lib-table">
              <thead><tr><th>What</th><th>How many</th><th>Each</th><th>In {horizon}</th></tr></thead>
              <tbody>
                <tr>
                  <td>Failures</td><td>≈ {formatNumber(data.expected)}</td>
                  <td>{money(budget.cost_per_failure, budget.currency)}{budget.basis === "replacement_cost" ? <span className="lib-date"> (replacement cost)</span> : null}</td>
                  <td>≈ {money(budget.failures, budget.currency)} <span className="lib-date">(likely {moneyRange(budget.failures_interval, budget.currency)})</span></td>
                </tr>
                {budget.planned_cost != null && (
                  <tr>
                    <td>Planned replacements due</td><td>{budget.planned_count}</td>
                    <td>{money(budget.planned_cost)}</td><td>{money(budget.planned)}</td>
                  </tr>
                )}
                <tr><td><strong>Total</strong></td><td /><td /><td><strong>≈ {money(budget.expected, budget.currency)}</strong></td></tr>
              </tbody>
            </table></div>
          )}
          {data.notes.map((n) => <p key={n} className="lib-date">{n}</p>)}
        </>
      )}
    </section>
  );
}

// ---- parts and stock -------------------------------------------------------------------

export function MaintenanceParts() {
  const [parts, setParts] = useState(null);
  const [locations, setLocations] = useState([]);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState({ itemClassId: null, manufacturerId: null });
  const [kinds] = useKinds();
  const [error, setError] = useState(null);
  const [view, setView] = useState("list");
  const filtered = !!(filter.itemClassId || filter.manufacturerId);
  const usesKinds = !!(kinds.classes?.length || kinds.makers?.length);
  const load = useCallback(() => {
    listMaintenanceParts(filter).then((d) => setParts(d.parts)).catch((e) => setError(e.message));
  }, [filter]);
  useEffect(() => {
    load();
    listMaintenanceLocations().then((d) => setLocations(d.locations)).catch(() => {});
  }, [load]);
  return (
    <div className="app">
      <SectionHeader section="maintenance" title="Parts" purpose="The parts catalogue, what parts are made of, and what's in stock where."
                  actions={<>
                    <button className="secondary" onClick={() => setModal("bom")}>Import a BOM</button>
                    <button className="secondary" onClick={() => setModal("levels")}>Indenture levels</button>
                  </>}
                  primary={<button onClick={() => setModal("new")}><PlusIcon /> New part</button>} />
      {error && <div className="card error">{error}</div>}
      {parts?.length > 0 && !filtered && <SparesCoverCard parts={parts} />}
      {parts?.length > 0 && (
        <div className="tablebar section-tablebar">
          <span className="count">{`${parts.length} part${parts.length === 1 ? "" : "s"}`}</span>
          <SegmentedControl size="sm" label="Show" value={view} onChange={setView} style={{ flex: "none" }}
                            options={[{ value: "list", label: "List" }, { value: "structure", label: "Structure" }]} />
          <span className="grow" />
          {usesKinds && <KindFilters classes={kinds.classes} makers={kinds.makers} value={filter} onChange={setFilter} />}
        </div>
      )}
      {parts === null ? <div className="card empty">Loading…</div> : parts.length === 0 ? (
        <div className="card empty"><p>{filtered ? "No parts match." : "No parts yet. Add the spares you keep: anodes, filters, bearings; or import a BOM."}</p></div>
      ) : view === "structure" ? <PartsStructure parts={parts} /> : (
        <div className="lib maint-scroll">
          <table className="lib-table">
            <thead><tr><th>Part number</th><th>Part</th><th>On hand</th><th>Where</th><th>Used at</th><th>Used (12 mo)</th><th>Cover</th><th /></tr></thead>
            <tbody>
              {parts.map((pt) => (
                <tr key={pt.id}>
                  <td><Link to={`/maintenance/parts/${pt.id}`}>{pt.part_number}</Link>
                    {pt.superseded_by && <div className="lib-date">superseded by {pt.superseded_by.part_number}</div>}</td>
                  <td>{pt.name}{pt.level && <> <span className="maint-badge">{pt.level}</span></>}
                    <div className="lib-date">{[pt.manufacturer_entry?.name || pt.manufacturer,
                    pt.components?.length > 0 && `${pt.components.length} part${pt.components.length === 1 ? "" : "s"} inside`,
                    pt.item_class?.name, pt.unit_cost != null && `${pt.unit_cost} each`].filter(Boolean).join(" · ")}</div></td>
                  <td>{pt.on_hand} {pt.unit}{pt.low && <span className="maint-overdue"> low</span>}
                    {pt.critical_short && <div className="maint-overdue">critical spare short (keep {pt.critical_min})</div>}</td>
                  <td className="lib-date">{pt.stock.map((st) => `${st.location.name}: ${st.quantity}${st.reorder_point != null ? ` (reorder at ${st.reorder_point})` : ""}`).join("; ") || "—"}</td>
                  <td className="lib-date">{(pt.used_at || []).length === 0 ? "—" : pt.used_at.map((u, i) => (
                    <span key={u.listing_id}>{i > 0 && "; "}
                      <Link to={`/maintenance/positions/${u.position.id}`}>{u.position.name}</Link>
                      {` (${roleLabel(u.role).toLowerCase()}${u.critical ? ", critical" : ""})`}</span>
                  ))}</td>
                  <td>{pt.used_last_year}</td>
                  <td className="lib-date">{pt.months_of_cover != null ? `${pt.months_of_cover} months` : "—"}</td>
                  <td><button className="secondary" onClick={() => setModal({ stock: pt })}>Stock</button>
                    {usesKinds && <> <button className="secondary" onClick={() => setModal({ kind: pt })}>What it is</button></>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {modal === "new" && <NewPartModal kinds={kinds} onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
      {modal?.kind && <PartKindModal part={modal.kind} kinds={kinds} onClose={() => setModal(null)}
                                     onDone={() => { setModal(null); load(); }} />}
      {modal?.stock && <StockModal part={modal.stock} locations={locations} onClose={() => setModal(null)}
                                   onDone={() => { setModal(null); load(); }} />}
      {modal === "bom" && <ImportBomModal onClose={() => setModal(null)} onDone={() => { setModal(null); setView("structure"); load(); }} />}
      {modal === "levels" && <LevelsModal onClose={() => setModal(null)} onDone={() => { setModal(null); load(); }} />}
    </div>
  );
}

// The catalogue as structures (#435): each top assembly with what it's made of, then a
// count of the parts in no structure.
function PartsStructure({ parts }) {
  const { roots, loose } = partsForest(parts);
  return (
    <section className="card">
      {roots.length === 0 ? (
        <p className="lib-date">No part is made of other parts yet. Open a part to add what goes inside it, or import a BOM.</p>
      ) : roots.map((r) => (
        <div key={r.id} className="maint-group"><StructureTree tree={r} /></div>
      ))}
      {loose.length > 0 && roots.length > 0 && (
        <p className="lib-date">{loose.length} part{loose.length === 1 ? " is" : "s are"} in no structure (see List).</p>
      )}
    </section>
  );
}

// Where the spares don't cover the plant: critical spares below the minimum their
// position keeps, positions whose critical replacement part has none in stock, and
// (on request) positions with no parts list yet.
function SparesCoverCard({ parts }) {
  const [cover, setCover] = useState(null);
  const [unlisted, setUnlisted] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => {
    getSparesCover(unlisted).then(setCover).catch((e) => setError(e.message));
  }, [unlisted, parts]);
  if (error) return <div className="card error">{error}</div>;
  if (!cover) return null;
  const bare = cover.without_parts_list || [];
  const line = (v) => (
    <li key={v.id}>
      <Link to={`/maintenance/positions/${v.position.id}`}>{v.position.name}</Link>: {v.part.part_number} {v.part.name}
      <span className="lib-date"> · {v.usable_on_hand} usable, keep {v.min_on_hand}
        {v.use_instead ? ` · use ${v.use_instead.part_number} instead` : ""}</span>
    </li>
  );
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Spares cover</h2>
        <label className="maint-row lib-date" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="checkbox" checked={unlisted} onChange={(e) => setUnlisted(e.target.checked)} />
          Positions with no parts list
        </label>
      </div>
      {cover.no_spare.length > 0 && (
        <>
          <p><strong className="maint-overdue">No spare</strong> for the critical replacement part at:</p>
          <ul className="maint-list">{cover.no_spare.map(line)}</ul>
        </>
      )}
      {cover.short.length > 0 && (
        <>
          <p><strong>Critical spares short</strong></p>
          <ul className="maint-list">{cover.short.map(line)}</ul>
        </>
      )}
      {cover.short.length === 0 && cover.no_spare.length === 0 && (
        <p className="lib-date">Every critical spare is at or above its minimum. Mark spares critical on a position's Parts card.</p>
      )}
      {unlisted && (bare.length === 0 ? <p className="lib-date">Every position has a parts list.</p> : (
        <>
          <p><strong>No parts list</strong> ({bare.length})</p>
          <ul className="maint-list">
            {bare.map((b) => <li key={b.id}><Link to={`/maintenance/positions/${b.id}`}>{b.name}</Link>
              {b.path.length > 0 && <span className="lib-date"> · {b.path.join(" › ")}</span>}</li>)}
          </ul>
        </>
      ))}
    </section>
  );
}

function NewPartModal({ kinds, onClose, onDone }) {
  const [f, setF] = useState({ part_number: "", name: "", manufacturer: "", unit_cost: "", item_class_id: null,
    manufacturer_id: null });
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  return (
    <FormModal title="New part" submitLabel="Add" canSubmit={!!f.part_number.trim() && !!f.name.trim()} onClose={onClose}
               onSubmit={async () => onDone(await createMaintenancePart({ ...f, unit_cost: f.unit_cost === "" ? null : Number(f.unit_cost) }))}>
      <Field label="Part number"><input autoFocus value={f.part_number} onChange={set("part_number")} /></Field>
      <Field label="Name"><input value={f.name} placeholder="e.g. Magnesium anode" onChange={set("name")} /></Field>
      <Field label="Manufacturer (optional)"><input value={f.manufacturer} onChange={set("manufacturer")} /></Field>
      <Field label="Cost each (optional)"><input type="number" inputMode="decimal" min="0" step="any" value={f.unit_cost} onChange={set("unit_cost")} /></Field>
      {kinds.classes?.length > 0 && (
        <Field label="Item class (optional: what kind of thing it is)">
          <ClassPicker classes={kinds.classes} value={f.item_class_id} onChange={(v) => setF({ ...f, item_class_id: v })} />
        </Field>
      )}
      {kinds.makers?.length > 0 && (
        <Field label="Manufacturer in the register (optional)">
          <select value={f.manufacturer_id || ""} onChange={(e) => setF({ ...f, manufacturer_id: e.target.value || null })}>
            <option value="">None</option>
            {kinds.makers.map((mk) => <option key={mk.id} value={mk.id}>{mk.name}</option>)}
          </select>
        </Field>
      )}
    </FormModal>
  );
}

function StockModal({ part, locations, onClose, onDone }) {
  const [loc, setLoc] = useState(part.stock[0]?.location.id || "");
  const [qty, setQty] = useState("");
  const [reorder, setReorder] = useState("");
  return (
    <FormModal title={`Stock: ${part.part_number}`} submitLabel="Save" canSubmit={!!loc && (qty !== "" || reorder !== "")}
               onClose={onClose}
               onSubmit={async () => {
                 if (qty !== "") await adjustMaintenanceStock(part.id, { location_id: loc, delta: Number(qty), reason: Number(qty) > 0 ? "received" : "issued" });
                 if (reorder !== "") await setMaintenanceReorder(part.id, { location_id: loc, reorder_point: Number(reorder) });
                 onDone();
               }}>
      <Field label="Location">
        <select value={loc} onChange={(e) => setLoc(e.target.value)}>
          <option value="">{locations.length ? "Choose…" : "Add a location first"}</option>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.parent ? `${l.parent.name} › ` : ""}{l.name}</option>)}
        </select>
      </Field>
      <Field label="Received (+) or issued (−)"><input type="number" step="any" value={qty} placeholder="e.g. 3 or -1" onChange={(e) => setQty(e.target.value)} /></Field>
      <Field label="Reorder at (optional)"><input type="number" inputMode="decimal" min="0" step="any" value={reorder} onChange={(e) => setReorder(e.target.value)} /></Field>
    </FormModal>
  );
}
