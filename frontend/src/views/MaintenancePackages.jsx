import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listPackages } from "../api.js";
import { SectionHeader } from "../components/SectionPage.jsx";
import ListSearch from "../components/ListSearch.jsx";
import Select from "../components/Select.jsx";
import { RowLink, rowOpen } from "../components/LibRows.jsx";
import { fmtDate } from "../components/MaintenanceParts.jsx";
import { SubjectCell } from "./MaintenanceHome.jsx";
import { explorerPath } from "../assetTree.js";
import {
  lateText, packageMatches, packagePath, packageStatusText,
} from "../maintenanceOrders.js";
import { PACKAGES_LABEL } from "../navigation.js";
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
