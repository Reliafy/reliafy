import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getRbdPlanUses } from "../api.js";
import { formatPercent } from "../format.js";
import { fmtDate } from "./MaintenanceParts.jsx";
import "./RbdTaskUses.css";

// The Maintenance tab's "Used in RBDs": the repairable RBDs whose plans read these tasks
// (rbd_tree_plan.rbds_using_tasks). A block standing for a position takes its maintenance from
// the position's tasks, so a change to a task here changes those diagrams' plans; each says which
// task it models, and its last saved availability calculation (marked out of date when that used
// an older version of the task).
export default function RbdTaskUses({ taskIds, version = 0 }) {
  const key = useMemo(() => [...taskIds].sort().join(","), [taskIds]);
  const [state, setState] = useState({ key: null, uses: [] });
  useEffect(() => {
    if (!key) return undefined;
    let live = true;
    getRbdPlanUses(key.split(","))
      .then((d) => live && setState({ key, uses: d.uses || [] }))
      .catch(() => live && setState({ key, uses: [] }));
    return () => { live = false; };
  }, [key, version]);
  const uses = state.key === key ? state.uses : [];
  if (!uses.length) return null;
  return (
    <section className="rtu" aria-label="Used in RBDs">
      <h4 className="rtu-h">Used in RBDs</h4>
      <p className="lib-date rtu-why">These diagrams take their maintenance from the tasks here, read each time they&apos;re calculated.</p>
      <ul className="rtu-list">
        {uses.map((u) => (
          <li key={`${u.rbd.id}:${u.block.id}:${u.task.id}`}>
            <Link to={`/systems/b/${encodeURIComponent(u.rbd.id)}`}>{u.rbd.name}</Link>
            <span className="lib-date">
              {" "}· block {u.block.label} · “{u.task.name}” {u.used ? "is its plan" : "isn't modelled (a block takes one task)"}
              {u.last?.availability != null && <> · availability {formatPercent(u.last.availability)}{u.last.at ? ` (calculated ${fmtDate(u.last.at.slice(0, 10))})` : ""}</>}
            </span>
            {u.outdated && <span className="rtu-old"> · out of date: calculated before this task changed</span>}
          </li>
        ))}
      </ul>
    </section>
  );
}
