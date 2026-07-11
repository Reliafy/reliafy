import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { listDegradationModels } from "../api.js";
import { relativeTime } from "../instrument.js";

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

  const refresh = useCallback(() => {
    listDegradationModels()
      .then((d) => setModels(d.models || []))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const visible = (models || []).filter((m) => matches(query, m.name));

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
      </header>

      {error && <div className="card error">{error}</div>}

      {models === null ? (
        <div className="card empty">Loading…</div>
      ) : models.length === 0 ? (
        <div className="card empty">
          <h2>Nothing tracked yet</h2>
          <p>
            Tracking needs a degradation model to predict against.{" "}
            <Link to="/modelling/degradation">Fit one under Modelling → Degradation models</Link>,
            then register the items you have in service.
          </p>
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
    </div>
  );
}
