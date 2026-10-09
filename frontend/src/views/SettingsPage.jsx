import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../AuthProvider.jsx";
import { useAppConfig } from "../ConfigProvider.jsx";
import ApiAccessPanel from "../components/ApiAccessPanel.jsx";
import ConnectedAppsPanel from "../components/ConnectedAppsPanel.jsx";
import { initials } from "../components/Sidebar.jsx";
import Button from "../components/ui/Button.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import {
  getBilling,
  restoreSamples,
  removeSamples,
  getEmailPreferences,
  setEmailPreferences,
} from "../api.js";
import { AUTH_DISABLED } from "../firebase.js";

const TABS = [
  { id: "general", label: "General" },
  { id: "api", label: "API access" },
  { id: "apps", label: "Connected apps" },
];

const PLAN_NAME = { free: "Free", agent: "Agent", pro: "Pro" };

// The plan at a glance: which plan, MCP calls against this period's
// allowance, and the way up. Only where this deployment has plans.
function PlanCard() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    getBilling()
      .then((d) => alive && setData(d))
      .catch(() => alive && setError("Couldn't load your plan."));
    return () => {
      alive = false;
    };
  }, []);

  const plan = data?.plan || "free";
  const mcp = data?.mcp || {};
  const n = (v) => (v ?? 0).toLocaleString();
  const quota = mcp.quota != null ? ` / ${n(mcp.quota)}` : "";
  return (
    <Card style={{ marginTop: "1rem" }}>
      <CardHeader
        title="Plan"
        actions={data && (
          <span className="chip-row">
            {data.admin && <Chip>Operator</Chip>}
            <Chip tone={plan === "free" ? "neutral" : "accent"}>{PLAN_NAME[plan] || plan}</Chip>
          </span>
        )}
      />
      {error ? (
        <p className="muted-line">{error}</p>
      ) : !data ? (
        <p className="muted-line">Loading…</p>
      ) : (
        <>
          <ul className="bill-usage">
            <li>
              <span>MCP calls {mcp.period === "day" ? "today" : "this month"}</span>
              <span className="bill-usage-n">{n(mcp.calls_used)}{quota}</span>
            </li>
          </ul>
          <div className="row set-plan-acts">
            {plan !== "pro" && !data.admin && (
              <Button onClick={() => navigate("/billing")}>Upgrade to Pro</Button>
            )}
            <Link className="evidence-link" to="/billing">Usage, limits and billing</Link>
          </div>
        </>
      )}
    </Card>
  );
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
    <Card style={{ marginTop: "1rem" }}>
      <CardHeader title="Emails" />
      <label className="set-check">
        <input
          type="checkbox"
          checked={!!updates}
          onChange={onToggle}
          disabled={updates === null || saving}
        />
        <span>
          <b>Product update emails</b> — a short monthly note on what's new, and a couple of getting-started tips when you join.
        </span>
      </label>
      <p className="muted-line" style={{ marginBottom: 0 }}>
        Emails you trigger yourself, like team invites and shares, aren't affected.
      </p>
      {error && <div className="error" style={{ marginBottom: 0 }}>{error}</div>}
    </Card>
  );
}

// Account settings — profile, sample data, and the ingestion API. The single
// home for account-level details that aren't billing (which stays on /billing).
export default function SettingsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { billing } = useAppConfig();

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
      <PageHeader title="Settings" />

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
          <Card>
            <CardHeader title="Profile" />
            <div className="set-profile">
              <span className="ava lg">{initials(user)}</span>
              <div>
                <div className="set-name">{user?.displayName || "—"}</div>
                <div className="muted-line">{user?.email || ""}</div>
              </div>
            </div>
          </Card>

          {billing && <PlanCard />}

          <Card style={{ marginTop: "1rem" }}>
            <CardHeader
              title="Sample data"
              subtitle="A fresh workspace comes with sample datasets, models, RBDs and studies to explore. Hiding them only changes your view; restore them any time."
            />
            <div className="row" style={{ gap: "0.6rem" }}>
              <Button variant="secondary" onClick={onRestore} disabled={!!samplesBusy}>
                {samplesBusy === "restore" ? "Restoring…" : "Restore sample data"}
              </Button>
              <Button variant="secondary" onClick={onRemoveAll} disabled={!!samplesBusy}>
                {samplesBusy === "remove" ? "Removing…" : "Remove all samples"}
              </Button>
            </div>
          </Card>

          {!AUTH_DISABLED && <EmailPreferences />}
        </div>
      )}

      {tab === "api" && <ApiAccessPanel />}
      {tab === "apps" && <ConnectedAppsPanel />}
    </div>
  );
}
