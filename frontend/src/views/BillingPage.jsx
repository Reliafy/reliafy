import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { getBilling, buyCredits, subscribePro, billingPortal } from "../api.js";
import { PRO_PRICE } from "../pricing.js";
import { useAppConfig } from "../ConfigProvider.jsx";
import Chip from "../components/ui/Chip.jsx";
import { CardHeader } from "../components/ui/Card.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";

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
  ["Outage logs", "outage_logs"],
];

export default function BillingPage() {
  const location = useLocation();
  const { ai, reliability_agent: agentEnabled } = useAppConfig();
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

  // Credits only buy AI use (the assistant, the Reliability Agent): without
  // either there's nothing to buy.
  const hasCredits = ai || agentEnabled;
  const title = hasCredits ? "Billing & credits" : "Billing";
  if (error && !data) {
    return (
      <div className="app">
        <PageHeader title={title} />
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!data) {
    return <div className="app"><div className="card empty">Loading…</div></div>;
  }

  // free | pro — or agent: the retired Agent plan (MCP only), which existing
  // subscribers keep until they cancel. It isn't sold or compared any more.
  const plan = data.plan || "free";
  const isPro = plan === "pro";
  const isAgent = plan === "agent";
  const isAdmin = !!data.admin;
  const noCaps = isPro || isAdmin; // operators are exempt from caps too
  const caps = data.caps || {}; // the Free plan's caps
  const myCaps = data.plan_caps || caps; // the caps that apply to this user
  const usage = data.usage || {};
  const mcp = data.mcp || {};
  const num = (v) => (v ?? 0).toLocaleString();

  // Free vs Pro comparison. Only non-Pro cloud users have something to
  // compare against: operators are exempt from caps, and self-hosted
  // installs (billing off) have no paid plans at all.
  const showCompare = !isPro && !isAdmin && !!data.billing_enabled;
  const proCredits = data.pro_monthly_credit_cents > 0 ? credits(data.pro_monthly_credit_cents) : null;
  const starterCredits = data.free_grant_cents > 0 ? credits(data.free_grant_cents) : null;
  const packsOnly = starterCredits ? `${starterCredits} starter credits, then buy packs` : "Buy credit packs";
  // Every value here reflects how the backend actually gates the feature:
  // caps from usage_summary, api_access_allowed (Pro only — the REST API; MCP
  // is unlimited on Pro, a small monthly allowance on Free), teams.py (create
  // is Pro only), and reliability_agent.py (Pro or any purchased credits).
  const compareRows = [
    ...ARTIFACTS.map(([label, key]) => ({ label, free: caps[key] ?? "—", pro: "Unlimited", mono: true })),
    ai && {
      label: "AI assistant (metered)",
      free: packsOnly,
      pro: proCredits ? `${proCredits} credits included every month, plus packs` : "Buy credit packs",
    },
    agentEnabled && { label: "Reliability Agent", free: "With purchased credits", pro: "Included" },
    {
      label: "Availability simulation (repairable RBDs)",
      free: "View saved results; run locally via Download as Python",
      pro: "Included",
    },
    {
      label: "Use Reliafy from AI agents (MCP)",
      free: data.mcp_free_monthly_calls > 0
        ? `${num(data.mcp_free_monthly_calls)} tool calls a month to try it (no fitting or fleets)`
        : "—",
      pro: "Unlimited",
    },
    { label: "Programmatic API & data ingestion", free: "—", pro: "Included" },
    { label: "Team workspaces", free: "Join teams (view-only)", pro: "Create teams and edit together" },
  ].filter(Boolean);
  // Pro exists (pricing.js); it can only be bought where Stripe is set up.
  const noPayments = (
    <p className="muted-line">Payments aren't set up on this environment, so Pro can't be bought here.</p>
  );
  const planName = { free: "Free", agent: "Agent", pro: "Pro" }[plan] || "Free";
  const current = (p) => (plan === p ? <Chip tone="accent">Current</Chip> : null);

  return (
    <div className="app">
      <PageHeader title={title} />

      {status === "success" && <div className="card notice-ok">Payment received — your account will update momentarily.</div>}
      {status === "cancel" && <div className="card">Checkout cancelled.</div>}
      {error && <div className="card error">{error}</div>}

      {showCompare && (
        <div className="card bill-card bill-compare">
          <CardHeader
            title="Free vs Pro"
            actions={
              <span className="bill-compare-price">
                {PRO_PRICE.amount}<span className="bill-compare-per">{PRO_PRICE.per}</span>
              </span>
            }
          />
          <div className="bill-compare-wrap">
            <table className="bill-compare-table">
              <thead>
                <tr>
                  <th scope="col" aria-label="Feature"></th>
                  <th scope="col">Free {current("free")}</th>
                  <th scope="col">Pro</th>
                </tr>
              </thead>
              <tbody>
                {compareRows.map((r) => (
                  <tr key={r.label}>
                    <th scope="row">{r.label}</th>
                    <td className={r.mono ? "bill-compare-n" : ""}>{r.free}</td>
                    <td className="bill-compare-pro">{r.pro}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.pro_available ? (
            <div className="bill-compare-cta">
              <button disabled={working === "pro"} onClick={() => go("pro", subscribePro)}>
                {working === "pro" ? "Redirecting…" : `${isAgent ? "Upgrade" : "Subscribe"} to Pro — ${PRO_PRICE.amount}/month`}
              </button>
              <span className="muted-line">
                {isAgent
                  ? "Upgrading moves your Agent subscription to Pro, prorated — no second subscription."
                  : "You'll be taken to Stripe Checkout to enter a card. Cancel anytime from this page."}
              </span>
            </div>
          ) : (
            noPayments
          )}
        </div>
      )}

      <div className="bill-grid">
        {/* Plan */}
        <div className="card bill-card">
          <CardHeader
            title="Plan"
            actions={
              <span className="chip-row">
                {isAdmin && <Chip>Operator</Chip>}
                <Chip tone={plan === "free" ? "neutral" : "accent"}>{planName}</Chip>
              </span>
            }
          />
          {isAdmin && (
            <p className="muted-line">Operator account — plan limits and AI charges don't apply to you.</p>
          )}
          {isAgent && (
            <p className="muted-line">
              You're on the Agent plan (Reliafy from your AI agent over MCP). It's no longer offered, but yours
              continues until you cancel it.
            </p>
          )}
          <ul className="bill-usage">
            {ARTIFACTS.map(([label, key]) => (
              <li key={key}>
                <span>{label}</span>
                <span className="bill-usage-n">{num(usage[key])} / {noCaps || myCaps[key] == null ? "Unlimited" : num(myCaps[key])}</span>
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
          {isPro && ai && proCredits && (
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
              noPayments
            )
          )}
          {!isPro && !showCompare && !isAdmin && (
            <p className="muted-line">
              Pro lifts the free-tier limits on saved datasets, models, and RBDs
              {ai && proCredits && ` — and includes ${proCredits} AI credits every month`}.
            </p>
          )}
        </div>

        {/* MCP use against a quota: Free's monthly allowance or the
            grandfathered Agent plan's daily quota. Pro and operators have
            none. */}
        {data.billing_enabled && !isAdmin && plan === "free" && mcp.period === "month" && (
          <div className="card bill-card">
            <CardHeader title="Your AI agent (MCP)" />
            <ul className="bill-usage">
              <li>
                <span>Tool calls this month</span>
                <span className="bill-usage-n">{num(mcp.calls_used)} / {num(mcp.quota)}</span>
              </li>
            </ul>
            <p className="muted-line">
              Free includes {num(mcp.quota)} tool calls a month to try Reliafy from your AI agent
              (everything except fitting, fleets and availability simulation); they reset on the 1st
              (UTC). Pro removes the limit.
            </p>
          </div>
        )}
        {data.billing_enabled && isAgent && !isAdmin && mcp.daily_quota != null && (
          <div className="card bill-card">
            <CardHeader title="Your AI agent (MCP)" />
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
              the <a href="/api-docs#mcp">API docs</a>. Pro removes the daily limit and fits in Reliafy.
            </p>
          </div>
        )}

        {/* Credits: only where there's AI to spend them on. */}
        {hasCredits && (
          <div className="card bill-card">
            <CardHeader title="AI credits" actions={<span className="bill-balance">{credits(data.credit_cents)}<span className="bill-balance-unit">credits</span></span>} />
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
        )}
      </div>
    </div>
  );
}
