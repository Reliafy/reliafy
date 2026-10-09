import { useEffect, useState } from "react";
import { getAdminUsage } from "../api.js";
import Plot from "./Plot.jsx";
import { COLORWAY, DANGER, SUBTLE } from "../plotTheme.js";
import Select from "./Select.jsx";

// Product usage for the operator dashboard (GET /api/admin/usage): how the
// app, MCP and the API are used, and the MCP plan wall — the numbers behind
// "does MCP use justify an agent-only plan?".

const RANGES = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last 90 days" },
  { value: "365", label: "Last 365 days" },
];

// App, MCP and API take the theme's first three series colours; the plan-wall
// outcomes are a caveat (limit), bad (Pro only) and neutral (repeat).
const COLORS = { app: COLORWAY[0], mcp: COLORWAY[1], api: COLORWAY[2], limit: COLORWAY[1], pro_only: DANGER, repeat: SUBTLE };

const LAYOUT = {
  height: 260,
  yaxis: { rangemode: "tozero" },
  hovermode: "x unified",
};

const pct = (x) => `${Math.round((x || 0) * 1000) / 10}%`;
const n = (v) => (v ?? 0).toLocaleString();

function Chart({ traces, barmode, category }) {
  const layout = { ...LAYOUT, ...(barmode ? { barmode } : {}) };
  // Week labels aren't dates to Plotly (a "*" marks a partial week).
  if (category) layout.xaxis = { ...LAYOUT.xaxis, type: "category" };
  return (
    <Plot data={traces} layout={layout} />
  );
}

function line(x, y, name, color) {
  return { type: "scatter", mode: "lines+markers", x, y, name, line: { color, width: 1.6 }, marker: { color, size: 4 } };
}

