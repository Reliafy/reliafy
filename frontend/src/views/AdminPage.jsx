import { useEffect, useState } from "react";
import { getAdminStats, getAdminTraffic } from "../api.js";
import Select from "../components/Select.jsx";

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
        <div className="bill-head">
          <h2 style={{ margin: 0 }}>Traffic</h2>
          <div style={{ width: 170 }}>
            <Select value={days} onChange={setDays} options={RANGES} />
          </div>
        </div>
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
