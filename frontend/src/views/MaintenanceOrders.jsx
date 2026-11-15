import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  generateWorkOrders,
  getMaintenanceOverview,
  getMaintenanceSettings,
  listDueTasks,
  listMaintenanceLocations,
  listMaintenanceWorkOrders,
  raisePackageVisit,
  setMaintenanceSettings,
} from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import NewWorkOrderModal from "../components/NewWorkOrderModal.jsx";
import Select from "../components/Select.jsx";
import Tabs, { panelId, tabId } from "../components/ui/Tabs.jsx";
import { PlusIcon, RowLink, rowOpen } from "../components/LibRows.jsx";
import { DueChip, LocationPicker, Proposals, flatten, fmtDate } from "../components/MaintenanceParts.jsx";
import { ImportModal, NewPositionModal, SubjectCell, TimeZoneNudge } from "./MaintenanceHome.jsx";
import {
  DUE_WINDOWS, ORDER_TABS, createDetail, createLabel, createPlan, daysLate, doneText, dueSearchText, dueWindow, groupDue,
  inArea, lateText, linesText, orderKind, orderTab, ordersSummary, packagePath, splitOpen, workOrderPath,
} from "../maintenanceOrders.js";
import { ORDERS_LABEL } from "../navigation.js";
import "./Maintenance.css";

const HELP = { guide: "maintenance-work-orders" };

const KINDS = [
  { value: "", label: "Every kind" },
  { value: "task", label: "From a task" },
  { value: "package", label: "From a package" },
  { value: "hand", label: "Added by hand" },
];

// How many closed work orders a search shows at once (the newest first).
const CLOSED_LIMIT = 200;

