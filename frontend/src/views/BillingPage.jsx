import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getBilling, buyCredits, subscribePro, billingPortal } from "../api.js";

const fmt = (cents) => `$${((cents || 0) / 100).toFixed(2)}`;

export default function BillingPage() {
  const location = useLocation();
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [working, setWorking] = useState("");

  const status = new URLSearchParams(location.search).get("status");

  const refresh = useCallback(() => {
    getBilling().then(setData).catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  // Stripe Checkout / portal: get a URL from the backend and redirect to it.
  const go = async (label, fn) => {
    setWorking(label);
    setError(null);
    try {
      const { url } = await fn();
      window.location.href = url;
    } catch (e) {
      setError(e.message);
      setWorking("");
    }
  };

  if (error && !data) {
    return (
      <div className="app">
        <header><h1>Billing &amp; credits</h1></header>
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!data) {
    return <div className="app"><div className="card empty">Loading…</div></div>;
  }

  const isPro = data.plan === "pro";
  const caps = data.caps || {};
  const usage = data.usage || {};

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">Account / <b>Billing &amp; credits</b></div>
          <h1>Billing &amp; credits</h1>
          <p>Manage your plan and AI credits. The assistant draws on your credit balance as you use it.</p>
        </div>
      </header>

      {status === "success" && <div className="card notice-ok">Payment received — your account will update momentarily.</div>}
      {status === "cancel" && <div className="card">Checkout cancelled.</div>}
      {error && <div className="card error">{error}</div>}
      {!data.stripe_enabled && (
        <div className="card">Payments aren't configured on this environment yet.</div>
      )}

      <div className="bill-grid">
        {/* Plan */}
        <div className="card bill-card">
          <div className="bill-head"><h2>Plan</h2><span className={"plan-badge " + (isPro ? "pro" : "free")}>{isPro ? "Pro" : "Free"}</span></div>
          <ul className="bill-usage">
            {[["Datasets", "datasets"], ["Models", "models"], ["RBDs", "rbds"]].map(([label, key]) => (
              <li key={key}>
                <span>{label}</span>
                <span className="bill-usage-n">{usage[key] ?? 0}{isPro ? "" : ` / ${caps[key]}`}</span>
              </li>
            ))}
          </ul>
          {isPro ? (
            <button className="secondary" disabled={working === "portal"} onClick={() => go("portal", billingPortal)}>
              {working === "portal" ? "Opening…" : "Manage subscription"}
            </button>
          ) : data.pro_available ? (
            <button disabled={working === "pro"} onClick={() => go("pro", subscribePro)}>
              {working === "pro" ? "Redirecting…" : "Upgrade to Pro"}
            </button>
          ) : (
            <p className="muted-line">Pro plan coming soon.</p>
          )}
          {!isPro && <p className="muted-line">Pro lifts the free-tier limits on saved datasets, models, and RBDs.</p>}
        </div>

        {/* Credits */}
        <div className="card bill-card">
          <div className="bill-head"><h2>AI credits</h2><span className="bill-balance">{fmt(data.credit_cents)}</span></div>
          <p className="muted-line">Top up your balance to use the AI assistant. Credits never expire.</p>
          <div className="bill-packs">
            {(data.packs || []).map((p) => (
              <button
                key={p.id}
                className="bill-pack"
                disabled={!data.stripe_enabled || working === p.id}
                onClick={() => go(p.id, () => buyCredits(p.id))}
              >
                <span className="bill-pack-price">{p.label}</span>
                <span className="bill-pack-credits">{fmt(p.grant_cents)} credits</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
