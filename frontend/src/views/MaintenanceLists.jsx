import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  createMaintenanceItem,
  createMaintenanceLocation,
  fitClassModel,
  getClassEconomics,
  getClassForecast,
  getClassLifeData,
  getPositionClass,
  setClassCosts,
  setClassReplacementCost,
  getMaintenanceLocation,
  getMaintenanceOverview,
  getPositionClasses,
  adjustMaintenanceStock,
  getSparesCover,
  listMaintenanceParts,
  setMaintenanceReorder,
  listMaintenanceLocations,
  listMaintenanceWorkOrders,
  placeMaintenanceItem,
  updateMaintenanceLocation,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import MaintenancePhotos from "../components/MaintenancePhotos.jsx";
import { PlusIcon, RowLink, rowOpen } from "../components/LibRows.jsx";
import {
  DocumentsCard, Field, FormModal, LifeTable, Proposals, flatten, fmtDate,
} from "../components/MaintenanceParts.jsx";
import { NewPositionModal } from "./MaintenanceHome.jsx";
import { costText, costValue } from "../maintenanceFields.js";
import { roleLabel } from "../maintenanceSpares.js";
import { countsText, inheritedText } from "../maintenanceLocations.js";
import { openWorkPath } from "../maintenanceAssets.js";
import { subjectBadge } from "../maintenanceSubjects.js";
import { TasksCard, WorkOrdersCard } from "../components/MaintenanceTasks.jsx";
import {
  ItemClassesSection, KindFilters, PartKindModal, useKinds,
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
import { tooLong } from "../maintenanceText.js";
import { PageTitle } from "../components/usePageTitle.js";
import LoadFailed from "../components/LoadFailed.jsx";
import { isNotFound } from "../components/loadFailed.js";
import { explorerPath } from "../assetTree.js";
import { DeleteTreeModal } from "../components/DeleteTree.jsx";
import { NewPartModal } from "../components/PartForms.jsx";
import { partsInBranch } from "../explorerTabs.js";
import { EXPLORER_LABEL } from "../navigation.js";
import { itemTreePath, productPath } from "../products.js";

const crumbs = [{ label: "Assets", to: "/asset-register" }];

// ---- items -------------------------------------------------------------------------------

// A new item: a spare on the shelf, a unit back from repair, anything not
// fitted yet. Fitting one to a position (from the position's page) makes it
// there and then; this is for the rest. `locations`: where it can be put.
export function NewItemModal({ locations, locationId = null, onClose, onDone }) {
  const [name, setName] = useState("");
  const [serial, setSerial] = useState("");
  const [where, setWhere] = useState(locationId || "");
  return (
    <FormModal title="New item" submitLabel="Create"
               canSubmit={!!name.trim() && !tooLong(name) && !tooLong(serial)} onClose={onClose}
               onSubmit={async () => {
                 const item = await createMaintenanceItem({ name, serial });
                 if (where) await placeMaintenanceItem(item.id, where);
                 onDone(item);
               }}>
      <p className="lib-date">An item is one physical thing, with its own history. To fit a new one, open the
        position it goes in and fit it there instead.</p>
      <Field label="Name" text={name}>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Spare seal kit, Motor M-118" />
      </Field>
      <Field label="Serial number (optional)" text={serial}>
        <input value={serial} onChange={(e) => setSerial(e.target.value)} placeholder="e.g. SK-0042" />
      </Field>
      <Field label="Where it is">
        <select value={where} onChange={(e) => setWhere(e.target.value)}>
          <option value="">Nowhere yet (no home)</option>
          {locations.map((l) => <option key={l.id} value={l.id}>{l.parent ? `${l.parent.name} › ` : ""}{l.name}</option>)}
        </select>
      </Field>
    </FormModal>
  );
}

// ---- locations -------------------------------------------------------------------------

// A new location. `asset`: a new asset, a top-level place (no "Inside" to pick).
// designOf: a product's id (its page's Locations): a location in its physical
// layout (one at the top of it is design_of the product; one inside another
// of its locations is the product's too).
export function NewLocationModal({ locations, parentId = null, asset = false, designOf = null, layoutName = "", onClose, onDone }) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState(parentId || "");
  const top = (!asset && parent) || null;
  return (
    <FormModal title={asset ? "New asset" : "New location"} submitLabel="Create" pendingLabel="Adding…"
               canSubmit={!!name.trim() && !tooLong(name)} onClose={onClose}
               onSubmit={async () => onDone(await createMaintenanceLocation({
                 name, parent_id: top, ...(designOf && !top ? { design_of: designOf } : {}),
               }))}>
      {designOf && (
        <p className="lib-date">A part of the product's physical layout (an arm, a bay). Place its positions there;
          items built from it carry a copy.</p>
      )}
      {asset && (
        <p className="lib-date">An asset is a place you look after: a house, a site, a plant. Add the rooms or
          areas inside it from its page, then say where each position is.</p>
      )}
      <Field label="Name" text={name}>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)}
               placeholder={asset ? "e.g. 12 Smith Street, North mine site" : designOf ? "e.g. Forward left arm, Battery bay" : "e.g. Laundry, Garage, Store A"} />
      </Field>
      {!asset && (
        <Field label="Inside">
          <select value={parent} onChange={(e) => setParent(e.target.value)}>
            <option value="">{designOf ? `None (the top of ${layoutName || "the product"}'s layout)` : "None (top level: an asset)"}</option>
            {locations.map((l) => <option key={l.id} value={l.id}>{l.parent ? `${l.parent.name} › ` : ""}{l.name}</option>)}
          </select>
        </Field>
      )}
    </FormModal>
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
  // A product's design location (or one a built item carries): its own layout's locations.
  const owner = loc?.design_of?.id || loc?.carried_by?.id || null;
  useEffect(() => {
    if (loc === null) return;
    listMaintenanceLocations(owner).then((d) => setAll(d.locations)).catch(() => {});
  }, [owner, loc === null]); // eslint-disable-line react-hooks/exhaustive-deps
  // A place you look after (not a product's design layout, nor one an item carries) holds
  // positions: adding one here is its main action, and the new position is at this place.
  const canHoldPositions = !!loc && !loc.design_of && !loc.carried_by;
  const addPosition = () => setModal("position");
  if (error && !loc) return <div className="app"><LoadFailed header error={error} notFound="Location not found." to={explorerPath("locations")} label={`Open the ${EXPLORER_LABEL}`} /></div>;
  if (!loc) return <div className="app"><div className="card empty">Loading…</div></div>;
  // The header leaves out the open work: it's its own card below, the whole area's
  // (positions, items there now and the place itself), not only the positions'.
  return (
    <div className="app">
      <PageTitle name={loc?.name} />
      <PageHeader
        crumbs={[...crumbs, ...loc.path.map((a) => ({ label: a.name, to: `/asset-register/locations/${a.id}` }))]}
        title={loc.name} id={loc.id}
        meta={[loc.description, countsText({ ...loc.counts, open_work_orders: 0 })].filter(Boolean).join(" · ")
          || (loc.path.length ? "Location" : "Asset")}
        actions={<button className="secondary" onClick={() => setModal("child")}><PlusIcon /> Location inside</button>}
        primary={canHoldPositions
          ? <button onClick={() => setModal("position")}><PlusIcon /> Add a position here</button>
          : <button onClick={() => setModal("rename")}>Rename</button>}
        menu={(
          <>
            {canHoldPositions && <button className="ovm-item" onClick={() => setModal("rename")}>Rename…</button>}
            <button className="ovm-item danger" onClick={() => setModal("delete")}>Delete…</button>
          </>
        )}
      />
      {loc.design_of && (
        <p className="card lib-date">
          Part of the physical layout of the product{" "}
          <Link to={`${productPath(loc.design_of.id)}?arrange=locations&sel=${encodeURIComponent(loc.id)}`}>{loc.design_of.name}</Link>:
          where its positions sit. It's a design, so nothing is stored or worked on here; items built from it carry a copy.
        </p>
      )}
      {loc.carried_by && (
        <p className="card lib-date">
          Carried by <Link to={itemTreePath(loc.carried_by.id)}>{loc.carried_by.name}</Link> (a copy of its product's
          layout): it is wherever the item is kept, and moves with it.
        </p>
      )}
      {loc.children.length > 0 && (
        <section className="card">
          <div className="maint-head"><h2>Inside it</h2></div>
          <ul className="maint-list">{loc.children.map((c) => (
            <li key={c.id}><Link to={`/asset-register/locations/${c.id}`}>{c.name}</Link>
              {(c.positions > 0 || c.items > 0) && (
                <span className="lib-date"> · {[c.positions && `${c.positions} position${c.positions === 1 ? "" : "s"}`,
                  c.items && `${c.items} item${c.items === 1 ? "" : "s"} placed`].filter(Boolean).join(", ")}</span>
              )}</li>
          ))}</ul>
        </section>
      )}
      {!loc.design_of && <OpenWorkHere loc={loc} />}
      <LocationPositions loc={loc} onAdd={canHoldPositions ? addPosition : null} />
      {!loc.design_of && <section className="card">
        <div className="maint-head"><h2>Items placed here</h2></div>
        {loc.items.length === 0 ? (
          <p className="lib-date">No spares or items away from their positions here. (Fitted items are where their
            positions are; place an item that isn't fitted from its page.)</p>
        ) : (
          <ul className="maint-list">
            {loc.items.map((i) => (
              <li key={i.id}><Link to={`/asset-register/items/${i.id}`}>{i.name}</Link>
                <span className="lib-date">
                  {i.location.id !== loc.id && <> · in <Link to={`/asset-register/locations/${i.location.id}`}>{i.location.name}</Link></>}
                  {" "}· since {fmtDate(i.since)}</span></li>
            ))}
          </ul>
        )}
      </section>}
      {!loc.design_of && <TasksCard subject={{ kind: "location", id: loc.id, name: loc.name }} tasks={loc.tasks || []} onChanged={refresh}
                 emptyText={"No tasks on this place. Add a round or walkdown, an Ex (hazardous-area) inspection, or a "
                   + "building or area check: it raises one work order here, and can list every position here to check."} />}
      {(loc.work_orders || []).length > 0 && <WorkOrdersCard workOrders={loc.work_orders} />}
      <ConditionsCard target={{ id: loc.id, name: loc.name, kind: "Location" }} view={loc} onChanged={refresh} />
      <MaintenancePhotos targetId={loc.id} targetKind="Location" targetName={loc.name} photos={loc.photos} onChanged={refresh} />
      {loc.coordinates && <p className="lib-date">Coordinates: {loc.coordinates.lat}, {loc.coordinates.lon}</p>}
      {modal === "child" && <NewLocationModal locations={all} parentId={loc.id} onClose={() => setModal(null)}
                                              onDone={(l) => { setModal(null); navigate(`/asset-register/locations/${l.id}`); }} />}
      {modal === "position" && (
        <NewPositionFromPlace loc={loc} locations={all} onClose={() => setModal(null)}
                              onCreated={() => { setModal(null); refresh(); }} />
      )}
      {modal === "rename" && <RenameLocation loc={loc} onClose={() => setModal(null)} onDone={(d) => { setLoc(d); setModal(null); }} />}
      {modal === "delete" && (
        // Gone with the places inside and the positions there: the Explorer shows the toast with Undo.
        <DeleteTreeModal kind="location" id={loc.id} name={loc.name} onClose={() => setModal(null)}
                         onDone={(answer, done) => navigate(explorerPath("locations"), { state: { deleted: done } })} />
      )}
    </div>
  );
}

