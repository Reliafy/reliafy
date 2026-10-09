import { useEffect, useState } from "react";
import {
  getAdminEmailCampaigns,
  getAdminSignups,
  getAdminStats,
  getAdminTraffic,
  getAdminUsage,
} from "../api.js";
import { relativeTime } from "../instrument.js";
import Select from "../components/Select.jsx";
import UsageSection from "../components/UsageSection.jsx";
import Card, { CardHeader } from "../components/ui/Card.jsx";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import { ResultDetails } from "../components/ui/ResultSummary.jsx";

const LABELS = {
  datasets: "Datasets",
  models: "Models",
  rbds: "RBDs",
  degradation_models: "Degradation models",
  tracked_items: "Tracked items",
  tracked_fleets: "Tracked fleets",
  strategy_analyses: "Strategy analyses",
  rcm_studies: "RCM studies",
  fleets: "Fleet forecasts",
};

// One range drives the whole page. Traffic and account-level usage keep 90
// days, so that's the longest window.
const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
];

const PLAN = { free: "Free", pro: "Pro", agent: "Agent" };
const n = (v) => (v ?? 0).toLocaleString();

// Fetch on every change of the dependencies; { data, error } with data null
// while loading.
function useLoad(fn, deps) {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let alive = true;
    setState({ data: null, error: null });
    fn()
      .then((data) => alive && setState({ data, error: null }))
      .catch((e) => alive && setState({ data: null, error: e.message }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return state;
}

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
    <Card>
      <CardHeader title={title} />
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
    </Card>
  );
}

// The latest accounts: who to welcome or follow up with.
function RecentSignups({ state }) {
  const { data, error } = state;
  const rows = data?.signups || [];
  return (
    <Card>
      <CardHeader
        title="Recent signups"
        subtitle={data && data.count > rows.length ? `Latest ${rows.length} of ${n(data.count)}` : null}
      />
      {error ? (
        <p className="muted-line">{error}</p>
      ) : !data ? (
        <p className="muted-line">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="muted-line">No new accounts in this window.</p>
      ) : (
        <div className="usage-table-wrap">
          <table className="usage-table admin-signups">
            <thead>
              <tr>
                <th>Email</th>
                <th>Plan</th>
                <th>Joined</th>
                <th>Last active</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.email}-${i}`}>
                  <td className="admin-email">{r.email || "—"}</td>
                  <td>{r.plan === "free" ? PLAN.free : <Chip tone="accent">{PLAN[r.plan] || r.plan}</Chip>}</td>
                  <td>{relativeTime(r.joined)}</td>
                  <td>{relativeTime(r.last_active)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// What each email brought in (#269): one row per update / lifecycle email.
// Visitors are visitor-days (daily-hashed), pages are those reached in a
// tagged visit, and "Active" counts recipients using the app within a few
// days of their send.
function EmailCampaigns({ state }) {
  const { data, error } = state;
  const rows = data?.campaigns || [];
  if (error) return <p className="muted-line">{error}</p>;
  if (!data) return <p className="muted-line">Loading…</p>;
  if (rows.length === 0) return <p className="muted-line">No emails sent or tagged visits in this window.</p>;
  return (
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
  );
}

// Operator dashboard (ADMIN_EMAILS accounts only): the week's answer in one
// tile row, then product usage and MCP, then traffic, with emails and artifact
// volumes folded away at the end.
export default function AdminPage() {
  const [days, setDays] = useState("7");
  const [includeAdmin, setIncludeAdmin] = useState(false);
  const d = Number(days);

  const stats = useLoad(getAdminStats, []);
  const signups = useLoad(() => getAdminSignups(d), [d]);
  const usage = useLoad(() => getAdminUsage(d, includeAdmin), [d, includeAdmin]);
  const trafficState = useLoad(() => getAdminTraffic(d), [d]);
  const emails = useLoad(() => getAdminEmailCampaigns(d), [d]);
  const traffic = trafficState.data;
  const s = stats.data;
  const u = usage.data;

  const header = (
    <PageHeader
      title="Operator stats"
      actions={
        <div className="admin-range">
          <Select value={days} onChange={setDays} options={RANGES} title="Date range for the whole page" />
        </div>
      }
    />
  );

  if (stats.error) {
    return (
      <div className="app">
        {header}
        <Card className="empty"><p>{stats.error}</p></Card>
      </div>
    );
  }
  if (!s) return <div className="app">{header}<Card className="empty">Loading…</Card></div>;

  const dash = (v) => (v == null ? "…" : n(v));
  const errors = u?.totals?.errors;

  return (
    <div className="app">
      {header}

      <div className="stats admin-tiles">
        <div className="stat"><div className="k">New signups</div><div className="v">{dash(signups.data?.count)}</div></div>
        <div className="stat"><div className="k">Active accounts</div><div className="v">{dash(u?.share?.any_accounts)}</div></div>
        <div className="stat"><div className="k">MCP calls</div><div className="v">{dash(u?.totals?.mcp)}</div></div>
        <div className="stat"><div className="k">MCP-active accounts</div><div className="v">{dash(u?.share?.mcp_accounts)}</div></div>
        <div className="stat"><div className="k">MCP errors</div><div className="v">{dash(errors?.mcp)}</div></div>
        <div className="stat"><div className="k">Pro subscribers</div><div className="v">{n(s.pro_users)}</div></div>
      </div>
      <p className="admin-minor">
        {n(s.users_total)} users · {n(s.teams)} teams · {n(s.shares)} shares
        {traffic && <> · {n(traffic.pageviews)} pageviews · {n(traffic.visitors_daily_sum)} visitor-days</>}
        {errors && <> · {n(errors.app)} failed app calls{errors.api > 0 && <> · {n(errors.api)} failed API calls</>}</>}
      </p>

      <RecentSignups state={signups} />

      <UsageSection
        state={usage}
        includeAdmin={includeAdmin}
        onIncludeAdmin={setIncludeAdmin}
      />

      <Card style={{ marginTop: "1rem" }}>
        <CardHeader title="Traffic" />
        {trafficState.error ? (
          <p className="muted-line">{trafficState.error}</p>
        ) : !traffic ? (
          <p className="muted-line">Loading…</p>
        ) : traffic.pageviews === 0 ? (
          <p className="muted-line">No pageviews recorded in this window.</p>
        ) : (
          <DailyBars daily={traffic.daily} />
        )}
      </Card>

      {traffic && traffic.pageviews > 0 && (
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
        <div style={{ marginTop: "1rem" }}>
          <TopList title="Product events" rows={traffic.events} empty="" />
        </div>
      )}

      <Card className="admin-fold">
        <ResultDetails summary="Email campaigns">
          <EmailCampaigns state={emails} />
        </ResultDetails>
      </Card>

      <Card className="admin-fold">
        <ResultDetails summary="Artifacts (excluding samples)">
          <div className="stats admin-artifacts">
            {Object.entries(s.artifacts).map(([key, count]) => (
              <div className="stat" key={key}>
                <div className="k">{LABELS[key] || key}</div>
                <div className="v">{n(count)}</div>
              </div>
            ))}
          </div>
        </ResultDetails>
      </Card>

      <p className="admin-foot">
        Live counts straight from the database. Traffic is first-party: no cookies,
        daily-hashed visitors, 90-day retention.
      </p>
    </div>
  );
}
