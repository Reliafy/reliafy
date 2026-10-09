import { useEffect, useState } from "react";
import { getAdminEmailCampaigns, getAdminStats, getAdminTraffic } from "../api.js";
import Select from "../components/Select.jsx";
import UsageSection from "../components/UsageSection.jsx";
import { CardHeader } from "../components/ui/Card.jsx";

const LABELS = {
  datasets: "Datasets",
  models: "Models",
  rbds: "RBDs",
  degradation_models: "Degradation models",
  tracked_items: "Tracked items",
  strategy_analyses: "Strategy analyses",
  rcm_studies: "RCM studies",
};

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "14", label: "Last 14 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

// Simple inline bar chart: one row per day, width scaled to the max.
function DailyBars({ daily }) {
  const max = Math.max(1, ...daily.map((d) => d.pageviews));
  return (
    <div className="traffic-days">
      {daily.map((d) => (
        <div key={d.day} className="traffic-day">
          <span className="traffic-date">{d.day.slice(5)}</span>
          <span className="traffic-bar-wrap">
            <span className="traffic-bar" style={{ width: `${(d.pageviews / max) * 100}%` }} />
          </span>
          <span className="traffic-nums">
            {d.pageviews} views · {d.visitors} visitors
          </span>
        </div>
      ))}
    </div>
  );
}

function TopList({ title, rows, empty }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted-line">{empty}</p>
      ) : (
        <ul className="bill-usage">
          {rows.map((r) => (
            <li key={r.key}>
              <span className="traffic-key">{r.key}</span>
              <span className="bill-usage-n">{r.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// What each email brought in (#269): one row per update / lifecycle email.
// Visitors are visitor-days (daily-hashed), pages are those reached in a
// tagged visit, and "Active" counts recipients using the app within a few
// days of their send.
function EmailCampaigns() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    getAdminEmailCampaigns().then(setData).catch((e) => setError(e.message));
  }, []);
  const rows = data?.campaigns || [];
  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <h2>Email campaigns (last {data?.days ?? 90} days)</h2>
      {error ? (
        <p className="muted-line">{error}</p>
      ) : !data ? (
        <p className="muted-line">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted-line">No emails sent or tagged visits yet.</p>
      ) : (
        <div className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Sent</th>
                <th>Visitors</th>
                <th>Pageviews</th>
                <th>Active ≤{data.active_days}d</th>
                <th style={{ textAlign: "left" }}>Pages reached</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={`${r.medium}:${r.campaign}`}>
                  <td className="usage-key">{r.medium} · {r.campaign}</td>
                  <td>{r.sent}</td>
                  <td>{r.visitors}</td>
                  <td>{r.pageviews}</td>
                  <td>{r.active == null ? "—" : r.active}</td>
                  <td style={{ textAlign: "left" }}>
                    {r.top_pages.map((p) => `${p.key} (${p.count})`).join(", ") || "—"}
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

// Operator dashboard (ADMIN_EMAILS accounts only): signups, plans, volumes,
// and first-party traffic (no cookies, no third parties, 90-day retention).
export default function AdminPage() {
  const [stats, setStats] = useState(null);
  const [traffic, setTraffic] = useState(null);
  const [days, setDays] = useState("14");
  const [error, setError] = useState(null);

  useEffect(() => {
    getAdminStats().then(setStats).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    getAdminTraffic(Number(days)).then(setTraffic).catch((e) => setError(e.message));
  }, [days]);

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
          <p>Live counts straight from the database. Traffic is first-party — no cookies, daily-hashed visitors, 90-day retention.</p>
        </div>
      </header>

      <div className="stats">
        <div className="stat"><div className="k">Users</div><div className="v">{stats.users_total}</div></div>
        <div className="stat"><div className="k">New (7 days)</div><div className="v">{stats.users_new_7d}</div></div>
        <div className="stat"><div className="k">Pro subscribers</div><div className="v">{stats.pro_users}</div></div>
        <div className="stat"><div className="k">Teams</div><div className="v">{stats.teams}</div></div>
        <div className="stat"><div className="k">Shares</div><div className="v">{stats.shares}</div></div>
        {traffic && (
          <>
            <div className="stat"><div className="k">Pageviews ({traffic.days}d)</div><div className="v">{traffic.pageviews}</div></div>
            <div className="stat"><div className="k">Visitor-days ({traffic.days}d)</div><div className="v">{traffic.visitors_daily_sum}</div></div>
          </>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <CardHeader
          title="Traffic"
          actions={
            <div style={{ width: 170 }}>
              <Select value={days} onChange={setDays} options={RANGES} />
            </div>
          }
        />
        {!traffic ? (
          <p className="muted-line">Loading…</p>
        ) : traffic.pageviews === 0 ? (
          <p className="muted-line">No pageviews recorded in this window yet.</p>
        ) : (
          <DailyBars daily={traffic.daily} />
        )}
      </div>

      {traffic && (
        <div className="dash-cards" style={{ marginTop: "1rem" }}>
          <TopList title="Top pages" rows={traffic.top_pages} empty="Nothing yet." />
          <TopList title="Referrers" rows={traffic.top_referrers} empty="No external referrers yet." />
          <TopList
            title="Campaigns (utm_source)"
            rows={traffic.top_sources}
            empty="No tagged campaigns yet — add ?utm_source=… to links you post."
          />
        </div>
      )}

      {traffic && traffic.events.length > 0 && (
        <TopList title="Product events" rows={traffic.events} empty="" />
      )}

      <EmailCampaigns />

      <UsageSection />

      <div className="card" style={{ marginTop: "1rem" }}>
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
