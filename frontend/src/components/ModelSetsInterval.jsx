import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getModelTasks } from "../api.js";
import { useRoles } from "../RolesProvider.jsx";
import { optimisePath, setsLine } from "../taskOptimise.js";

// On a model's page: the maintenance tasks whose interval an Optimise rests on this model ("Sets
// the interval of: Replace spark plugs (every 96 h)"), each linked to that task's Optimise, and a
// word when the model has been refitted since (its optimum may have moved). Nothing for a model no
// task rests on, or for someone without Reliafy Maintenance.
export default function ModelSetsInterval({ modelId }) {
  const { has } = useRoles() || {};
  const on = !!has?.maintenance;
  const [tasks, setTasks] = useState([]);
  useEffect(() => {
    if (!on || !modelId) return undefined;
    let live = true;
    getModelTasks([modelId]).then((d) => live && setTasks(d.tasks?.[modelId] || []), () => live && setTasks([]));
    return () => { live = false; };
  }, [modelId, on]);
  if (!tasks.length) return null;
  return (
    <p className="mf-notice model-sets" role="note">
      Sets the interval of{" "}
      {tasks.map((t, i) => (
        <span key={t.task_id}>
          {i > 0 && ", "}
          <Link to={optimisePath(t)}>{setsLine(t)}</Link>
          {t.moved && <span className="model-sets-moved"> (refitted since: re-optimise)</span>}
        </span>
      ))}.
    </p>
  );
}
