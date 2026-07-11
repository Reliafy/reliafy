import { useEffect, useState } from "react";
import { getAdminStats } from "../api.js";

const LABELS = {
  datasets: "Datasets",
  models: "Models",
  rbds: "RBDs",
  degradation_models: "Degradation models",
  tracked_items: "Tracked items",
  strategy_analyses: "Strategy analyses",
  rcm_studies: "RCM studies",
};

// Operator dashboard (ADMIN_EMAILS accounts only): signups, plans, volumes.
export default function AdminPage() {
  const [stats, setStats] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAdminStats().then(setStats).catch((e) => setError(e.message));
  }, []);

  if (error) {
    return (
      <div className="app">
        <header><h1>Operator stats</h1></header>
        <div className="card empty"><p>{error}</p></div>
      </div>
    );
  }
  if (!stats) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb"><b>Operator stats</b></div>
          <h1>Operator stats</h1>
          <p>Live counts straight from the database. Pageviews and errors are in Cloud Logging.</p>
        </div>
      </header>

      <div className="stats">
        <div className="stat"><div className="k">Users</div><div className="v">{stats.users_total}</div></div>
        <div className="stat"><div className="k">New (7 days)</div><div className="v">{stats.users_new_7d}</div></div>
        <div className="stat"><div className="k">Pro subscribers</div><div className="v">{stats.pro_users}</div></div>
        <div className="stat"><div className="k">Teams</div><div className="v">{stats.teams}</div></div>
        <div className="stat"><div className="k">Shares</div><div className="v">{stats.shares}</div></div>
      </div>

      <div className="card">
        <h2>Artifacts (excluding samples)</h2>
        <ul className="bill-usage">
          {Object.entries(stats.artifacts).map(([key, n]) => (
            <li key={key}>
              <span>{LABELS[key] || key}</span>
              <span className="bill-usage-n">{n}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
