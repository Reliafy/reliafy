import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listJointModels, deleteJointModel } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import { CATEGORY } from "../plotTheme.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { PlusIcon, RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";

const JOINT_COLOR = CATEGORY.blue;

// Condition-based risk models (joint models of readings and failures): the
// list, like the other model types'. The fit lives on /modelling/joint/new.
export default function JointHome() {
  const navigate = useNavigate();
  const [models, setModels] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");

  const refresh = () => listJointModels().then((r) => setModels(r.models)).catch(() => setModels([]));
  useEffect(() => { refresh(); }, []);

  const onDelete = async (m) => {
    const msg = m.is_sample
      ? `Remove the sample “${itemName(m)}” from your workspace? It stays available to other users.`
      : `Delete “${m.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteJointModel(m.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/modelling/joint/${id}`);
  const visible = (models || []).filter((m) => matches(query, m.name, m.marker, m.path_model, m.id));

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Modelling", to: "/modelling" }]}
        title="Condition-based risk"
        meta="Readings taken on each unit (vibration, wear, oil debris) and its failures, fitted together: each running unit's own risk."
        primary={<button onClick={() => navigate("/modelling/joint/new")}><PlusIcon /> New model</button>}
      />
      {error && <div className="card error">{error}</div>}
      {models === null ? (
        <div className="card empty">Loading…</div>
      ) : !models.length ? (
        <div className="card empty">
          <h2>No saved models</h2>
          <p>
            Fit one from two tables: your units (each one's age at failure, or now, and whether it failed) and
            their readings (unit, age, value).
          </p>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {models.length} models</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search models…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "36%" }}>Model</th>
                  <th>Reading</th>
                  <th className="lib-opt" style={{ width: 80 }}>Units</th>
                  <th className="lib-opt" style={{ width: 80 }}>Running</th>
                  <th className="lib-opt">Saved</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={6} render={(m) => (
                  <tr key={m.id} className="lib-row" onClick={() => open(m.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(m)}
                        {m.shared_by && <Chip title={`Shared by ${m.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td>
                      <Chip dot={JOINT_COLOR}>{[m.marker, m.path_model && `${m.path_model} path`].filter(Boolean).join(" · ") || "—"}</Chip>
                    </td>
                    <td className="lib-n lib-opt">{(m.n_items ?? 0).toLocaleString()}</td>
                    <td className="lib-n lib-opt">{(m.n_running ?? 0).toLocaleString()}</td>
                    <td className="lib-date lib-opt">{relativeTime(m.created_at)}</td>
                    <RowActions item={m} onOpen={() => open(m.id)} onDelete={() => onDelete(m)} />
                  </tr>
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
