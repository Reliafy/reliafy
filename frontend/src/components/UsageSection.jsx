import Plot from "./Plot.jsx";
import { CATEGORY, COLORWAY, SUBTLE } from "../plotTheme.js";
import Card, { CardHeader } from "./ui/Card.jsx";
import Chip from "./ui/Chip.jsx";
import { formatPercent } from "../format.js";

// Product usage for the operator dashboard (GET /api/admin/usage): how the
// app, MCP and the API are used, and the MCP plan wall — the numbers behind
// "does MCP use justify an agent-only plan?". The page fetches the report
// (its range drives everything) and passes it in.

// App, MCP and API take the theme's first three series colours. The plan-wall
// outcomes: limit is a caveat (amber), Pro-only is demand (the accent, not a
// fault), repeat is neutral.
const COLORS = { app: COLORWAY[0], mcp: COLORWAY[1], api: COLORWAY[2], limit: CATEGORY.amber, pro_only: COLORWAY[0], repeat: SUBTLE };
const CHANNELS = [["app", "App"], ["mcp", "MCP"], ["api", "API"]];

// Outcome and plan keys as the backend stores them.
const LABELS = {
  ok: "OK", error: "Error", locked: "Locked", limit: "Limit", pro_only: "Pro-only",
  free: "Free", pro: "Pro", agent: "Agent", admin: "Operator", unknown: "Unknown",
};

const LAYOUT = {
  height: 240,
  yaxis: { rangemode: "tozero" },
  hovermode: "x unified",
};

const n = (v) => (v ?? 0).toLocaleString();

function Chart({ traces, barmode, category, legend = false }) {
  const layout = { ...LAYOUT, showlegend: legend, ...(barmode ? { barmode } : {}) };
  // Week labels aren't dates to Plotly (a "*" marks a partial week).
  if (category) layout.xaxis = { ...LAYOUT.xaxis, type: "category" };
  return (
    <Plot data={traces} layout={layout} />
  );
}

function line(x, y, name, color) {
  return { type: "scatter", mode: "lines+markers", x, y, name, line: { color, width: 1.6 }, marker: { color, size: 4 } };
}

// One legend for the App / MCP / API charts.
function ChannelLegend() {
  return (
    <div className="chip-row usage-legend" aria-label="Legend">
      {CHANNELS.map(([key, label]) => <Chip key={key} dot={COLORS[key]}>{label}</Chip>)}
    </div>
  );
}

// A ranked table: key, total and the outcome columns that matter for it.
function OutcomeTable({ title, rows, columns, empty }) {
  return (
    <Card>
      <CardHeader title={title} />
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
    </Card>
  );
}

