import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createMaintenancePosition,
  generateWorkOrders,
  getMaintenanceOverview,
  getMaintenanceSettings,
  setMaintenanceSettings,
  listRcmStudies,
  maintenanceFromRcm,
} from "../api.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon } from "../components/LibRows.jsx";
import {
  DueChip, Field, FormModal, MaintenanceTabs, PositionPicker, flatten, fmtDate,
} from "../components/MaintenanceParts.jsx";
import "./Maintenance.css";

// Reliafy Maintenance home: what's due, open work orders, and the plant as a
// tree of positions with what's fitted in each.
export default function MaintenanceHome() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // "position" | "rcm"
  const [generating, setGenerating] = useState(false);

  const [digest, setDigest] = useState(null);
  const refresh = useCallback(() => {
    getMaintenanceOverview().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);
  useEffect(() => {
    getMaintenanceSettings().then((s) => setDigest(s.digest)).catch(() => {});
  }, []);
  const toggleDigest = async (on) => {
    setDigest(on);
    await setMaintenanceSettings({ digest: on }).catch(() => setDigest(!on));
  };

  const onGenerate = async () => {
    setGenerating(true);
    try {
      await generateWorkOrders(30);
      refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setGenerating(false);
    }
  };

  const positions = flatten(data?.tree);
  const unscheduled = (data?.due || []).filter((t) => !t.open_work_order);

  return (
    <div className="app">
      <PageHeader
        title="Maintenance"
        meta="Your plant as positions, what's fitted in each, the tasks from your RCM studies, and the work done."
        actions={<button className="secondary" onClick={() => setModal("rcm")}>From an RCM study</button>}
        primary={<button onClick={() => setModal("position")}><PlusIcon /> New position</button>}
      />
      <MaintenanceTabs />
      {error && <div className="card error">{error}</div>}
      {data === null ? (
        <div className="card empty">Loading…</div>
      ) : data.tree.length === 0 ? (
        <div className="card empty">
          <h2>Nothing here yet</h2>
          <p>Start from an RCM study (its system becomes a position, with the study's tasks), or add a position by hand.</p>
          <div className="maint-row" style={{ justifyContent: "center", marginTop: "1rem" }}>
            <button className="secondary" onClick={() => setModal("rcm")}>From an RCM study</button>
            <button onClick={() => setModal("position")}><PlusIcon /> New position</button>
          </div>
        </div>
      ) : (
        <>
          <section className="card">
            <div className="maint-head">
              <h2>Due in the next 30 days</h2>
              {unscheduled.length > 0 && (
                <button onClick={onGenerate} disabled={generating}>
                  {generating ? "Creating…" : `Create ${unscheduled.length} work order${unscheduled.length === 1 ? "" : "s"}`}
                </button>
              )}
            </div>
            {data.due.length === 0 ? (
              <p className="lib-date">Nothing due.</p>
            ) : (
              <table className="lib-table">
                <thead><tr><th>Task</th><th>Position</th><th>Due</th><th>Work order</th></tr></thead>
                <tbody>
                  {data.due.map((t) => (
                    <tr key={t.id}>
                      <td>{t.name}</td>
                      <td>{t.position && <Link to={`/maintenance/positions/${t.position.id}`}>{t.position.name}</Link>}</td>
                      <td><DueChip task={t} /></td>
                      <td>{t.open_work_order
                        ? <Link to={`/maintenance/work-orders/${t.open_work_order.id}`}>#{t.open_work_order.number}</Link>
                        : <span className="lib-date">none yet</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <div className="maint-head"><h2>Open work orders</h2></div>
            {data.open_work_orders.length === 0 ? (
              <p className="lib-date">None open.</p>
            ) : (
              <table className="lib-table">
                <thead><tr><th>#</th><th>Title</th><th>Position</th><th>Type</th><th>Due</th></tr></thead>
                <tbody>
                  {data.open_work_orders.map((w) => (
                    <tr key={w.id} className="lib-row" onClick={() => navigate(`/maintenance/work-orders/${w.id}`)}>
                      <td>{w.number}</td>
                      <td>{w.title}</td>
                      <td>{w.position?.name}</td>
                      <td>{w.type}</td>
                      <td className="lib-date">{fmtDate(w.due)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="card">
            <div className="maint-head">
              <h2>Positions</h2>
              <span className="lib-date">
                {data.summary.positions} positions · {data.summary.items} items · {data.summary.tasks} tasks
              </span>
            </div>
            <ul className="maint-tree">
              {data.tree.map((node) => <TreeNode key={node.id} node={node} />)}
            </ul>
          </section>
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
          onCreated={(p) => navigate(`/maintenance/positions/${p.id}`)}
        />
      )}
      {modal === "rcm" && (
        <FromRcmModal
          positions={positions}
          onClose={() => setModal(null)}
          onCreated={(r) => navigate(`/maintenance/positions/${r.position.id}`)}
        />
      )}
    </div>
  );
}

function TreeNode({ node }) {
  return (
    <li>
      <div className="maint-node">
        <Link to={`/maintenance/positions/${node.id}`} className="maint-node-name">{node.name}</Link>
        {node.tag && <span className="lib-date">{node.tag}</span>}
        <span className="maint-node-item">{node.item
          ? <Link to={`/maintenance/items/${node.item.id}`}>{node.item.name}</Link>
          : <span className="lib-date">nothing fitted</span>}</span>
        {node.next_due && <span className="lib-date">next due {fmtDate(node.next_due)}</span>}
        {node.open_work_orders > 0 && <span className="maint-badge">{node.open_work_orders} open</span>}
      </div>
      {node.children.length > 0 && (
        <ul>{node.children.map((c) => <TreeNode key={c.id} node={c} />)}</ul>
      )}
    </li>
  );
}

export function NewPositionModal({ positions, parentId = null, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [tag, setTag] = useState("");
  const [positionClass, setPositionClass] = useState("");
  const [parent, setParent] = useState(parentId);
  return (
    <FormModal
      title="New position"
      submitLabel="Create position"
      canSubmit={!!name.trim()}
      onClose={onClose}
      onSubmit={async () => onCreated(await createMaintenancePosition({
        name, tag, position_class: positionClass, parent_id: parent,
      }))}
    >
      <Field label="Name">
        <input autoFocus value={name} placeholder="e.g. Hot water system" onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Inside">
        <PositionPicker positions={positions} value={parent} onChange={setParent} />
      </Field>
      <Field label="Tag (optional)">
        <input value={tag} placeholder="e.g. =HOUSE.HWS" onChange={(e) => setTag(e.target.value)} />
      </Field>
      <Field label="Class (optional, to compare like positions)">
        <input value={positionClass} placeholder="e.g. Electric storage water heater" onChange={(e) => setPositionClass(e.target.value)} />
      </Field>
    </FormModal>
  );
}

function FromRcmModal({ positions, onClose, onCreated }) {
  const [studies, setStudies] = useState(null);
  const [studyId, setStudyId] = useState("");
  const [parent, setParent] = useState(null);
  useEffect(() => {
    listRcmStudies().then((d) => setStudies(d.studies || [])).catch(() => setStudies([]));
  }, []);
  return (
    <FormModal
      title="From an RCM study"
      submitLabel="Create position"
      canSubmit={!!studyId}
      onClose={onClose}
      onSubmit={async () => onCreated(await maintenanceFromRcm(studyId, parent))}
    >
      <p className="lib-date">
        The study's system becomes a position. Its failure modes come with it, and every decision with an
        interval becomes a scheduled task.
      </p>
      <Field label="RCM study">
        <select value={studyId} onChange={(e) => setStudyId(e.target.value)}>
          <option value="">{studies === null ? "Loading…" : "Choose a study"}</option>
          {(studies || []).map((s) => (
            <option key={s.id} value={s.id}>{s.name}{s.system ? ` (${s.system})` : ""}</option>
          ))}
        </select>
      </Field>
      <Field label="Inside">
        <PositionPicker positions={positions} value={parent} onChange={setParent} />
      </Field>
    </FormModal>
  );
}
