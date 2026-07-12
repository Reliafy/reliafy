import { useCallback, useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import Modal from "../components/Modal.jsx";
import Select from "../components/Select.jsx";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { listFleets, createFleet, deleteFleet, listModels } from "../api.js";
import { relativeTime } from "../instrument.js";

const PlusIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 5v14M5 12h14" />
  </svg>
);
const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Fleet forecasts: one row per fleet with its live expected-failure headline.
export default function FleetForecasts() {
  const navigate = useNavigate();
  const [fleets, setFleets] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [capHit, setCapHit] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [models, setModels] = useState([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState(null);

  const refresh = useCallback(() => {
    listFleets()
      .then((d) => setFleets(d.fleets || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const openCreate = async () => {
    setCreateError(null);
    setModalOpen(true);
    try {
      const { models: all } = await listModels();
      // Forecasting needs a plain distribution (no covariates).
      setModels(all.filter((m) => m.distribution && !String(m.distribution).includes("PH")));
    } catch {
      setModels([]);
    }
  };

  const onCreate = async () => {
    if (!name.trim() || !modelId) return;
    setCreating(true);
    setCreateError(null);
    try {
      const fleet = await createFleet(name.trim(), modelId);
      navigate(`/fleet/forecasts/${fleet.id}`);
    } catch (err) {
      if (err.code === "cap") {
        setModalOpen(false);
        setCapHit(true);
      } else {
        setCreateError(err.message);
      }
    } finally {
      setCreating(false);
    }
  };

  const onDelete = async (f) => {
    const msg = f.is_sample
      ? `Remove the sample “${f.name}” from your workspace? It stays available to other users.`
      : `Delete fleet “${f.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteFleet(f.id);
    refresh();
  };

  const visible = (fleets || []).filter((f) => matches(query, f.name));

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/fleet")}>Fleet</button> / <b>Failure forecasts</b>
          </div>
          <h1>Failure forecasts</h1>
          <p>
            Predict how many failures a fleet will see over a chosen horizon,
            straight from your fitted life models.
          </p>
        </div>
        <button onClick={openCreate}>
          <PlusIcon /> New forecast
        </button>
      </header>

      {error && <div className="card error">{error}</div>}
      {capHit && (
        <div className="card upgrade-nudge">
          <p>
            You've reached the free-plan limit of 1 failure forecast.{" "}
            <Link to="/billing">Upgrade to Pro</Link> for unlimited fleets.
          </p>
        </div>
      )}

      {fleets === null ? (
        <div className="card empty">Loading…</div>
      ) : fleets.length === 0 ? (
        <div className="card empty">
          <h2>No fleet forecasts</h2>
          <p>Create one from a saved life model and list the items you have in service.</p>
          <button style={{ marginTop: "1rem" }} onClick={openCreate}>
            <PlusIcon /> New forecast
          </button>
        </div>
      ) : (
        <div className="lib">
          <div className="tablebar">
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search forecasts…" />
          </div>
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Forecast</th>
                <th style={{ width: 80 }}>Items</th>
                <th>Forecast</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((f) => (
                <tr key={f.id} className="lib-row" onClick={() => navigate(`/fleet/forecasts/${f.id}`)}>
                  <td>
                    <div className="lib-name">
                      {f.name}
                      {f.is_sample && <span className="sample-tag">Sample</span>}
                      {f.shared_by && <span className="sample-tag shared" title={`Shared by ${f.shared_by}`}>Shared</span>}
                    </div>
                  </td>
                  <td className="lib-n">{f.n_items}</td>
                  <td className="lib-date">{f.headline}</td>
                  <td className="lib-date">{relativeTime(f.updated_at || f.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/fleet/forecasts/${f.id}`); }}>
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
          title="New failure forecast"
          locked={creating}
          onClose={() => setModalOpen(false)}
          footer={
            <>
              <button className="secondary" onClick={() => setModalOpen(false)} disabled={creating}>
                Cancel
              </button>
              <button onClick={onCreate} disabled={creating || !name.trim() || !modelId}>
                {creating ? "Creating…" : "Create forecast"}
              </button>
            </>
          }
        >
          {createError && <div className="card error">{createError}</div>}
          <div className="rcm-form">
            <label className="login-field">
              <span>Name</span>
              <input
                type="text"
                autoFocus
                value={name}
                placeholder="e.g. Delivery trucks — bearings, next 12 months"
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && onCreate()}
              />
            </label>
            <label className="login-field">
              <span>Life model</span>
              <Select
                value={modelId}
                onChange={setModelId}
                placeholder="Choose a saved model…"
                options={models.map((m) => ({
                  value: m.id,
                  label: m.name,
                  hint: m.distribution,
                }))}
              />
            </label>
            <p className="muted-line">
              The forecast evaluates this model at each item's age — fit one
              under Modelling first if you don't have one yet.
            </p>
          </div>
        </Modal>
      )}
    </div>
  );
}
