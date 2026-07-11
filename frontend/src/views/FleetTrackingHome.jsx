import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import DegradationNewModal from "../components/DegradationNewModal.jsx";
import DegradationResultView from "../components/DegradationResultView.jsx";
import { listDegradationModels, saveDegradationModel } from "../api.js";
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
  const [models, setModels] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [pending, setPending] = useState(null); // { result, fit }
  const [name, setName] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(() => {
    listDegradationModels()
      .then((d) => setModels(d.models || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const visible = (models || []).filter((m) => matches(query, m.name));

  // Fit-and-save flow (same as Modelling → Degradation models), landing the
  // user straight on the new fleet's tracking page to register items.
  const onFitted = ({ result, fit }) => {
    setPending({ result, fit });
    const r = result.results;
    setName(`Degradation — ${r.path_model.name.toLowerCase()} to ${r.threshold}${r.measurement_unit ? " " + r.measurement_unit : ""}`);
    setError(null);
    setModalOpen(false);
  };

  const onSave = async () => {
    if (!name.trim() || !pending) return;
    setSaving(true);
    setError(null);
    try {
      const { fit } = pending;
      const saved = await saveDegradationModel(name.trim(), fit.file, fit);
      navigate(`/fleet/tracking/${saved.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

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
        <button onClick={() => setModalOpen(true)}>
          <PlusIcon /> New tracked fleet
        </button>
      </header>

      {error && <div className="card error">{error}</div>}

      {pending ? (
        <div className="card">
          <div className="save-bar">
            <input
              className="save-name"
              type="text"
              value={name}
              placeholder="Fleet name"
              onChange={(e) => setName(e.target.value)}
            />
            <button onClick={onSave} disabled={saving || !name.trim()}>
              {saving ? "Saving…" : "Save & track items"}
            </button>
            <button className="secondary" onClick={() => setPending(null)}>Discard</button>
          </div>
          <DegradationResultView results={pending.result.results} />
        </div>
      ) : models === null ? (
        <div className="card empty">Loading…</div>
      ) : models.length === 0 ? (
        <div className="card empty">
          <h2>Nothing tracked yet</h2>
          <p>
            Fit a degradation model from your inspection history, then
            register the items you have in service.
          </p>
          <button style={{ marginTop: "1rem" }} onClick={() => setModalOpen(true)}>
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
                <th style={{ width: "28%" }}>Tracked fleet</th>
                <th style={{ width: 80 }}>Items</th>
                <th>Health</th>
                <th style={{ width: 170 }}>Next predicted failure</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((m) => (
                <tr key={m.id} className="lib-row" onClick={() => navigate(`/fleet/tracking/${m.id}`)}>
                  <td>
                    <div className="lib-name">
                      {m.name}
                      {m.is_sample && <span className="sample-tag">Sample</span>}
                      {m.shared_by && <span className="sample-tag shared" title={`Shared by ${m.shared_by}`}>Shared</span>}
                    </div>
                  </td>
                  <td className="lib-n">{m.n_items}</td>
                  <td><HealthChips tracking={m.tracking} /></td>
                  <td className="lib-n">
                    {m.tracking?.next_crossing != null
                      ? `${fmt(m.tracking.next_crossing)}${m.unit ? ` ${m.unit}` : ""}`
                      : "—"}
                  </td>
                  <td className="lib-date">{relativeTime(m.updated_at || m.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/fleet/tracking/${m.id}`); }}>
                        <OpenIcon />
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
        <DegradationNewModal onClose={() => setModalOpen(false)} onFitted={onFitted} />
      )}
    </div>
  );
}