// Maintenance › Orders: the open work orders (overdue first), what's due soon
// (grouped by package, with "Create N work orders"), and the closed ones.
export default function MaintenanceOrders() {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = orderTab(params.get("tab"));
  const horizon = dueWindow(params.get("days"));
  const locationId = params.get("location") || "";

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // "position" | "import" | "wo"
  const [due, setDue] = useState(null);
  const [locations, setLocations] = useState(null);
  const [inArea, setInArea] = useState(null);
  const [digest, setDigest] = useState(null);

  const refresh = useCallback(() => {
    getMaintenanceOverview().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);
  useEffect(() => {
    setDue(null);
    listDueTasks(horizon).then((d) => setDue(d.due || [])).catch((e) => setError(e.message));
  }, [horizon, data]);
  useEffect(() => {
    listMaintenanceLocations().then((d) => setLocations(d.locations || [])).catch(() => setLocations([]));
    getMaintenanceSettings().then((s) => setDigest(s.digest)).catch(() => {});
  }, []);
  useEffect(() => {
    setInArea(null);
    if (!locationId) return;
    listMaintenanceWorkOrders({ status: "open", locationId })
      .then((d) => setInArea(d.work_orders)).catch((e) => setError(e.message));
  }, [locationId, data]);

  // One query key changed, the others kept (the tab, the window, the area).
  const setParam = (key, value) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const toggleDigest = async (on) => {
    setDigest(on);
    await setMaintenanceSettings({ digest: on }).catch(() => setDigest(!on));
  };

  const positions = flatten(data?.tree);
  const openWork = locationId ? inArea : data?.open_work_orders;

  return (
    <div className="app">
      <SectionHeader
        section="maintenance"
        title={ORDERS_LABEL}
        purpose="Work orders raised by your tasks and packages, and the ones added by hand."
        help={HELP}
        primary={data?.tree?.length > 0 ? <button onClick={() => setModal("wo")}><PlusIcon /> New work order</button> : null}
        actions={<button className="secondary" onClick={() => setModal("import")}>Import from a spreadsheet</button>}
      />
      {error && <div className="card error">{error}</div>}
      {data && <TimeZoneNudge zone={data.time_zone} onSet={refresh} />}
      {data === null ? (
        <div className="card empty">Loading…</div>
      ) : data.tree.length === 0 ? (
        <div className="card empty">
          <h2>Nothing here yet</h2>
          <p>
            Add a position by hand, or build the tree on an asset in <Link to="/asset-register">Assets</Link>, where
            each position's RCM gives it its tasks.
          </p>
          <div className="maint-row" style={{ justifyContent: "center", marginTop: "1rem" }}>
            <button onClick={() => setModal("position")}><PlusIcon /> New position</button>
          </div>
        </div>
      ) : (
        <>
          <Proposals proposals={data.proposals} onDecided={refresh} />
          <p className="maint-answer">
            {ordersSummary({ open: data.open_work_orders || [], due, horizon, today: data.today })}
          </p>
          <Tabs tabs={ORDER_TABS} value={tab} onChange={(id) => setParam("tab", id === "open" ? "" : id)}
                label="Work orders" idPrefix="orders" />
          <div role="tabpanel" id={panelId("orders")} aria-labelledby={tabId("orders", tab)}>
            {tab === "open" && (
              <OpenTab rows={openWork} today={data.today} locations={locations} locationId={locationId}
                       onLocation={(v) => setParam("location", v)} navigate={navigate} />
            )}
            {tab === "due" && (
              <DueTab rows={due} horizon={horizon} onHorizon={(d) => setParam("days", d === 30 ? "" : String(d))}
                      locations={locations} locationId={locationId} onLocation={(v) => setParam("location", v)}
                      onCreated={refresh} onError={setError} />
            )}
            {tab === "closed" && <ClosedTab navigate={navigate} />}
          </div>

          {digest !== null && (
            <label className="maint-row lib-date" style={{ gap: "0.5rem" }}>
              <input type="checkbox" checked={digest} onChange={(e) => toggleDigest(e.target.checked)} />
              Email me when new work orders are raised for tasks coming due
            </label>
          )}
        </>
      )}

      {modal === "position" && (
        <NewPositionModal
          positions={positions}
          onClose={() => setModal(null)}
          onCreated={(p) => navigate(`/asset-register/positions/${p.id}`)}
        />
      )}
      {modal === "wo" && (
        <NewWorkOrderModal positions={positions} onClose={() => setModal(null)}
                           onDone={(wo) => navigate(workOrderPath(wo.id))} />
      )}
      {modal === "import" && <ImportModal onClose={() => setModal(null)} onDone={() => { setModal(null); refresh(); }} />}
    </div>
  );
}

// Open: the overdue ones first (only when something is late), then the rest by due date.
function OpenTab({ rows, today, locations, locationId, onLocation, navigate }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const shown = useMemo(() => (rows || []).filter((w) =>
    (!kind || orderKind(w) === kind)
    && matches(query, String(w.number), `#${w.number}`, w.title, w.subject?.name, w.location?.name, w.trade, w.package?.name)),
  [rows, query, kind]);
  const { overdue, open } = splitOpen(shown, today);
  return (
    <section className="card">
      <div className="tablebar section-tablebar maint-filters">
        <span className="count">
          {rows == null ? "Loading…" : shown.length === rows.length
            ? `${rows.length} open` : `${shown.length} of ${rows.length} open`}
        </span>
        <span className="grow" />
        {locations?.length > 0 && (
          <label className="maint-row lib-date" style={{ marginTop: 0, gap: "0.5rem" }}>
            In
            <LocationPicker locations={locations} value={locationId} emptyLabel="Every location" onChange={onLocation} />
          </label>
        )}
        <Select className="section-type-filter" ariaLabel="Kind" value={kind} onChange={setKind} options={KINDS} />
        <ListSearch value={query} onChange={setQuery} placeholder="Search open work orders…" />
      </div>
      {rows == null ? null : rows.length === 0 ? (
        <p className="lib-date">{locationId ? "None open there." : "None open."}</p>
      ) : shown.length === 0 ? (
        <p className="lib-date">Nothing open matches.</p>
      ) : (
        <>
          {overdue.length > 0 && (
            <>
              <h3 className="maint-subhead maint-overdue">Overdue ({overdue.length})</h3>
              <OpenTable rows={overdue} today={today} navigate={navigate} />
            </>
          )}
          {open.length > 0 && (
            <>
              {overdue.length > 0 && <h3 className="maint-subhead">Open ({open.length})</h3>}
              <OpenTable rows={open} today={today} navigate={navigate} />
            </>
          )}
        </>
      )}
    </section>
  );
}

function OpenTable({ rows, today, navigate }) {
  return (
    <div className="maint-scroll"><table className="lib-table">
      <thead><tr><th>#</th><th>Title</th><th>On</th><th>Location</th><th>Trade</th><th>Due</th><th>Lines</th></tr></thead>
      <tbody>
        {rows.map((w) => {
          const late = daysLate(w, today);
          return (
            <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, workOrderPath(w.id))}>
              <td>{w.number}</td>
              <td>
                <RowLink to={workOrderPath(w.id)}>{w.title}</RowLink>
                {w.under_warranty && <> <span className="maint-badge">warranty</span></>}
                {w.package && <div className="lib-date">{w.package.name}</div>}
              </td>
              <td><SubjectCell subject={w.subject} at={w.item_at} link={false} /></td>
              <td className="lib-date">{w.location?.name || "—"}</td>
              <td className="lib-date">{w.trade || "—"}</td>
              <td className="maint-nowrap">
                <span className="lib-date">{fmtDate(w.due)}</span>
                {late != null
                  ? <> <span className="chip chip-danger">{lateText(late)}</span></>
                  : w.overdue && <> <span className="chip chip-danger">late</span></>}
              </td>
              <td className="lib-date maint-nowrap">{linesText(w) || "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table></div>
  );
}

// Due soon: the tasks coming due in the window, grouped by package, then those in none.
function DueTab({ rows, horizon, onHorizon, locations, locationId, onLocation, onCreated, onError }) {
  const [query, setQuery] = useState("");
  const [creating, setCreating] = useState(false);
  const [made, setMade] = useState(null);
  const [raising, setRaising] = useState(null);
  const [raised, setRaised] = useState(null);
  // One site (the same choice as the Open tab's): the tasks whose work is there; then the search.
  const here = (rows || []).filter((t) => inArea(t, locationId));
  const shown = here.filter((t) => matches(query, ...dueSearchText(t)));
  const where = locationId && locations?.find((l) => l.id === locationId)?.name;
  // One package's visit on its own: nothing else that's due is raised.
  const raise = async (pkg) => {
    setRaising(pkg.id);
    setRaised(null);
    try {
      const out = await raisePackageVisit(pkg.id);
      setRaised({ ...out, name: pkg.name });
      onCreated?.();
    } catch (e) {
      onError?.(e.message);
    } finally {
      setRaising(null);
    }
  };
  const plan = createPlan(here);
  const create = async () => {
    setCreating(true);
    setMade(null);
    try {
      const out = await generateWorkOrders(horizon, locationId || null);
      setMade((out.work_orders || []).length);
      onCreated?.();
    } catch (e) {
      onError?.(e.message);
    } finally {
      setCreating(false);
    }
  };
  return (
    <section className="card">
      <div className="maint-head maint-wrap">
        <h2>Due in the next {horizon} days{where ? ` in ${where}` : ""}</h2>
        {plan.total > 0 && (
          <div className="maint-create">
            <button onClick={create} disabled={creating}>{creating ? "Creating…" : createLabel(plan)}</button>
            <span className="lib-date">{createDetail(plan)}</span>
          </div>
        )}
      </div>
      {raised && (
        <p className="lib-date" role="status">
          {raised.raised ? "Raised " : "Already open: "}
          <Link to={workOrderPath(raised.work_order.id)}>#{raised.work_order.number}</Link> for {raised.name}
          {raised.lines_added ? `, with ${raised.lines_added} more ${raised.lines_added === 1 ? "line" : "lines"}` : ""}.
        </p>
      )}
      {made != null && (
        <p className="lib-date" role="status">
          {made === 0 ? "No new work orders: everything due has one." : `${made} work order${made === 1 ? "" : "s"} created.`}
        </p>
      )}
      <div className="tablebar section-tablebar maint-filters">
        <span className="count">
          {rows == null ? "Loading…" : shown.length !== rows.length ? `${shown.length} of ${rows.length} tasks` : `${rows.length} ${rows.length === 1 ? "task" : "tasks"}`}
        </span>
        <span className="grow" />
        {locations?.length > 0 && (
          <label className="maint-row lib-date" style={{ marginTop: 0, gap: "0.5rem" }}>
            In
            <LocationPicker locations={locations} value={locationId} emptyLabel="Every location" onChange={onLocation} />
          </label>
        )}
        <Select className="section-type-filter" ariaLabel="Window" value={String(horizon)}
                onChange={(v) => onHorizon(Number(v))}
                options={DUE_WINDOWS.map((d) => ({ value: String(d), label: `Next ${d} days` }))} />
        <ListSearch value={query} onChange={setQuery} placeholder="Search what's due…" />
      </div>
      {rows == null ? null : rows.length === 0 ? (
        <p className="lib-date">Nothing due.</p>
      ) : shown.length === 0 ? (
        <p className="lib-date">{here.length === 0 ? "Nothing due there." : "Nothing due matches."}</p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>Task</th><th>On</th><th>Due</th><th>Work order</th></tr></thead>
          <tbody>
          {groupDue(shown).map((g) => (
            <Fragment key={g.key}>
              <tr className="lib-group">
                <th colSpan={4} scope="colgroup">
                  {g.package
                    ? <><Link to={packagePath(g.package.id)}>{g.package.name}</Link>
                      {g.package.active === false && <span className="lib-date"> · paused</span>}</>
                    : "Not in a package"}
                  <span className="lib-date"> · {g.tasks.length} {g.tasks.length === 1 ? "task" : "tasks"}</span>
                  {g.package && g.package.active !== false && !g.tasks.every((t) => t.open_work_order) && (
                    <button type="button" className="secondary sm maint-group-btn" disabled={raising === g.package.id}
                            onClick={() => raise(g.package)}>
                      {raising === g.package.id ? "Raising…" : "Raise this visit"}
                    </button>
                  )}
                </th>
              </tr>
              {g.tasks.map((t) => (
                <tr key={t.id} className="maint-plain-row">
                  <td>{t.name}</td>
                  <td><SubjectCell subject={t.subject} at={t.at} /></td>
                  <td className="maint-nowrap"><DueChip task={t} /></td>
                  <td>{t.open_work_order
                    ? <Link to={workOrderPath(t.open_work_order.id)}>#{t.open_work_order.number}</Link>
                    : <span className="lib-date">none yet</span>}</td>
                </tr>
              ))}
            </Fragment>
          ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

// Closed: every closed and cancelled work order, newest first, searched on the server.
function ClosedTab({ navigate }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState(null);
  const [failed, setFailed] = useState(null);
  useEffect(() => {
    let live = true;
    const wait = setTimeout(() => {
      listMaintenanceWorkOrders({ status: "done", query, limit: CLOSED_LIMIT })
        .then((d) => { if (live) { setFound(d); setFailed(null); } })
        .catch((e) => live && setFailed(e.message));
    }, query ? 250 : 0);
    return () => { live = false; clearTimeout(wait); };
  }, [query]);
  const rows = found?.work_orders;
  return (
    <section className="card">
      <div className="tablebar section-tablebar maint-filters">
        <span className="count">
          {rows == null ? "Loading…" : found.total > rows.length
            ? `The newest ${rows.length} of ${found.total}` : `${found.total} ${found.total === 1 ? "work order" : "work orders"}`}
        </span>
        <span className="grow" />
        <ListSearch value={query} onChange={setQuery} placeholder="Search closed work orders…" />
      </div>
      {failed && <div className="card error">{failed}</div>}
      {rows == null ? null : rows.length === 0 ? (
        <p className="lib-date">{query ? "Nothing closed matches." : "None closed yet."}</p>
      ) : (
        <div className="maint-scroll"><table className="lib-table">
          <thead><tr><th>#</th><th>Title</th><th>On</th><th>Closed</th><th>What was done</th></tr></thead>
          <tbody>
            {rows.map((w) => (
              <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, workOrderPath(w.id))}>
                <td>{w.number}</td>
                <td>
                  <RowLink to={workOrderPath(w.id)}>{w.title}</RowLink>
                  {w.package && <div className="lib-date">{w.package.name}</div>}
                </td>
                <td><SubjectCell subject={w.subject} at={w.item_at} link={false} /></td>
                <td className="lib-date maint-nowrap">{fmtDate(w.closed)}</td>
                <td className={w.status === "cancelled" ? "lib-date" : undefined}>{doneText(w)}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}
