import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import ApiAccessPanel from "../components/ApiAccessPanel.jsx";
import { restoreSamples } from "../api.js";

const TABS = [
  { id: "general", label: "General" },
  { id: "api", label: "API access" },
];

function initials(user) {
  const s = user?.displayName || user?.email || "?";
  return s.trim().slice(0, 2).toUpperCase();
}

// Account settings — profile, sample data, and the ingestion API. The single
// home for account-level details that aren't billing (which stays on /billing).
export default function SettingsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();

  const initial = new URLSearchParams(location.search).get("tab");
  const [tab, setTab] = useState(TABS.some((t) => t.id === initial) ? initial : "general");

  const [restoring, setRestoring] = useState(false);
  const onRestore = async () => {
    setRestoring(true);
    try {
      await restoreSamples();
      window.location.reload();
    } finally {
      setRestoring(false);
    }
  };

  const selectTab = (id) => {
    setTab(id);
    navigate(id === "general" ? "/settings" : `/settings?tab=${id}`, { replace: true });
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">Account / <b>Settings</b></div>
          <h1>Settings</h1>
          <p>Your profile, sample data, and programmatic access.</p>
        </div>
      </header>

      <div className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => selectTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "general" && (
        <div className="set-section">
          <div className="card">
            <h2>Profile</h2>
            <div className="set-profile">
              <span className="ava lg">{initials(user)}</span>
              <div>
                <div className="set-name">{user?.displayName || "—"}</div>
                <div className="muted-line">{user?.email || ""}</div>
              </div>
            </div>
          </div>

          <div className="card" style={{ marginTop: "1rem" }}>
            <h2>Sample data</h2>
            <p className="muted-line" style={{ marginTop: 0 }}>
              A fresh workspace comes with sample datasets, models, RBDs and
              studies so you can explore. Removing a sample only hides it from
              you — restore them here any time.
            </p>
            <button className="secondary" onClick={onRestore} disabled={restoring}>
              {restoring ? "Restoring…" : "Restore sample data"}
            </button>
          </div>
        </div>
      )}

      {tab === "api" && <ApiAccessPanel />}
    </div>
  );
}