// The open work orders in a place's area: on the positions there, the items there
// now and the place itself (or a place inside it). The first few, and a link to all.
const OPEN_HERE = 8;
function OpenWorkHere({ loc }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(null);
  useEffect(() => {
    listMaintenanceWorkOrders({ status: "open", locationId: loc.id })
      .then((d) => setOpen(d.work_orders)).catch(() => setOpen([]));
  }, [loc]);
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Open work here</h2>
        {open?.length > OPEN_HERE && <Link to={openWorkPath(loc.id)} className="lib-date">All {open.length}</Link>}
      </div>
      {open === null ? <p className="lib-date">Loading…</p> : open.length === 0 ? (
        <p className="lib-date">No open work orders here.</p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>#</th><th>Title</th><th>On</th><th>Due</th></tr></thead>
          <tbody>
            {open.slice(0, OPEN_HERE).map((w) => (
              <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, `/maintenance/work-orders/${w.id}`)}>
                <td>{w.number}</td>
                <td><RowLink to={`/maintenance/work-orders/${w.id}`}>{w.title}</RowLink></td>
                <td>{w.subject?.name}{subjectBadge(w.subject) && <> <span className="maint-badge">{subjectBadge(w.subject)}</span></>}
                  {w.location && ![loc.id, w.subject?.id].includes(w.location.id) && <div className="lib-date">{w.location.name}</div>}</td>
                <td className="lib-date">{fmtDate(w.due)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

// The positions at a location (set on them or inherited, here or inside it), by the
// system each belongs to, with what's fitted to each.
function LocationPositions({ loc, onAdd = null }) {
  return (
    <section className="card">
      <div className="maint-head">
        <h2>Positions here</h2>
        {onAdd && loc.systems.length > 0 && (
          <button type="button" className="secondary sm" onClick={onAdd}><PlusIcon /> Add a position here</button>
        )}
      </div>
      {loc.systems.length === 0 ? (
        <div className="maint-empty-add">
          <p className="lib-date">No positions here yet. Add one here (a pump, a boiler, a pump set with its motor
            inside), or set an existing position's location on its page: the positions inside it follow, and so does
            whatever is fitted.</p>
          {onAdd && <button type="button" onClick={onAdd}><PlusIcon /> Add a position here</button>}
        </div>
      ) : loc.systems.map((g) => (
        <div key={g.system.id} className="maint-group">
          <h3>
            <Link to={`/asset-register/${g.system.kind === "Item" ? "items" : "positions"}/${g.system.id}`}>{g.system.name}</Link>
            <span className="lib-date"> · {g.count} here</span>
          </h3>
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Position</th><th>Where</th><th>Fitted</th><th>Work</th></tr></thead>
            <tbody>
              {g.positions.map((r) => (
                <tr key={r.id}>
                  <td><Link to={`/asset-register/positions/${r.id}`}>{r.path}</Link>{r.tag && <span className="lib-date"> · {r.tag}</span>}</td>
                  <td className="lib-date">
                    {r.location.id !== loc.id && <><Link to={`/asset-register/locations/${r.location.id}`}>{r.location.name}</Link> · </>}
                    {r.direct ? "set here" : inheritedText({ inherited: true, inherited_from: r.inherited_from })}
                  </td>
                  <td>{r.item ? <Link to={`/asset-register/items/${r.item.id}`}>{r.item.name}</Link> : <span className="lib-date">nothing fitted</span>}</td>
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

// New position at a place: the shared form, its Location filled with this place.
function NewPositionFromPlace({ loc, locations, onClose, onCreated }) {
  const [positions, setPositions] = useState([]);
  useEffect(() => {
    getMaintenanceOverview().then((d) => setPositions(flatten(d.tree))).catch(() => {});
  }, []);
  // The place itself is always a choice, even before its layout's list has come back.
  const places = locations.some((l) => l.id === loc.id) ? locations : [...locations, { id: loc.id, name: loc.name }];
  return (
    <NewPositionModal positions={positions} locations={places} locationId={loc.id}
                      onClose={onClose} onCreated={onCreated} />
  );
}

function RenameLocation({ loc, onClose, onDone }) {
  const [name, setName] = useState(loc.name);
  const [description, setDescription] = useState(loc.description || "");
  return (
    <FormModal title="Rename location" submitLabel="Save" canSubmit={!!name.trim() && !tooLong(name)} onClose={onClose}
               onSubmit={async () => onDone(await updateMaintenanceLocation(loc.id, { name, description }))}>
      <Field label="Name" text={name}><input autoFocus value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Description"><input value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
    </FormModal>
  );
}

// ---- position classes ----------------------------------------------------------------------

// The Explorer's Classes tab: the position classes used at the row picked and
// inside it (how many of its positions have each), or with "Show all classes"
// every class in the register, with the item classes and conditions (the
// taxonomy). A class picked (?class=) opens its panel: its model, costs,
// forecast and pooled life data, as the Classes page had them.
// `here`: [{position_class, here}] for the branch (explorerTabs.js
// classesInBranch); `scopeName`: the row's name.
export function ClassesPanel({ here = [], scopeName = "", all = false, onAll, open = null, onOpen }) {
  const [classes, setClasses] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [classError, setClassError] = useState(null);
  useEffect(() => {
    getPositionClasses().then((d) => setClasses(d.classes)).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    setClassError(null);
    if (!open) return;
    setData(null);
    getClassLifeData(open).then(setData).catch((e) => setClassError(e.message));
  }, [open]);
  const byName = new Map((classes || []).map((c) => [c.position_class, c]));
  const rows = all ? (classes || []).map((c) => ({ ...c, here: here.find((h) => h.position_class === c.position_class)?.here || 0 }))
    : here.map((h) => ({ positions: 0, fitments: 0, failures: 0, ...byName.get(h.position_class), ...h }));
  const missing = open && isNotFound(classError);
  return (
    <div className="td-tab-page">
      <div className="tablebar section-tablebar">
        <span className="count">{all ? "Every class in the register" : `Classes used at ${scopeName || "this row"} and inside it`}</span>
        <span className="grow" />
        <label className="maint-row lib-date td-tab-check" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="checkbox" checked={all} onChange={(e) => onAll?.(e.target.checked)} /> Show all classes
        </label>
      </div>
      <p className="lib-date">Position classes group like positions by their duty, so their items' lives can be compared and pooled
        into one model. Item classes (optional) say what kind of thing each item is; conditions (optional), what things are exposed to.</p>
      {error && <div className="card error">{error}</div>}
      <h3 className="maint-section">Position classes</h3>
      {classes === null ? <div className="card empty">Loading…</div> : rows.length === 0 ? (
        <div className="card empty"><p>{all || !classes.length
          ? "No classes yet. Give positions a class (e.g. “Pool pump”) when you create or edit them."
          : `No position inside ${scopeName || "this row"} has a class yet. Give positions a class when you create or edit them, or show all classes.`}</p></div>
      ) : (
        <div className="lib maint-scroll">
          <table className="lib-table">
            <thead><tr><th>Class</th><th className="num">Here</th><th className="num">Positions</th><th className="num">Fitments</th><th className="num">Failures</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.position_class} className="lib-row" onClick={() => onOpen?.(c.position_class)}
                    aria-current={c.position_class === open ? "true" : undefined}>
                  <td><button type="button" className="link lib-name" onClick={(e) => { e.stopPropagation(); onOpen?.(c.position_class); }}>
                    {c.position_class}</button></td>
                  <td className="num" data-label="Here">{c.here}</td>
                  <td className="num" data-label="Positions">{c.positions}</td>
                  <td className="num" data-label="Fitments">{c.fitments}</td>
                  <td className="num" data-label="Failures">{c.failures}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {missing && (
        <div className="card error">Class not found: {open}. <button type="button" className="link" onClick={() => onOpen?.(null)}>Close it</button></div>
      )}
      {classError && !missing && <div className="card error">{classError}</div>}
      {open && !missing && (
        <>
          <div className="maint-row"><button type="button" className="secondary sm" onClick={() => onOpen?.(null)}>Close {open}</button></div>
          <ClassPanel name={open} onChanged={() => getPositionClasses().then((d) => setClasses(d.classes))} />
          <section className="card">
            <div className="maint-head">
              <h2>{open}: pooled life data</h2>
              {data && <span className="lib-date">{data.failures} failures · {data.suspensions} suspensions
                {data.uncertain ? ` · ${data.uncertain} with dates known only roughly (fitted as ranges)` : ""}</span>}
            </div>
            {data === null ? <p className="lib-date">Loading…</p> : <div className="maint-scroll"><LifeTable rows={data.rows} showPosition /></div>}
          </section>
        </>
      )}
      {all ? (
        <>
          <h3 className="maint-section">What kind of thing</h3>
          <ItemClassesSection />
          <h3 className="maint-section">What things are exposed to</h3>
          <ConditionsSection />
        </>
      ) : (
        <p className="lib-date">Item classes and conditions are the whole register's:{" "}
          <button type="button" className="link" onClick={() => onAll?.(true)}>show all classes</button> to manage them.</p>
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
            <Link to={`/models/m/${model.model_id}`}>Open the model</Link>
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
              data.n_forecast > 0 && { label: "Likely range (90%)", value: rangeText(data.interval), hint: "P5–P95, counting replacements that fail again" },
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
                    array: data.per_period.map((r) => Math.max(0, r.high - r.expected)),
                    arrayminus: data.per_period.map((r) => Math.max(0, r.expected - r.low)),
                  },
                  customdata: data.per_period.map((r, i) => [labels[i], r.low, r.high]),
                  hovertemplate: "%{customdata[0]}: %{y:.2f} expected (likely %{customdata[1]}–%{customdata[2]})<extra></extra>",
                }]}
                layout={{
                  height: 260, bargap: 0.35,
                  xaxis: { title: { text: `${shown[0].toUpperCase()}${shown.slice(1)} starting` }, type: "date" },
                  yaxis: { title: { text: `Expected failures a ${shown}` }, rangemode: "tozero" },
                }}
                download={`${name} — failure forecast`}
              />
              <p className="rs-note">Whiskers: each {shown}’s likely range (90%).</p>
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
                      <td><Link to={`/asset-register/positions/${r.position.id}`}>{r.position.name}</Link></td>
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

// The Explorer's Parts and stock tab: the parts kept in stock at the row
// picked and inside it (a location's stores) and those on the parts lists of
// its positions; with "Show all parts", the whole catalogue and the spares
// cover. List or Structure (what each part is made of). On a product's design
// (`design`) it's the tab "Parts": the parts lists, with no stock.
// `branch`: explorerTabs.js branchOf for the row; `scopeName`: its name.
export function PartsPanel({ branch, scopeName = "", all = false, onAll, design = false, show = "list", onShow }) {
  const [parts, setParts] = useState(null);
  const [locations, setLocations] = useState([]);
  const [modal, setModal] = useState(null);
  const [filter, setFilter] = useState({ itemClassId: null, manufacturerId: null });
  const [kinds] = useKinds();
  const [error, setError] = useState(null);
  const view = show === "structure" ? "structure" : "list";
  const filtered = !!(filter.itemClassId || filter.manufacturerId);
  const usesKinds = !!(kinds.classes?.length || kinds.makers?.length);
  const load = useCallback(() => {
    listMaintenanceParts(filter).then((d) => setParts(d.parts)).catch((e) => setError(e.message));
  }, [filter]);
  useEffect(() => {
    load();
    if (!design) listMaintenanceLocations().then((d) => setLocations(d.locations)).catch(() => {});
  }, [load, design]);
  const shown = parts === null ? null : all || !branch ? parts : partsInBranch(parts, branch, { design });
  const where = all ? "in the catalogue" : `at ${scopeName || "this row"} and inside it`;
  return (
    <div className="td-tab-page">
      <div className="tablebar section-tablebar">
        <span className="count">{shown === null ? (design ? "Parts" : "Parts and stock")
          : `${shown.length} part${shown.length === 1 ? "" : "s"} ${where}`}</span>
        <SegmentedControl size="sm" label="Show" value={view} onChange={(v) => onShow?.(v)} style={{ flex: "none" }}
                          options={[{ value: "list", label: "List" }, { value: "structure", label: "Structure" }]} />
        <span className="grow" />
        <label className="maint-row lib-date td-tab-check" style={{ marginTop: 0, gap: "0.4rem" }}>
          <input type="checkbox" checked={all} onChange={(e) => onAll?.(e.target.checked)} /> Show all parts
        </label>
      </div>
      <div className="maint-row td-tab-actions">
        <button className="secondary sm" onClick={() => setModal("bom")}>Import a BOM</button>
        <button className="secondary sm" onClick={() => setModal("levels")}>Indenture levels</button>
        {usesKinds && <KindFilters classes={kinds.classes} makers={kinds.makers} value={filter} onChange={setFilter} />}
        <span className="grow" />
        <button className="sm" onClick={() => setModal("new")}><PlusIcon /> New part</button>
      </div>
      {error && <div className="card error">{error}</div>}
      {!design && all && parts?.length > 0 && !filtered && <SparesCoverCard parts={parts} />}
      {shown === null ? <div className="card empty">Loading…</div> : shown.length === 0 ? (
        <div className="card empty"><p>{filtered ? "No parts match."
          : parts.length === 0 ? (design ? "No parts yet. Add the parts that go into it, or import a BOM."
            : "No parts yet. Add the spares you keep: anodes, filters, bearings; or import a BOM.")
          : design ? `No part is on a parts list inside ${scopeName || "this row"} yet. Add parts to a position's parts list on its page, or show all parts.`
          : `No parts are kept or used at ${scopeName || "this row"} or inside it. Show all parts to see the catalogue.`}</p></div>
      ) : view === "structure" ? <PartsStructure parts={shown} /> : (
        <div className="lib maint-scroll">
          <table className="lib-table">
            <thead><tr><th>Part number</th><th>Part</th>{!design && <><th>On hand</th><th>Where</th></>}<th>Used at</th>
              {!design && <><th>Used (12 mo)</th><th>Cover</th></>}<th /></tr></thead>
            <tbody>
              {shown.map((pt) => (
                <tr key={pt.id}>
                  <td><Link to={`/asset-register/parts/${pt.id}`}>{pt.part_number}</Link>
                    {pt.superseded_by && <div className="lib-date">superseded by {pt.superseded_by.part_number}</div>}</td>
                  <td>{pt.name}{pt.level && <> <span className="maint-badge">{pt.level}</span></>}
                    <div className="lib-date">{[pt.manufacturer_entry?.name || pt.manufacturer,
                    pt.components?.length > 0 && `${pt.components.length} part${pt.components.length === 1 ? "" : "s"} inside`,
                    pt.item_class?.name, pt.unit_cost != null && `${pt.unit_cost} each`].filter(Boolean).join(" · ")}</div></td>
                  {!design && (
                    <>
                      <td>{pt.on_hand} {pt.unit}{pt.low && <span className="maint-overdue"> low</span>}
                        {pt.critical_short && <div className="maint-overdue">critical spare short (keep {pt.critical_min})</div>}</td>
                      <td className="lib-date">{pt.stock.map((st) => `${st.location.name}: ${st.quantity}${st.reorder_point != null ? ` (reorder at ${st.reorder_point})` : ""}`).join("; ") || "—"}</td>
                    </>
                  )}
                  <td className="lib-date">{(pt.used_at || []).length === 0 ? "—" : pt.used_at.map((u, i) => (
                    <span key={u.listing_id}>{i > 0 && "; "}
                      <Link to={`/asset-register/positions/${u.position.id}`}>{u.position.name}</Link>
                      {` (${roleLabel(u.role).toLowerCase()}${u.critical ? ", critical" : ""})`}</span>
                  ))}</td>
                  {!design && (
                    <>
                      <td>{pt.used_last_year}</td>
                      <td className="lib-date">{pt.months_of_cover != null ? `${pt.months_of_cover} months` : "—"}</td>
                    </>
                  )}
                  <td>{!design && <button className="secondary sm" onClick={() => setModal({ stock: pt })}>Stock</button>}
                    {usesKinds && <> <button className="secondary sm" onClick={() => setModal({ kind: pt })}>What it is</button></>}</td>
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
      {modal === "bom" && <ImportBomModal onClose={() => setModal(null)} onDone={() => { setModal(null); onShow?.("structure"); load(); }} />}
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
      <Link to={`/asset-register/positions/${v.position.id}`}>{v.position.name}</Link>: {v.part.part_number} {v.part.name}
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
            {bare.map((b) => <li key={b.id}><Link to={`/asset-register/positions/${b.id}`}>{b.name}</Link>
              {b.path.length > 0 && <span className="lib-date"> · {b.path.join(" › ")}</span>}</li>)}
          </ul>
        </>
      ))}
    </section>
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
