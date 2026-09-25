import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import ApiAccessPanel from "../components/ApiAccessPanel.jsx";
import {
  restoreSamples,
  removeSamples,
  getEmailPreferences,
  setEmailPreferences,
} from "../api.js";
import { AUTH_DISABLED } from "../firebase.js";

const TABS = [
  { id: "general", label: "General" },
  { id: "api", label: "API access" },
];

function initials(user) {
  const s = user?.displayName || user?.email || "?";
  return s.trim().slice(0, 2).toUpperCase();
}

// Product-update email opt-out. Optimistic: the checkbox flips immediately and
// reverts if the save fails. Hidden on self-hosted builds, which send no email.
function EmailPreferences() {
  const [updates, setUpdates] = useState(null); // null until loaded
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    getEmailPreferences()
      .then((p) => alive && setUpdates(!!p.updates))
      .catch(() => alive && setError("Couldn't load your email preferences."));
    return () => {
      alive = false;
    };
  }, []);

  const onToggle = async (e) => {
    const next = e.target.checked;
    const prev = updates;
    setUpdates(next);
    setError("");
    setSaving(true);
    try {
      const p = await setEmailPreferences({ updates: next });
      setUpdates(!!p.updates);
    } catch {
      setUpdates(prev);
      setError("Couldn't save that change — please try again.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <h2>Emails</h2>
      <label className="set-check">
        <input
          type="checkbox"
          checked={!!updates}
          onChange={onToggle}
          disabled={updates === null || saving}
        />
        <span>
          <b>Product update emails</b> — a short monthly note on what's new.
        </span>
      </label>
      <p className="muted-line" style={{ marginBottom: 0 }}>
        Emails you trigger yourself, like team invites and shares, aren't affected.
      </p>
      {error && <div className="error" style={{ marginBottom: 0 }}>{error}</div>}
    </div>
  );
}

// Account settings — profile, sample data, and the ingestion API. The single
// home for account-level details that aren't billing (which stays on /billing).
export default function SettingsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();

  const initial = new URLSearchParams(location.search).get("tab");
  const [tab, setTab] = useState(TABS.some((t) => t.id === initial) ? initial : "general");

  const [samplesBusy, setSamplesBusy] = useState("");
  const onRestore = async () => {
    setSamplesBusy("restore");
    try {
      await restoreSamples();
      window.location.reload();
    } finally {
      setSamplesBusy("");
    }
  };
  const onRemoveAll = async () => {
    if (!window.confirm("Remove all sample data from your workspace? The samples stay available to restore any time.")) return;
    setSamplesBusy("remove");
    try {
      await removeSamples();
      window.location.reload();
    } finally {
      setSamplesBusy("");
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
          <p>Your profile, sample data, emails, and programmatic access.</p>
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
              studies so you can explore. Hiding samples only affects your view —
              they stay available to restore any time.
            </p>
            <div className="row" style={{ gap: "0.6rem" }}>
              <button className="secondary" onClick={onRestore} disabled={!!samplesBusy}>
                {samplesBusy === "restore" ? "Restoring…" : "Restore sample data"}
              </button>
              <button className="secondary" onClick={onRemoveAll} disabled={!!samplesBusy}>
                {samplesBusy === "remove" ? "Removing…" : "Remove all samples"}
              </button>
            </div>
          </div>

          {!AUTH_DISABLED && <EmailPreferences />}
        </div>
      )}

      {tab === "api" && <ApiAccessPanel />}
    </div>
  );
}