function KeyList({ title, rows, empty }) {
  const shown = rows.filter((r) => r.count > 0);
  return (
    <Card>
      <CardHeader title={title} />
      {shown.length === 0 ? (
        <p className="muted-line">{empty}</p>
      ) : (
        <ul className="bill-usage">
          {shown.map((r) => (
            <li key={r.key}>
              <span className="traffic-key">{LABELS[r.key] || r.key}</span>
              <span className="bill-usage-n">{n(r.count)}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Tiles({ items }) {
  return (
    <div className="stats usage-stats">
      {items.map(([label, value]) => (
        <div className="stat" key={label}><div className="k">{label}</div><div className="v">{value}</div></div>
      ))}
    </div>
  );
}

export default function UsageSection({ state, includeAdmin, onIncludeAdmin }) {
  const { data, error } = state;

  const header = (
    <CardHeader
      title="Product usage"
      subtitle="Signed-in actions by channel: the web app, AI agents over MCP, and the API (rlf_ tokens)."
      actions={
        <label className="usage-check">
          <input type="checkbox" checked={includeAdmin} onChange={(e) => onIncludeAdmin(e.target.checked)} />
          Include operator accounts
        </label>
      }
    />
  );

  if (error) return <Card style={{ marginTop: "1rem" }}>{header}<p className="muted-line">{error}</p></Card>;
  if (!data) return <Card style={{ marginTop: "1rem" }}>{header}<p className="muted-line">Loading…</p></Card>;

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
  const anyActions = data.totals.app + data.totals.mcp + data.totals.api > 0;
  const anyWall = data.weekly.some((w) => w.wall_limit + w.wall_pro_only + w.wall_repeat > 0);

  return (
    <>
      <Card style={{ marginTop: "1rem" }}>
        {header}
        <Tiles items={[
          ["App actions", n(data.totals.app)],
          ["API calls", n(data.totals.api)],
          ["MCP share", formatPercent(share.mcp_share)],
          ["MCP connects", n(data.totals.mcp_connects)],
        ]} />
        {anyActions ? (
          <>
            <ChannelLegend />
            <div className="usage-charts">
              <div>
                <h3 className="usage-h">Actions per day</h3>
                <Chart traces={CHANNELS.map(([k, label]) => line(x, data.daily.map((d) => d[k]), label, COLORS[k]))} />
              </div>
              <div>
                <h3 className="usage-h">Active accounts per day</h3>
                <Chart traces={CHANNELS.map(([k, label]) => line(x, data.daily.map((d) => d[`${k}_accounts`]), label, COLORS[k]))} />
              </div>
            </div>
          </>
        ) : (
          <p className="muted-line">No signed-in actions in this window.</p>
        )}
        <p className="usage-note">
          Account-linked events are kept 90 days; older days come from anonymous daily totals, so
          account-level figures cover the last {windowDays} days. MCP actions are tool calls;
          connections (initialize) are counted separately.
        </p>
      </Card>

      <Card style={{ marginTop: "1rem" }}>
        <CardHeader title="MCP vs the app" subtitle={`Accounts active in the last ${windowDays} days`} />
        <Tiles items={[
          ["App-active accounts", n(share.app_accounts)],
          ["Both", n(share.mcp_and_app_accounts)],
          ["MCP only", n(share.mcp_only_accounts)],
          ["Connected to MCP", n(share.mcp_connect_accounts)],
        ]} />
      </Card>

      <Card style={{ marginTop: "1rem" }}>
        <CardHeader
          title="The Pro wall (MCP)"
          subtitle="Free (and grandfathered Agent) accounts whose MCP calls were refused. Both kinds are demand signals."
        />
        <Tiles items={[
          ["Hit the limit", n(wall.limit_accounts)],
          ["Asked for Pro-only", n(wall.pro_only_accounts)],
          ["Repeat (2+ days)", n(wall.repeat_accounts)],
          ["Upgraded after", n(wall.upgraded_accounts)],
        ]} />
        {anyWall ? (
          <>
            <h3 className="usage-h">Free accounts refused per week</h3>
            <Chart barmode="group" category legend traces={[
              { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_limit), name: "Limit", marker: { color: COLORS.limit } },
              { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_pro_only), name: "Pro-only", marker: { color: COLORS.pro_only } },
              { type: "bar", x: weeks, y: data.weekly.map((w) => w.wall_repeat), name: "Repeat", marker: { color: COLORS.repeat } },
            ]} />
          </>
        ) : (
          <p className="muted-line">No refusals in this window.</p>
        )}
        <p className="usage-note">
          Limit = the monthly allowance used up; Pro-only = fitting, fleets or simulation asked for;
          repeat = refused on 2+ days; upgraded = moved to Pro after a refusal. {n(wall.pro_upgrades)} Pro
          upgrade{wall.pro_upgrades === 1 ? "" : "s"} in this window, by any route.
          {anyWall && " Weeks start on Monday (UTC); * = this week so far."}
        </p>
      </Card>

      {/* The breakdowns: only when there's something to break down. */}
      {anyActions && (
        <>
        <div className="dash-cards usage-cards" style={{ marginTop: "1rem" }}>
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
            empty="No MCP calls in this window."
          />
          <KeyList title="MCP clients" rows={data.mcp_clients} empty="No MCP clients in this window." />
          <KeyList title="MCP calls by plan" rows={data.mcp_plans} empty="No MCP calls in this window." />
        </div>
        {data.api_features.length > 0 && (
          <div style={{ marginTop: "1rem" }}>
            <OutcomeTable title="API (rlf_ tokens)" rows={data.api_features} columns={outcomeCols.filter(([k]) => k !== "pro_only")} empty="" />
          </div>
        )}
        </>
      )}
    </>
  );
}
