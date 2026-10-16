// Which pages the smoke tests open. Routes are read from the router source
// (App.jsx, AppShell.jsx, productPages.jsx), so a new page is covered without
// editing the suite. A new route with a parameter (/things/:id) needs one
// line in DETAIL_IDS below saying where its ids come from: until it has one,
// its test fails and says so.
import { readFileSync } from "node:fs";

const src = (file) => readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8");

// Every `<Route path=...>` in a file, with the `{flag && ...}` gate in front of
// it (null when ungated: the gate sits between the previous route and this
// one) and whether it only redirects.
function routesIn(file) {
  const text = src(file);
  const found = [];
  let previous = text.indexOf("<Routes>");
  for (const m of text.matchAll(/<Route\s+(?:key=\{[^}]*\}\s+)?path=(?:"([^"]+)"|\{p\.path\})([^\n]*)/g)) {
    const gates = [...text.slice(previous, m.index).matchAll(/\{\s*(!?\w+)\s*&&/g)];
    const gate = gates.length ? gates[gates.length - 1][1] : null;
    previous = m.index + m[0].length;
    for (const path of m[1] ? [m[1]] : productPaths()) {
      found.push({ path, gate, redirect: /<Navigate\b|<TrackingRedirect\b/.test(m[2]) });
    }
  }
  return found;
}

// The product pages' paths (App.jsx maps PRODUCT_PAGES to routes).
function productPaths() {
  return [...src("productPages.jsx").matchAll(/^\s*path:\s*"([^"]+)"/gm)].map((m) => m[1]);
}

// The gates in AppShell.jsx, as the /api/config flags behind them.
const GATE_FLAGS = { agentEnabled: "reliability_agent", maintenanceEnabled: "maintenance", billing: "billing" };

// The signed-in app's pages, minus the catch-all; `flag` is the /api/config
// capability a gated route needs (the test skips it when that's off).
export function appRoutes() {
  const shell = routesIn("AppShell.jsx").map((r) => ({ ...r, flag: r.gate ? GATE_FLAGS[r.gate] : null }));
  for (const r of shell) {
    if (r.gate && !r.flag) throw new Error(`AppShell.jsx gates ${r.path} on "${r.gate}": add it to GATE_FLAGS in smoke/routes.js`);
  }
  // App.jsx's ungated routes besides the shell itself (/oauth/consent): these
  // draw outside the shell's <main>.
  const top = routesIn("App.jsx")
    .filter((r) => !r.gate && r.path !== "/*")
    .map((r) => ({ ...r, flag: null, root: "#root" }));
  return [...shell, ...top].filter((r) => r.path !== "*");
}

// The public pages (cloud builds only: App.jsx gates them on !AUTH_DISABLED).
export function publicRoutes() {
  return routesIn("App.jsx").filter((r) => r.gate === "!AUTH_DISABLED");
}

export const hasParam = (path) => path.includes("/:");

// Fill a route's parameter: "/modelling/m/:id" + "abc" -> "/modelling/m/abc".
export const fill = (path, id) => path.replace(/:\w+/, encodeURIComponent(id));

// Where each app route with a parameter gets its records (each `{id, ...}`):
// an API list and how to read them out of it. Every sample (or seeded record)
// is opened, up to MAX_IDS each, so a page that breaks on one kind of record
// (a competing-risks model, a repairable diagram) is caught. Maintenance
// records and the RBD run are made by smoke/seed.js.
export const MAX_IDS = 12;
const list = (key, field = "id") => (body) => (body[key] || []).map((x) => ({ ...x, id: x[field] }));
export const DETAIL_IDS = {
  "/modelling/m/:id": ["/api/models", list("models")],
  "/modelling/degradation/:id": ["/api/degradation/models", list("models")],
  "/modelling/recurrent/:id": ["/api/recurrent/models", list("models")],
  "/modelling/alt/:id": ["/api/alt/models", list("models")],
  "/rbds/b/:id": ["/api/rbds", list("rbds")],
  "/rbds/runs/:runId": ["/api/rbd-runs", list("runs", "run_id")],
  "/datasets/d/:id": ["/api/datasets", list("datasets")],
  "/strategy/analyses/:id": ["/api/strategy/analyses", list("analyses")],
  "/fleet/tracking/:fleetId": ["/api/fleet/tracked", list("fleets")],
  "/fleet/forecasts/:id": ["/api/fleet/fleets", list("fleets")],
  "/rcm/studies/:id": ["/api/rcm/studies", list("studies")],
  "/maintenance/positions/:id": ["/api/maintenance/overview", list("tree")],
  "/maintenance/work-orders/:id": ["/api/maintenance/work-orders", list("work_orders")],
  "/maintenance/items/:id": ["/api/maintenance/items", list("items")],
  "/maintenance/locations/:id": ["/api/maintenance/locations", list("locations")],
  "/maintenance/classes/:name": ["/api/maintenance/classes", list("classes", "position_class")],
  "/maintenance/parts/:id": ["/api/maintenance/parts", list("parts")], // #435
  // An old bookmark: redirects to the tracking list whatever the id.
  "/strategy/tracking/:modelId": [null, () => [{ id: "any-old-id" }]],
};

// Pages that draw a chart: the test waits for a Plotly plot on these (true,
// or a test of the record shown). The chart library loads with the first page
// that needs it, so a broken chart chunk shows up here.
const CHART_PAGES = {
  "/modelling/m/:id": true,
  "/modelling/degradation/:id": true,
  "/modelling/recurrent/:id": true,
  "/modelling/alt/:id": true,
  "/fleet/forecasts/:id": true,
  "/fleet/tracking/:fleetId": true,
  // A class with a fitted model shows its failure forecast (#407).
  "/maintenance/classes/:name": (cls) => Boolean(cls.model),
  // A failure-finding analysis is one interval: no chart.
  "/strategy/analyses/:id": (analysis) => analysis.kind !== "failure_finding",
};

export function expectsChart(path, record = {}) {
  const rule = CHART_PAGES[path];
  return typeof rule === "function" ? rule(record) : Boolean(rule);
}
