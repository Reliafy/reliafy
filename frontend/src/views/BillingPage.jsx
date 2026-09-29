import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getBilling, buyCredits, subscribePro, subscribeAgent, billingPortal } from "../api.js";
import { AGENT_PRICE, PRO_PRICE } from "../pricing.js";

// AI usage is denominated in "credits" — users never see a dollar balance.
// (Internally 1 credit == 1 cent; only pack purchase prices show as dollars.)
const credits = (cents) => (cents || 0).toLocaleString();

// Capped artifact kinds, in display order. Keys match `caps` / `usage` in the
// GET /api/billing response (backend/services/billing.py usage_summary).
const ARTIFACTS = [
  ["Datasets", "datasets"],
  ["Models", "models"],
  ["RBDs", "rbds"],
  ["Degradation models", "degradation_models"],
  ["Tracked items", "tracked_items"],
  ["RCM studies", "rcm_studies"],
  ["Fleet forecasts", "fleets"],
];

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

  const plan = data.plan || "free"; // free | agent | pro
  const isPro = plan === "pro";
  const isAgent = plan === "agent";
  const isAdmin = !!data.admin;
  const noCaps = isPro || isAdmin; // operators are exempt from caps too
  const caps = data.caps || {}; // the Free plan's caps
  const agentCaps = data.agent_caps || {};
  const myCaps = data.plan_caps || caps; // the caps that apply to this user
  const usage = data.usage || {};
  const mcp = data.mcp || {};
  const num = (v) => (v ?? 0).toLocaleString();

  // Free vs (Agent vs) Pro comparison. Only Free/Agent cloud users have
  // something to compare against: operators are exempt from caps, and
  // self-hosted installs (billing off) have no paid plans at all.
  const showCompare = !isPro && !isAdmin && !!data.billing_enabled;
  const showAgent = !!data.agent_available || isAgent;
  const proCredits = data.pro_monthly_credit_cents > 0 ? credits(data.pro_monthly_credit_cents) : null;
  const starterCredits = data.free_grant_cents > 0 ? credits(data.free_grant_cents) : null;
  const packsOnly = starterCredits ? `${starterCredits} starter credits, then buy packs` : "Buy credit packs";
  // Every value here reflects how the backend actually gates the feature:
  // caps from usage_summary, api_access_allowed (Pro only), teams.py (create
  // is Pro only), reliability_agent.py (Pro or any purchased credits), and
  // mcp_server.py (fitting Pro-only; a daily tool-call quota on Free/Agent).
  const compareRows = [
    ...ARTIFACTS.map(([label, key]) => ({
      label, free: caps[key] ?? "—", agent: agentCaps[key] ?? "—", pro: "Unlimited", mono: true,
    })),
    {
      label: "Use from your AI agent (MCP)",
      free: `${num(data.mcp_free_daily_calls)} tool calls/day`,
      agent: `${num(data.mcp_agent_daily_calls)} tool calls/day`,
      pro: "No daily limit",
    },
    { label: "Fitting from your agent", free: "Locally with SurPyval", agent: "Locally with SurPyval", pro: "Included" },
    {
      label: "AI assistant (metered)",
      free: packsOnly,
      agent: packsOnly,
      pro: proCredits ? `${proCredits} credits included every month, plus packs` : "Buy credit packs",
    },
    { label: "Reliability Agent", free: "With purchased credits", agent: "With purchased credits", pro: "Included" },
    {
      label: "Availability simulation (repairable RBDs)",
      free: "View saved results; run locally via Download as Python",
      agent: "View saved results; run locally via Download as Python",
      pro: "Included",
    },
    { label: "Programmatic API & data ingestion", free: "—", agent: "—", pro: "Included" },
    { label: "Team workspaces", free: "Join teams (view-only)", agent: "Join teams (view-only)", pro: "Create teams and edit together" },
  ];
  const planName = { free: "Free", agent: "Agent", pro: "Pro" }[plan] || "Free";
  const current = (p) => (plan === p ? <span className={"plan-badge " + p}>current</span> : null);
  const subscribeButtons = (
    <>
      {data.agent_available && !isAgent && (
        <button className="secondary" disabled={working === "agent"} onClick={() => go("agent", subscribeAgent)}>
          {working === "agent" ? "Redirecting…" : `Subscribe to Agent — ${AGENT_PRICE.amount}/month`}
        </button>
      )}
      {data.pro_available && (
        <button disabled={working === "pro"} onClick={() => go("pro", subscribePro)}>
          {working === "pro" ? "Redirecting…" : `${isAgent ? "Upgrade" : "Subscribe"} to Pro — ${PRO_PRICE.amount}/month`}
        </button>
      )}
    </>
  );

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

      {showCompare && (
        <div className="card bill-card bill-compare">
          <div className="bill-head">
            <h2>{showAgent ? "Free, Agent and Pro" : "Free vs Pro"}</h2>
            <span className="bill-compare-price">
              {PRO_PRICE.amount}<span className="bill-compare-per">{PRO_PRICE.per}</span>
            </span>
          </div>
          {showAgent && (
            <p className="muted-line">
              Agent ({AGENT_PRICE.amount}/month) is for using Reliafy from your AI agent over MCP — Claude or
              any MCP client — with no web app features. Your agent fits data locally with SurPyval and saves
              the result here.
            </p>
          )}
          <div className="bill-compare-wrap">
            <table className={"bill-compare-table" + (showAgent ? " three" : "")}>
              <thead>
                <tr>
                  <th scope="col" aria-label="Feature"></th>
                  <th scope="col">Free {current("free")}</th>
                  {showAgent && <th scope="col">Agent {current("agent")}</th>}
                  <th scope="col">Pro</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.map((r) => (
                  <tr key={r.label}>
                    <th scope="row">{r.label}</th>
                    <td className={r.mono ? "bill-compare-n" : ""}>{r.free}</td>
                    {showAgent && <td className={r.mono ? "bill-compare-n" : ""}>{r.agent}</td>}
                    <td className="bill-compare-pro">{r.pro}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.pro_available || data.agent_available ? (
            <div className="bill-compare-cta">
              {subscribeButtons}
              <span className="muted-line">
                {isAgent
                  ? "Upgrading moves your Agent subscription to Pro, prorated — no second subscription."
                  : "You'll be taken to Stripe Checkout to enter a card. Cancel anytime from this page."}
              </span>
            </div>
          ) : (
            <p className="muted-line">Pro plan coming soon.</p>
          )}
        </div>
      )}

      <div className="bill-grid">
        {/* Plan */}
        <div className="card bill-card">
          <div className="bill-head">
            <h2>Plan</h2>
            <span style={{ display: "inline-flex", gap: 6 }}>
              {isAdmin && <span className="plan-badge admin">Operator</span>}
              <span className={"plan-badge " + plan}>{planName}</span>
            </span>
          </div>
          {isAdmin && (
            <p className="muted-line">Operator account — plan limits and AI charges don't apply to you.</p>
          )}
          <ul className="bill-usage">
            {ARTIFACTS.map(([label, key]) => (
              <li key={key}>
                <span>{label}</span>
                <span className="bill-usage-n">{usage[key] ?? 0}{noCaps ? "" : ` / ${myCaps[key]}`}</span>
              </li>
            ))}
          </ul>
          <p className="muted-line">
            Usage shown is your personal workspace — team workspaces have
            unlimited saves.
          </p>
          {(isPro || isAgent) && (
            <button className="secondary" disabled={working === "portal"} onClick={() => go("portal", billingPortal)}>
              {working === "portal" ? "Opening…" : "Manage subscription"}
            </button>
          )}
          {isPro && proCredits && (
            <p className="muted-line">Your plan includes {proCredits} AI credits each month.</p>
          )}
          {/* Free users on the cloud get the subscribe button under the
              comparison above; operators / self-host keep the plain one. */}
          {!isPro && !showCompare && (
            data.pro_available ? (
              <button disabled={working === "pro"} onClick={() => go("pro", subscribePro)}>
                {working === "pro" ? "Redirecting…" : "Upgrade to Pro"}
              </button>
            ) : (
              <p className="muted-line">Pro plan coming soon.</p>
            )
          )}
          {!isPro && !showCompare && (
            <p className="muted-line">
              Pro lifts the free-tier limits on saved datasets, models, and RBDs
              {proCredits && ` — and includes ${proCredits} AI credits every month`}.
            </p>
          )}
        </div>

        {/* MCP use today (Free / Agent: Pro and operators have no daily quota) */}
        {data.billing_enabled && !isPro && !isAdmin && mcp.daily_quota != null && (
          <div className="card bill-card">
            <div className="bill-head">
              <h2>Your AI agent (MCP)</h2>
              <span className={"plan-badge " + plan}>{planName}</span>
            </div>
            <ul className="bill-usage">
              <li>
                <span>Tool calls today</span>
                <span className="bill-usage-n">{num(mcp.calls_today)} / {num(mcp.daily_quota)}</span>
              </li>
              <li>
                <span>Fitting</span>
                <span className="bill-usage-n">Locally with SurPyval</span>
              </li>
              <li>
                <span>Availability simulations</span>
                <span className="bill-usage-n">Locally via Download as Python</span>
              </li>
            </ul>
            <p className="muted-line">
              The daily limit resets at 00:00 UTC. Connect Claude or another MCP client from
              the <a href="/api-docs#mcp">API docs</a>.
              {isAgent && " Pro removes the daily limit and fits in Reliafy."}
              {!isAgent && data.agent_available &&
                ` Agent (${AGENT_PRICE.amount}/month) raises it to ${num(data.mcp_agent_daily_calls)} calls a day.`}
            </p>
          </div>
        )}

        {/* Credits */}
        <div className="card bill-card">
          <div className="bill-head"><h2>AI credits</h2><span className="bill-balance">{credits(data.credit_cents)}<span className="bill-balance-unit">credits</span></span></div>
          <p className="muted-line">The assistant draws on your credit balance as you use it. Credits never expire.</p>
          <div className="bill-packs">
            {(data.packs || []).map((p) => (
              <button
                key={p.id}
                className="bill-pack"
                disabled={!data.stripe_enabled || working === p.id}
                onClick={() => go(p.id, () => buyCredits(p.id))}
              >
                <span className="bill-pack-price">{p.label}</span>
                <span className="bill-pack-credits">{credits(p.grant_cents)} credits</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
