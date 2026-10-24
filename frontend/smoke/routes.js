// Which pages the smoke tests open. Routes are read from the router source
// (App.jsx, AppShell.jsx, productPages.jsx), so a new page is covered without
// editing the suite. A new route with a parameter (/things/:id) needs one
// line in DETAIL_IDS below saying where its ids come from: until it has one,
// its test fails and says so.
import { readFileSync } from "node:fs";
import { MOVED, fillMoved } from "../src/redirects.js";

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
      found.push({ path, gate, redirect: /<Navigate\b|<\w+Redirect\b/.test(m[2]) });
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
// capability a gated route needs (the test skips it when that's off). The
// earlier addresses (src/redirects.js) are routes too: `redirect`, with the
// `target` they go to.
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
  const moved = MOVED.map((m) => ({ path: m.path, target: m.to, gate: null, flag: null, redirect: true }));
  return [...shell, ...top, ...moved].filter((r) => r.path !== "*");
}

// The public pages (cloud builds only: App.jsx gates them on !AUTH_DISABLED).
export function publicRoutes() {
  return routesIn("App.jsx").filter((r) => r.gate === "!AUTH_DISABLED");
}

export const hasParam = (path) => path.includes("/:");

// Fill a route's parameter: "/models/m/:id" + "abc" -> "/models/m/abc".
export const fill = (path, id) => path.replace(/:\w+/, encodeURIComponent(id));

// Where each app route with a parameter gets its records (each `{id, ...}`):
// an API list and how to read them out of it. Every sample (or seeded record)
// is opened, up to MAX_IDS each, so a page that breaks on one kind of record
// (a competing-risks model, a repairable diagram) is caught. Maintenance
// records and the RBD run are made by smoke/seed.js.
export const MAX_IDS = 12;
const list = (key, field = "id") => (body) => (body[key] || []).map((x) => ({ ...x, id: x[field] }));
export const DETAIL_IDS = {
  "/models/m/:id": ["/api/models", list("models")],
  "/models/degradation/:id": ["/api/degradation/models", list("models")],
  "/models/recurrent/:id": ["/api/recurrent/models", list("models")],
  "/models/alt/:id": ["/api/alt/models", list("models")],
  // A condition and life model: smoke/seed.js fits one.
  "/models/joint/:id": ["/api/joint/models", list("models")],
  "/systems/b/:id": ["/api/rbds", list("rbds")],
  "/systems/runs/:runId": ["/api/rbd-runs", list("runs", "run_id")],
  "/data/:id": ["/api/datasets", list("datasets")],
  "/strategy/analyses/:id": ["/api/strategy/analyses", list("analyses")],
  "/risk/:fleetId": ["/api/fleet/tracked", list("fleets")],
  "/forecasts/:id": ["/api/fleet/fleets", list("fleets")],
  "/maintenance/rcm/:id": ["/api/rcm/studies", list("studies")],
  "/asset-register/positions/:id": ["/api/maintenance/overview", list("tree")],
  "/maintenance/work-orders/:id": ["/api/maintenance/work-orders", list("work_orders")],
  "/asset-register/items/:id": ["/api/maintenance/items", list("items")],
  "/asset-register/locations/:id": ["/api/maintenance/locations", list("locations")],
  "/asset-register/classes/:name": ["/api/maintenance/classes", list("classes", "position_class")],
  "/asset-register/parts/:id": ["/api/maintenance/parts", list("parts")],
};

// An earlier address with an id takes its records from the page it moved to;
// one whose new page has no id (an old tracking bookmark) opens with any id.
export function idSource(route) {
  if (DETAIL_IDS[route.path]) return DETAIL_IDS[route.path];
  if (route.redirect && route.target) {
    if (hasParam(route.target)) return DETAIL_IDS[route.target];
    return [null, () => [{ id: "any-old-id" }]];
  }
  return undefined;
}

// Pages that draw a chart: the test waits for a Plotly plot on these (true,
// or a test of the record shown). The chart library loads with the first page
// that needs it, so a broken chart chunk shows up here.
const CHART_PAGES = {
  // A per-demand model is one probability, with no chart.
  "/models/m/:id": (model) => model.kind !== "per_demand",
  "/models/degradation/:id": true,
  "/models/recurrent/:id": true,
  "/models/alt/:id": true,
  "/models/joint/:id": true,
  "/forecasts/:id": true,
  "/risk/:fleetId": true,
  // A class with a fitted model shows its failure forecast (#407).
  "/asset-register/classes/:name": (cls) => Boolean(cls.model),
  // A failure-finding analysis is one interval: no chart.
  "/strategy/analyses/:id": (analysis) => analysis.kind !== "failure_finding",
};

export function expectsChart(path, record = {}) {
  const rule = CHART_PAGES[path];
  return typeof rule === "function" ? rule(record) : Boolean(rule);
}

// Where an earlier address lands: `from` with an id filled in (and any
// query or #hash) goes to its new page with the same id, query and hash.
export function landing(route, id, suffix = "") {
  const params = {};
  for (const name of route.path.match(/:\w+/g) || []) params[name.slice(1)] = encodeURIComponent(id);
  // The path only: a target's own query (?arrange=items) isn't part of it.
  return fillMoved(route.target, params).split("?")[0] + suffix;
}

// A few earlier addresses with a query or #hash, which must survive the move.
export const REDIRECTS_WITH_QUERY = [
  ["/datasets/d/sample-ds-bearings?compare=arm", "/data/sample-ds-bearings?compare=arm"],
  ["/modelling/new?mode=paste", "/models/new?mode=paste"],
  ["/modelling/m/sample-model-bearings-weibull?from=email#bounds", "/models/m/sample-model-bearings-weibull?from=email#bounds"],
  ["/rcm/studies/sample-rcm-truck?from=email", "/maintenance/rcm/sample-rcm-truck?from=email"],
  ["/strategy/demonstration-test?model=sample-model-bearings-weibull", "/strategy/test-planning?model=sample-model-bearings-weibull"],
  ["/asset-register/positions?place=none", "/asset-register/explorer?arrange=positions&place=none"],
  ["/maintenance/locations#top", "/asset-register/explorer?arrange=locations#top"],
];
