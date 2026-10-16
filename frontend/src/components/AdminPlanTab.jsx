import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getAdminPlan } from "../api.js";
import { renderMarkdown } from "../markdown.js";
import { rewritePlanLinks, splitMermaid } from "../planMarkdown.js";
import { ganttThemeVariables, readTokens } from "../planTheme.js";
import Card from "./ui/Card.jsx";

// The Admin page's Plan tab: the operators' plan, a markdown document kept in
// the database (GET /api/admin/plan; pushed with backend/scripts/push_plan.py),
// never in the repo or this bundle. Prose renders with the content pages'
// renderer (markdown.js); fenced ```mermaid blocks render with mermaid, which
// is imported only here, when a plan with charts opens, so its chunk never
// loads anywhere else. A block mermaid can't draw shows its source and why.
// Relative links point into the plan's own repository, which the app doesn't
// serve: they go to GitHub at the plan's commit, or become plain text
// (planMarkdown.js, rewritePlanLinks).

// Gantt charts keep at least this width and scroll inside their own box
// rather than squeezing onto a phone.
const MIN_GANTT_WIDTH = 880;

let mermaidModule = null;
function loadMermaid() {
  if (!mermaidModule) {
    mermaidModule = import("mermaid").then((m) => m.default).catch((e) => {
      mermaidModule = null; // let a Refresh try again
      throw e;
    });
  }
  return mermaidModule;
}

let renders = 0;

async function drawCharts(parts, width, onChart, alive) {
  let mermaid;
  try {
    mermaid = await loadMermaid();
  } catch (e) {
    parts.forEach((p, i) => p.type === "mermaid" && onChart(i, { error: `The chart renderer didn't load: ${e.message}` }));
    return;
  }
  if (!alive()) return;
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "strict",
    // The app's colours (planTheme.js): done, active, crit and not-started
    // tasks each look different.
    theme: "base",
    themeVariables: ganttThemeVariables(readTokens()),
    suppressErrorRendering: true,
    fontFamily: getComputedStyle(document.body).fontFamily,
    // Short axis dates ("5 Jan") so the ticks don't run into each other; a
    // chart's own axisFormat still wins.
    gantt: { useMaxWidth: false, useWidth: width, axisFormat: "%-d %b" },
  });
  for (const [i, p] of parts.entries()) {
    if (p.type !== "mermaid") continue;
    const id = `plan-mermaid-${++renders}`;
    let chart;
    try {
      chart = { svg: (await mermaid.render(id, p.code)).svg };
    } catch (e) {
      chart = { error: e?.message || String(e) };
      // What mermaid may leave behind in <body> after a failed render.
      document.getElementById(`d${id}`)?.remove();
      document.getElementById(id)?.remove();
    }
    if (!alive()) return;
    onChart(i, chart);
  }
}

function Chart({ code, chart }) {
  if (!chart) return <div className="admin-plan-chart admin-plan-chart-pending">Drawing chart…</div>;
  if (chart.error) {
    return (
      <div className="admin-plan-chart-error" role="note">
        <p className="muted-line warn">This chart couldn't be drawn: {chart.error}</p>
        <pre>{code}</pre>
      </div>
    );
  }
  return <div className="admin-plan-chart" dangerouslySetInnerHTML={{ __html: chart.svg }} />;
}

const when = (iso) =>
  iso
    ? new Date(iso).toLocaleString("en-AU", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" })
    : "";

export default function AdminPlanTab() {
  const [state, setState] = useState({ data: null, error: null, missing: false });
  const [busy, setBusy] = useState(true);
  const [charts, setCharts] = useState({});
  const bodyRef = useRef(null);

  const load = useCallback(() => {
    setBusy(true);
    return getAdminPlan()
      .then((data) => setState({ data, error: null, missing: false }))
      .catch((e) => setState({ data: null, error: e.message, missing: e.status === 404 }))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const parts = useMemo(() => splitMermaid(state.data?.markdown), [state.data]);

  useEffect(() => {
    setCharts({});
    if (!parts.some((p) => p.type === "mermaid")) return undefined;
    let alive = true;
    const width = Math.max(MIN_GANTT_WIDTH, bodyRef.current?.clientWidth || 0);
    drawCharts(parts, width, (i, chart) => setCharts((c) => ({ ...c, [i]: chart })), () => alive);
    return () => {
      alive = false;
    };
  }, [parts]);

  const { data, error, missing } = state;
  return (
    <div className="admin-plan">
      <div className="lib-bar">
        <span className="muted" data-testid="plan-updated">
          {data?.updated_at && (
            <>
              Updated {when(data.updated_at)}
              {data.source ? <> from <code>{data.source}</code></> : null}
            </>
          )}
        </span>
        <button type="button" className="secondary sm" onClick={load} disabled={busy}>
          {busy ? "Loading…" : "Refresh"}
        </button>
      </div>
      {error ? (
        <Card className="empty">
          <p>{missing ? error : `The plan didn't load: ${error}`}</p>
        </Card>
      ) : !data ? (
        <Card className="empty">Loading…</Card>
      ) : (
        <Card className="admin-plan-card">
          <div ref={bodyRef} className="guide-prose admin-plan-prose">
            {parts.map((p, i) =>
              p.type === "mermaid" ? (
                <Chart key={i} code={p.code} chart={charts[i]} />
              ) : (
                <div key={i} dangerouslySetInnerHTML={{ __html: rewritePlanLinks(renderMarkdown(p.text), data.source) }} />
              )
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
