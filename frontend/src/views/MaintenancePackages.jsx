import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getPackage, listPackages } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch from "../components/ListSearch.jsx";
import Select from "../components/Select.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import LoadFailed from "../components/LoadFailed.jsx";
import { PageTitle } from "../components/usePageTitle.js";
import { RowLink, rowOpen } from "../components/LibRows.jsx";
import { DueChip, fmtDate } from "../components/MaintenanceParts.jsx";
import { SubjectCell } from "./MaintenanceHome.jsx";
import { explorerPath } from "../assetTree.js";
import {
  PACKAGES_PATH, daysLate, lateText, packageMatches, packagePath, packageStatusText, workOrderPath,
} from "../maintenanceOrders.js";
import { ORDERS_PATH, PACKAGES_LABEL } from "../navigation.js";
import { subjectPath } from "../maintenanceSubjects.js";
import "./Maintenance.css";

const HELP = { guide: "maintenance-work-orders" };
// Packages are made where the tasks are: the Explorer's LSA tab (tick tasks, then package them).
const LSA_PATH = explorerPath("positions", { tab: "lsa" });

const STATUSES = [
  { value: "", label: "Active and paused" },
  { value: "active", label: "Active" },
  { value: "paused", label: "Paused" },
  { value: "retired", label: "Retired" },
  { value: "all", label: "All" },
];

