import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Link } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import { listTrackedFleets, createTrackedFleet, deleteTrackedFleet, listDegradationModels } from "../api.js";
import { relativeTime } from "../instrument.js";

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);
const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);

const fmt = (v) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: 0 });

// Health-chip strip for one tracked fleet (mirrors the item badges).
function HealthChips({ tracking }) {
  if (!tracking) return <span className="lib-date">—</span>;
  const parts = [
    ["replace", tracking.replace, "health-red", "replace now"],
    ["plan", tracking.plan, "health-amber", "plan replacement"],
    ["healthy", tracking.healthy, "health-green", "healthy"],
    ["monitoring", tracking.monitoring, "health-grey", "monitoring"],
  ].filter(([, n]) => n > 0);
  if (!parts.length) return <span className="lib-date">No items yet</span>;
  return (
    <span className="rollup-badges">
      {parts.map(([key, n, cls, label]) => (
        <span key={key} className={`health-badge ${cls}`}>{n} {label}</span>
      ))}
    </span>
  );
}

// Index of tracked fleets: one row per degradation model with its live
// health rollup. Opening a row goes to that model's tracking page.
export default function FleetTrackingHome() {
  const navigate = useNavigate();
  const [fleets, setFleets] = useState(null);
  const [models, setModels] = useState([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [pickedId, setPickedId] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  const refresh = useCallback(() => {
    listTrackedFleets()
      .then((d) => setFleets(d.fleets || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const openCreate = async () => {
    setName("");
    setPickedId("");
    setCreateError(null);
    setModalOpen(true);
    try {
      const { models: all } = await listDegradationModels();
      setModels(all || []);
    } catch {
      setModels([]);
    }
  };

  const startTracking = async () => {
    if (!name.trim() || !pickedId) return;
    setCreating(true);
    setCreateError(null);
    try {
      const fleet = await createTrackedFleet(name.trim(), pickedId);
      navigate(`/fleet/tracking/${fleet.id}`);
    } catch (err) {
      setCreateError(err.message);
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (f) => {
    const msg = f.is_sample
      ? `Remove the sample “${f.name}” from your workspace? It stays available to other users.`
      : `Delete fleet “${f.name}” and its tracked items?`;
    if (!window.confirm(msg)) return;
    await deleteTrackedFleet(f.id);
    refresh();
  };

  const visible = (fleets || []).filter((f) => matches(query, f.name, f.model_name));

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/fleet")}>Fleet</button> / <b>Degradation tracking</b>
          </div>
          <h1>Degradation tracking</h1>
          <p>
            Each degradation model tracks its own fleet of in-service items.
            Open one to see every item's remaining life and log inspections.
          </p>
        </div>
        <button onClick={openCreate}>
          <PlusIcon /> New tracked fleet
        </button>
      </header>

      {error && <div className="card error">{error}</div>}

      {fleets === null ? (
        <div className="card empty">Loading…</div>
      ) : fleets.length === 0 ? (
        <div className="card empty">
          <h2>Nothing tracked yet</h2>
          <p>
            Name a fleet, pick the degradation model it runs against, and
            register the items you have in service — or{" "}
            <Link to="/modelling/degradation">fit a model</Link> first.
          </p>
          <button style={{ marginTop: "1rem" }} onClick={openCreate}>
            <PlusIcon /> New tracked fleet
          </button>
        </div>
      ) : (
        <div className="lib">
          <div className="tablebar">
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search tracked fleets…" />
          </div>
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "24%" }}>Tracked fleet</th>
                <th style={{ width: "20%" }}>Model</th>
                <th style={{ width: 70 }}>Items</th>
                <th>Health</th>
                <th style={{ width: 160 }}>Next predicted failure</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((f) => (
                <tr key={f.id} className="lib-row" onClick={() => navigate(`/fleet/tracking/${f.id}`)}>
                  <td>
                    <div className="lib-name">
                      {f.name}
                      {f.is_sample && <span className="sample-tag">Sample</span>}
                    </div>
                  </td>
                  <td className="lib-date">{f.model_name || "—"}</td>
                  <td className="lib-n">{f.n_items}</td>
                  <td><HealthChips tracking={f.tracking} /></td>
                  <td className="lib-n">
                    {f.tracking?.next_crossing != null
                      ? `${fmt(f.tracking.next_crossing)}${f.unit ? ` ${f.unit}` : ""}`
                      : "—"}
                  </td>
                  <td className="lib-date">{relativeTime(f.updated_at || f.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/fleet/tracking/${f.id}`); }}>
                        <OpenIcon />
                      </button>
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(f); }}>
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {modalOpen && (
        <Modal
          title="New tracked fleet"
          className="modal-sm"
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)}>Cancel</button>
              <button onClick={startTracking} disabled={creating || !name.trim() || !pickedId}>
                {creating ? "Creating…" : "Start tracking"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Fleet name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Sydney trucks — brake pads"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && startTracking()}
              />
            </label>
            <label className="login-field">
              <span>Degradation model</span>
              <Select
                value={pickedId}
                onChange={setPickedId}
                placeholder="Choose a model…"
                options={models.map((m) => ({
                  value: m.id,
                  label: m.name,
                  hint: `${m.path_model || ""} · threshold ${m.threshold}${m.measurement_unit ? " " + m.measurement_unit : ""}`,
                }))}
              />
            </label>
            <p className="muted-line">
              One model can back any number of fleets. Don't have a model yet?{" "}
              <Link to="/modelling/degradation" onClick={() => setModalOpen(false)}>
                Fit a degradation model
              </Link>{" "}
              from your inspection history first.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