// A ranked table: key, total and the outcome columns that matter for it.
function OutcomeTable({ title, rows, columns, empty }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {rows.length === 0 ? (
        <p className="muted-line">{empty}</p>
      ) : (
        <div className="usage-table-wrap">
          <table className="usage-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Calls</th>
                {columns.map(([key, label]) => <th key={key}>{label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="usage-key">{r.key}</td>
                  <td>{n(r.count)}</td>
                  {columns.map(([key]) => (
                    <td key={key}>{key === "avg_ms" ? (r.avg_ms != null ? n(r.avg_ms) : "—") : n(r[key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function KeyList({ title, rows, empty }) {
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
              <span className="bill-usage-n">{n(r.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function UsageSection() {
  const [days, setDays] = useState("30");
  const [includeAdmin, setIncludeAdmin] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setError(null);
    getAdminUsage(Number(days), includeAdmin).then(setData).catch((e) => setError(e.message));
  }, [days, includeAdmin]);

  const header = (
    <div className="bill-head">
      <h2 style={{ margin: 0 }}>Product usage</h2>
      <div className="usage-controls">
        <label className="usage-check">
          <input type="checkbox" checked={includeAdmin} onChange={(e) => setIncludeAdmin(e.target.checked)} />
          Include operator accounts
        </label>
        <div style={{ width: 170 }}>
          <Select value={days} onChange={setDays} options={RANGES} />
        </div>
      </div>
    </div>
  );

  if (error) return <div className="card" style={{ marginTop: "1rem" }}>{header}<p className="muted-line">{error}</p></div>;
  if (!data) return <div className="card" style={{ marginTop: "1rem" }}>{header}<p className="muted-line">Loading…</p></div>;

  const x = data.daily.map((d) => d.day);
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const weekLabel = (w) => {
    const [, m, d] = w.week.split("-");
    return `${Number(d)} ${MONTHS[Number(m) - 1]}${w.partial ? " *" : ""}`;
  };
  const weeks = data.weekly.map(weekLabel);
  const wall = data.pro_wall;
  const share = data.share;
  const windowDays = data.window_days;
  const outcomeCols = [["ok", "OK"], ["limit", "Limit"], ["pro_only", "Pro-only"], ["locked", "Locked"], ["error", "Error"]];

  return (
    <>
      <div className="card" style={{ marginTop: "1rem" }}>
        {header}
        <p className="muted-line">
          Signed-in actions by channel: the web app, AI agents over MCP, and the API (rlf_ tokens).
          Account-linked events are kept 90 days; older days come from anonymous daily totals, so
          account-level figures cover the last {windowDays} days. MCP actions are tool calls; connections
          (initialize) are counted separately.
        </p>
        <div className="stats usage-stats">
          <div className="stat"><div className="k">App actions</div><div className="v">{n(data.totals.app)}</div></div>
          <div className="stat"><div className="k">MCP tool calls</div><div className="v">{n(data.totals.mcp)}</div></div>
          <div className="stat"><div className="k">API calls</div><div className="v">{n(data.totals.api)}</div></div>
          <div className="stat"><div className="k">MCP share</div><div className="v">{pct(share.mcp_share)}</div></div>
          <div className="stat"><div className="k">MCP connects</div><div className="v">{n(data.totals.mcp_connects)}</div></div>
        </div>
        <div className="usage-charts">
          <div>
            <h3 className="usage-h">Actions per day</h3>
            <Chart traces={[
              line(x, data.daily.map((d) => d.app), "App", COLORS.app),
              line(x, data.daily.map((d) => d.mcp), "MCP", COLORS.mcp),
              line(x, data.daily.map((d) => d.api), "API", COLORS.api),
            ]} />
          </div>
          <div>
            <h3 className="usage-h">Active accounts per day</h3>
            <Chart traces={[
              line(x, data.daily.map((d) => d.app_accounts), "App", COLORS.app),
              line(x, data.daily.map((d) => d.mcp_accounts), "MCP", COLORS.mcp),
              line(x, data.daily.map((d) => d.api_accounts), "API", COLORS.api),
            ]} />
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>MCP vs the app (last {windowDays} days)</h2>
        <div className="stats usage-stats">
          <div className="stat"><div className="k">MCP-active accounts</div><div className="v">{n(share.mcp_accounts)}</div></div>
          <div className="stat"><div className="k">App-active accounts</div><div className="v">{n(share.app_accounts)}</div></div>
          <div className="stat"><div className="k">Both</div><div className="v">{n(share.mcp_and_app_accounts)}</div></div>
          <div className="stat"><div className="k">MCP only</div><div className="v">{n(share.mcp_only_accounts)}</div></div>
          <div className="stat"><div className="k">Connected to MCP</div><div className="v">{n(share.mcp_connect_accounts)}</div></div>
        </div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h2>The Pro wall (MCP)</h2>
        <p className="muted-line">
          Free (and grandfathered Agent) accounts whose MCP calls were refused: <b>limit</b> = the
          monthly allowance used up, <b>Pro-only</b> = fitting, fleets or simulation asked for. Both
          are demand signals. Repeat = refused on 2+ days. Upgraded = moved to Pro after a refusal.
        </p>
        <div className="stats usage-stats">
          <div className="stat"><div className="k">Hit the limit</div><div className="v">{n(wall.limit_accounts)}</div></div>
          <div className="stat"><div className="k">Asked for Pro-only</div><div className="v">{n(wall.pro_only_accounts)}</div></div>
          <div className="stat"><div className="k">Repeat (2+ days)</div><div className="v">{n(wall.repeat_accounts)}</div></div>
          <div className="stat"><div className="k">Upgraded after</div><div className="v">{n(wall.upgraded_accounts)}</div></div>
          <div className="stat"><div className="k">Pro upgrades ({data.days}d)</div><div className="v">{n(wall.pro_upgrades)}</div></div>
        </div>
        <h3 className="usage-h">Free accounts refused per week</h3>
        <Chart barmode="group" category traces={[
          { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_limit), name: "Limit", marker: { color: COLORS.limit } },
          { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_pro_only), name: "Pro-only", marker: { color: COLORS.pro_only } },
          { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_repeat), name: "Repeat", marker: { color: COLORS.repeat } },
        ]} />
        <p className="muted-line">Weeks start on Monday (UTC); * = this week so far.</p>
      </div>

      <div className="dash-cards usage-cards">
        <OutcomeTable
          title="MCP tools"
          rows={data.mcp_tools}
          columns={[...outcomeCols.filter(([k]) => k !== "locked"), ["avg_ms", "Avg ms"]]}
          empty="No MCP tool calls in this window."
        />
        <OutcomeTable
          title="App features"
          rows={data.app_features}
          columns={outcomeCols.filter(([k]) => k !== "pro_only")}
          empty="No app actions in this window."
        />
      </div>
      <div className="dash-cards" style={{ marginTop: "1rem" }}>
        <KeyList
          title="MCP outcomes"
          rows={Object.entries(data.mcp_outcomes).map(([key, count]) => ({ key, count }))}
          empty="Nothing yet."
        />
        <KeyList title="MCP clients" rows={data.mcp_clients} empty="No MCP clients yet." />
        <KeyList title="MCP calls by plan" rows={data.mcp_plans} empty="Nothing yet." />
      </div>
      {data.api_features.length > 0 && (
        <OutcomeTable title="API (rlf_ tokens)" rows={data.api_features} columns={outcomeCols.filter(([k]) => k !== "pro_only")} empty="" />
      )}
    </>
  );
}