// Maintenance › Packages: every work package (tasks done together on one visit,
// one work order per visit), with what it's on, its timing, next visit and status.
export default function MaintenancePackages() {
  const navigate = useNavigate();
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setData(null);
    listPackages(status ? { status } : {}).then((d) => live && setData(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [status]);
  const rows = data?.packages;
  const shown = (rows || []).filter((p) => packageMatches(p, query));
  return (
    <div className="app">
      <SectionHeader
        section="maintenance"
        title={PACKAGES_LABEL}
        purpose="Tasks done together on one visit, with one work order for each visit."
        help={HELP}
        primary={<button onClick={() => navigate(LSA_PATH)}>Package tasks</button>}
      />
      {error && <div className="card error">{error}</div>}
      {data && (
        <p className="maint-answer">
          {rows.length === 0 ? "No packages here."
            : `${rows.length} ${rows.length === 1 ? "package" : "packages"}.`
              + (data.open_work_orders ? ` ${data.open_work_orders} with a visit open${data.late ? `, ${data.late} late` : ""}.` : " No visit open.")}
        </p>
      )}
      <section className="card">
        <div className="tablebar section-tablebar maint-filters">
          <span className="count">
            {rows == null ? "Loading…" : shown.length === rows.length
              ? `${rows.length} ${rows.length === 1 ? "package" : "packages"}` : `${shown.length} of ${rows.length} packages`}
          </span>
          <span className="grow" />
          <Select className="section-type-filter" ariaLabel="Status" value={status} onChange={setStatus} options={STATUSES} />
          <ListSearch value={query} onChange={setQuery} placeholder="Search packages…" />
        </div>
        {rows == null ? null : rows.length === 0 ? (
          <div className="empty">
            <p className="lib-date">
              {status ? "No packages with that status." : <>No packages yet. Tick tasks on the Explorer's <Link to={LSA_PATH}>LSA tab</Link> to package them into visits.</>}
            </p>
          </div>
        ) : shown.length === 0 ? (
          <p className="lib-date">No package matches.</p>
        ) : (
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Name</th><th>On</th><th>Timing</th><th>Next due</th><th>Tasks</th><th>Status</th></tr></thead>
            <tbody>
              {shown.map((p) => <PackageRow key={p.id} p={p} navigate={navigate} />)}
            </tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}

function PackageRow({ p, navigate }) {
  const wo = p.open_work_order;
  return (
    <tr className="lib-row" onClick={rowOpen(navigate, packagePath(p.id))}>
      <td>
        <RowLink to={packagePath(p.id)}>{p.name}</RowLink>
        {p.parent && <div className="lib-date">a layer on {p.parent.name}</div>}
      </td>
      <td><SubjectCell subject={p.subject} link={false} /></td>
      <td className="lib-date">{p.cadence?.text}{p.season?.text ? `, ${p.season.text}` : ""}</td>
      <td className="maint-nowrap">
        {wo ? (
          <>
            <span className="lib-date">#{wo.number} · {fmtDate(wo.visit_on)}</span>
            {wo.late && <> <span className="chip chip-danger">{lateText(wo.days_late) || "late"}</span></>}
          </>
        ) : <span className="lib-date">{fmtDate(p.next_visit)}</span>}
      </td>
      <td>{p.task_count}</td>
      <td className={p.status === "active" && !wo?.late ? "lib-date" : undefined}>{packageStatusText(p)}</td>
    </tr>
  );
}

// One package, kept simple: what it's on and when, its next visits, its tasks
// and its recent work orders.
export function MaintenancePackage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    let live = true;
    setPkg(null);
    setError(null);
    getPackage(id).then((p) => live && setPkg(p)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [id]);
  if (error && !pkg) {
    return <div className="app"><LoadFailed header error={error} notFound="Package not found." to={PACKAGES_PATH} label="Back to Packages" /></div>;
  }
  if (!pkg) return <div className="app"><div className="card empty">Loading…</div></div>;
  const wo = pkg.open_work_order;
  const late = wo?.late ? daysLate({ overdue: true, days_late: wo.days_late }, null) : null;
  return (
    <div className="app">
      <PageTitle name={pkg.name} />
      <PageHeader
        crumbs={[{ label: "Maintenance", to: ORDERS_PATH }, { label: PACKAGES_LABEL, to: PACKAGES_PATH }]}
        title={pkg.name}
        meta={[pkg.cadence?.text, pkg.subject && `on ${pkg.subject.name}`, packageStatusText(pkg)].filter(Boolean).join(" · ")}
        id={pkg.id}
      />
      <section className="card">
        <dl className="maint-dl">
          {pkg.subject && <><dt>On</dt><dd><Link to={subjectPath(pkg.subject)}>{pkg.subject.name}</Link></dd></>}
          <dt>Timing</dt><dd>{pkg.cadence?.text}{pkg.season?.text ? `, ${pkg.season.text}` : ""}</dd>
          {pkg.tolerance?.amount && <><dt>On time within</dt><dd>{pkg.tolerance.amount} {pkg.tolerance.unit}</dd></>}
          {pkg.trade && <><dt>Trade</dt><dd>{pkg.trade}</dd></>}
          {pkg.parent && <><dt>A layer on</dt><dd><Link to={packagePath(pkg.parent.id)}>{pkg.parent.name}</Link></dd></>}
          {pkg.layers?.length > 0 && (
            <><dt>Layers</dt><dd>{pkg.layers.map((l, i) => <span key={l.id}>{i > 0 && ", "}<Link to={packagePath(l.id)}>{l.name}</Link></span>)}</dd></>
          )}
          {wo ? (
            <><dt>Open visit</dt><dd>
              <Link to={workOrderPath(wo.id)}>#{wo.number}</Link> · {fmtDate(wo.visit_on)}
              {wo.late && <> <span className="chip chip-danger">{lateText(late) || "late"}</span></>}
            </dd></>
          ) : pkg.next_visit && !pkg.next_visits?.length && <><dt>Next visit</dt><dd>{fmtDate(pkg.next_visit)}</dd></>}
          {pkg.pause?.text && <><dt>Paused</dt><dd>{pkg.pause.text}{pkg.paused_reason ? `: ${pkg.paused_reason}` : ""}</dd></>}
          {pkg.notes && <><dt>Notes</dt><dd>{pkg.notes}</dd></>}
        </dl>
        {pkg.next_visits?.length > 0 && (
          <p className="lib-date" style={{ marginBottom: 0 }}>
            Next visits: {pkg.next_visits.map((v) => `${fmtDate(v.on)} (${v.tasks} ${v.tasks === 1 ? "task" : "tasks"})`).join(", ")}
          </p>
        )}
      </section>

      <section className="card">
        <div className="maint-head"><h2>Tasks ({pkg.tasks?.length || 0})</h2></div>
        {!pkg.tasks?.length ? <p className="lib-date">No tasks in it yet.</p> : (
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>Task</th><th>On</th><th>Every</th><th>Next due</th><th>Work order</th></tr></thead>
            <tbody>
              {pkg.tasks.map((t) => (
                <tr key={t.task_id} className="maint-plain-row">
                  <td>{t.name}{t.retired && <span className="lib-date"> · retired</span>}
                    {t.visit_rule === "every_nth" && t.every_nth && <div className="lib-date">every {t.every_nth} visits</div>}</td>
                  <td><SubjectCell subject={t.subject} /></td>
                  <td className="lib-date maint-nowrap">{t.interval} {t.interval === 1 ? String(t.unit).replace(/s$/, "") : t.unit}</td>
                  <td className="maint-nowrap"><DueChip task={t} /></td>
                  <td>{t.open_work_order
                    ? <Link to={workOrderPath(t.open_work_order.id)}>#{t.open_work_order.number}</Link>
                    : <span className="lib-date">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>

      <section className="card">
        <div className="maint-head"><h2>Recent work orders</h2></div>
        {!pkg.work_orders?.length ? <p className="lib-date">None raised yet.</p> : (
          <div className="maint-scroll"><table className="lib-table">
            <thead><tr><th>#</th><th>Title</th><th>Visit</th><th>Status</th></tr></thead>
            <tbody>
              {pkg.work_orders.map((w) => (
                <tr key={w.id} className="lib-row" onClick={rowOpen(navigate, workOrderPath(w.id))}>
                  <td>{w.number}</td>
                  <td><RowLink to={workOrderPath(w.id)}>{w.title}</RowLink></td>
                  <td className="lib-date maint-nowrap">{fmtDate(w.visit_on || w.due)}</td>
                  <td className="lib-date">{w.status.replace("_", " ")}{w.overdue ? " · late" : ""}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
