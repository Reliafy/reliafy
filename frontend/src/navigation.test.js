import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import {
  ENTRIES, ROLES, ROLE_IDS, SECTIONS, activeEntry, buildMenu, childActive, crumbsFor, datasetPath, entryActive,
  groupBySection, homeCards, itemPath, liveEntries,
} from "./navigation.js";
import { MOVED, movedTo } from "./redirects.js";
import { appRoutes, hasParam } from "../smoke/routes.js";

const ALL = { maintenance: true, agent: true };
const ids = (entries) => entries.map((e) => e.id);
const everyLink = (entries) => entries.flatMap((e) => [e.to, ...(e.children || []).map((c) => c.to)]);
const PAGES = new Set(appRoutes().filter((r) => !r.redirect).map((r) => r.path));

// Pages that aren't in the menu themselves, and where they're opened from.
const REACHED_FROM = {
  "/": "redirects to Home",
  "/models/new": "Models › New model, Home's starts, a dataset's Fit menu",
  "/models/recurrent/new": "Models › Repairable models › New model",
  "/models/alt/new": "Models › Accelerated life › New model",
  "/models/joint/new": "Models › Condition monitoring › New model",
  "/systems/b": "Systems › New diagram, Home's starts",
  "/systems/runs/compare": "Systems › Simulation runs › Compare",
  "/strategy/test-planning/sequential": "Test planning's tabs",
  "/strategy/test-planning/life": "Test planning's tabs",
  "/strategy/test-planning/accelerated": "Test planning's tabs",
  "/strategy/test-planning/comparison": "Test planning's tabs",
  "/settings": "the menu's Account group",
  "/billing": "the menu's Account group",
  "/api-docs": "the menu's Account group",
  "/team": "the top bar's team settings",
  "/admin": "operators only, by address",
  "/changes": "Home's What changed panel",
  "/oauth/consent": "an MCP client's sign-in",
};

test("every page in the app is in the menu or opened from a page that is", () => {
  const menu = new Set(everyLink(liveEntries(ALL)));
  const missing = [...PAGES]
    .filter((p) => !hasParam(p) && !p.startsWith("/api-docs/"))
    .filter((p) => !menu.has(p) && !REACHED_FROM[p]);
  assert.deepEqual(missing, []);
});

test("every menu link is a page of the app", () => {
  for (const has of [{}, ALL]) {
    for (const to of everyLink(liveEntries(has))) assert.ok(PAGES.has(to), to);
  }
});

test("the menu is Home, then Design, Operate and Analyse, then Reports and the Agent", () => {
  assert.deepEqual(SECTIONS.map((s) => s.label), ["Design", "Operate", "Analyse"]);
  const groups = groupBySection(buildMenu({ has: ALL }).main);
  assert.deepEqual(groups.map((g) => g.section?.label || g.key), ["home", "Design", "Operate", "Analyse", "end"]);
  assert.deepEqual(groups.map((g) => ids(g.entries)), [
    ["home"], ["systems"], ["assets", "maintenance"], ["data", "models", "strategy", "forecasts"], ["reports", "agent"],
  ]);
  const labels = buildMenu({ has: ALL }).main.map((e) => e.label);
  assert.deepEqual(labels, ["Home", "Systems", "Assets", "Maintenance", "Data", "Models", "Strategy", "Forecasts",
    "Reports", "Reliability Agent"]);
});

test("each entry's children, as agreed", () => {
  const live = liveEntries(ALL);
  const kids = (id) => live.find((e) => e.id === id).children?.map((c) => c.label) || [];
  assert.deepEqual(kids("systems"), ["Simulation runs", "Product structure"]);
  assert.deepEqual(kids("assets"), ["Items", "Locations", "Parts and stock", "Classes"]);
  assert.deepEqual(kids("maintenance"), ["RCM studies"]);
  assert.deepEqual(kids("data"), []);
  assert.deepEqual(kids("models"), ["Non-repairable models", "Repairable models", "Accelerated life", "Degradation",
    "Condition monitoring", "Degradation tracking"]);
  assert.deepEqual(kids("strategy"), ["Optimal replacement", "Compare two models", "Failure finding", "Test planning"]);
  assert.deepEqual(kids("forecasts"), []);
});

test("an entry's landing page is never also one of its children", () => {
  for (const has of [{}, ALL]) {
    for (const e of liveEntries(has)) {
      for (const c of e.children || []) assert.notEqual(c.to, e.to, `${e.label} repeats its landing page`);
    }
  }
});

test("without Reliafy Maintenance: no Assets, and Maintenance is the RCM studies", () => {
  const none = liveEntries({});
  assert.ok(!ids(none).includes("assets"));
  assert.ok(!ids(none).includes("agent"));
  const maint = none.find((e) => e.id === "maintenance");
  assert.equal(maint.label, "Maintenance");
  assert.equal(maint.to, "/maintenance/rcm");
  assert.equal(maint.children, undefined);
  // Product structure is Reliafy Maintenance's parts catalogue.
  assert.ok(!everyLink(none).includes("/systems/structure"));
  // With it, Maintenance opens on the due tasks and work orders.
  assert.equal(liveEntries(ALL).find((e) => e.id === "maintenance").to, "/maintenance");
});

test("no placeholder entries: Requirements and Failures stay hidden until their pages exist", () => {
  for (const has of [{}, ALL]) {
    const live = ids(liveEntries(has));
    assert.ok(!live.includes("requirements"));
    assert.ok(!live.includes("failures"));
  }
});

test("no roles shows everything the workspace has, nothing under More", () => {
  const { main, more } = buildMenu({ roles: [], has: ALL });
  assert.deepEqual(ids(main), ids(liveEntries(ALL)));
  assert.deepEqual(more, []);
});

test("a technician sees Home, Maintenance and Assets; the rest is under More", () => {
  const { main, more } = buildMenu({ roles: ["technician"], has: ALL });
  assert.deepEqual(ids(main), ["home", "maintenance", "assets"]);
  assert.deepEqual(ids(more), ["systems", "data", "models", "strategy", "forecasts", "reports", "agent"]);
  assert.equal(main[1].to, "/maintenance");
});

test("a fleet manager leads with Forecasts, then the assets and their maintenance", () => {
  const { main } = buildMenu({ roles: ["fleet"], has: ALL });
  assert.deepEqual(ids(main), ["home", "assets", "maintenance", "forecasts", "models", "data", "reports"]);
  assert.deepEqual(homeCards(["fleet"]), ["fleets", "due"]);
});

test("picking every role shows everything", () => {
  const { main, more } = buildMenu({ roles: ROLE_IDS, has: ALL });
  assert.deepEqual(new Set(ids(main)), new Set(ids(liveEntries(ALL))));
  assert.deepEqual(more, []);
});

test("shown entries keep their sections, in role order within each", () => {
  const { main } = buildMenu({ roles: ["planner", "analyst"], has: ALL });
  assert.deepEqual(ids(main), ["home", "systems", "maintenance", "assets", "forecasts", "strategy", "data", "models",
    "reports", "agent"]);
  assert.deepEqual(groupBySection(main).map((g) => g.key), ["home", "design", "operate", "analyse", "end"]);
});

test("unknown roles are ignored: everything shown", () => {
  assert.deepEqual(buildMenu({ roles: ["astronaut"], has: ALL }).more, []);
});

test("roles name only entries that exist", () => {
  const known = new Set(ENTRIES.map((e) => e.id));
  for (const role of ROLES) for (const id of role.entries) assert.ok(known.has(id), `${role.id}: ${id}`);
  assert.equal(new Set(ROLE_IDS).size, ROLES.length);
});

test("the roles are the server's", () => {
  const py = readFileSync(new URL("../../backend/services/roles.py", import.meta.url), "utf8");
  const server = /ROLE_IDS = \(([^)]*)\)/.exec(py)[1].match(/"(\w+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual(server, ROLE_IDS);
});

test("a page lights its entry, and its child, on landing, child and detail pages", () => {
  const live = liveEntries(ALL);
  const at = (path) => {
    const e = activeEntry(live, path);
    return [e?.id || null, (e?.children || []).find((c) => childActive(c, path))?.label || null];
  };
  assert.deepEqual(at("/home"), ["home", null]);
  assert.deepEqual(at("/models"), ["models", null]);
  assert.deepEqual(at("/models/life"), ["models", "Non-repairable models"]);
  assert.deepEqual(at("/models/m/abc"), ["models", "Non-repairable models"]);
  assert.deepEqual(at("/models/new"), ["models", "Non-repairable models"]);
  assert.deepEqual(at("/models/joint/x"), ["models", "Condition monitoring"]);
  assert.deepEqual(at("/models/tracking/f1"), ["models", "Degradation tracking"]);
  assert.deepEqual(at("/data"), ["data", null]);
  assert.deepEqual(at("/data/d1"), ["data", null]);
  assert.deepEqual(at("/systems/b/r1"), ["systems", null]);
  assert.deepEqual(at("/systems/runs/x"), ["systems", "Simulation runs"]);
  assert.deepEqual(at("/strategy/test-planning/life"), ["strategy", "Test planning"]);
  assert.deepEqual(at("/strategy/analyses/x"), ["strategy", null]);
  assert.deepEqual(at("/forecasts/f"), ["forecasts", null]);
  assert.deepEqual(at("/asset-register/items/i1"), ["assets", "Items"]);
  assert.deepEqual(at("/asset-register/positions/p1"), ["assets", null]);
  assert.deepEqual(at("/maintenance/work-orders/w1"), ["maintenance", null]);
  assert.deepEqual(at("/maintenance/rcm/s1"), ["maintenance", "RCM studies"]);
  assert.deepEqual(at("/reports"), ["reports", null]);
  assert.deepEqual(at("/settings"), [null, null]);
  // A prefix of a word isn't a match.
  assert.deepEqual(at("/modelsx"), [null, null]);
  const models = live.find((e) => e.id === "models");
  assert.ok(entryActive(models, "/models"));
  // Without Reliafy Maintenance, an RCM study lights Maintenance.
  assert.equal(activeEntry(liveEntries({}), "/maintenance/rcm/s1").id, "maintenance");
});

test("a page's breadcrumbs: its entry, then its child, from the live menu", () => {
  const live = liveEntries(ALL);
  assert.deepEqual(crumbsFor(live, "models", "/models"), []);
  assert.deepEqual(crumbsFor(live, "models", "/models/life"), [{ label: "Models", to: "/models" }]);
  assert.deepEqual(crumbsFor(live, "models", "/models/m/x", "/models/life"),
    [{ label: "Models", to: "/models" }, { label: "Non-repairable models", to: "/models/life" }]);
  assert.deepEqual(crumbsFor(live, "maintenance", "/maintenance/rcm/s", "/maintenance/rcm"),
    [{ label: "Maintenance", to: "/maintenance" }, { label: "RCM studies", to: "/maintenance/rcm" }]);
  // Without Reliafy Maintenance, Maintenance is the RCM studies: one crumb, to a page the user has.
  const none = liveEntries({});
  assert.deepEqual(crumbsFor(none, "maintenance", "/maintenance/rcm"), []);
  assert.deepEqual(crumbsFor(none, "maintenance", "/maintenance/rcm/s", "/maintenance/rcm"),
    [{ label: "Maintenance", to: "/maintenance/rcm" }]);
  assert.deepEqual(crumbsFor(none, "assets", "/asset-register/items"), []);
});

test("Home leads with the primary role's cards; none without roles", () => {
  assert.deepEqual(homeCards([]), []);
  assert.equal(homeCards(["technician"])[0], "work-today");
  assert.equal(homeCards(["planner"])[0], "due");
  assert.deepEqual(homeCards(["analyst"]), ["recent-models", "recent-data"]);
  assert.deepEqual(homeCards(["manager", "technician"]), ["waiting", "work-today"]);
  const cards = homeCards(ROLE_IDS);
  assert.equal(new Set(cards).size, cards.length);
});

test("saved items open at their new addresses", () => {
  assert.equal(itemPath("models", "m 1"), "/models/m/m%201");
  assert.equal(itemPath("rcm_studies", "s"), "/maintenance/rcm/s");
  assert.equal(itemPath("fleets", "f"), "/forecasts/f");
  assert.equal(itemPath("rbds", "r"), "/systems/b/r");
  assert.equal(itemPath("reports", "r"), null);
  assert.equal(datasetPath("d1"), "/data/d1");
});

// ---- Earlier addresses ----------------------------------------------------------

// Every address the app had before this menu, and where it must land (with
// "x" for an id). The whole table: a row missing here or in redirects.js fails.
const OLD_TO_NEW = [
  ["/modelling", "/models"],
  ["/modelling/models", "/models"],
  ["/modelling/data", "/data"],
  ["/modelling/data/x", "/data/x"],
  ["/modelling/life", "/models/life"],
  ["/modelling/new", "/models/new"],
  ["/modelling/m/x", "/models/m/x"],
  ["/modelling/degradation", "/models/degradation"],
  ["/modelling/degradation/x", "/models/degradation/x"],
  ["/modelling/recurrent", "/models/recurrent"],
  ["/modelling/recurrent/new", "/models/recurrent/new"],
  ["/modelling/recurrent/x", "/models/recurrent/x"],
  ["/modelling/alt", "/models/alt"],
  ["/modelling/alt/new", "/models/alt/new"],
  ["/modelling/alt/x", "/models/alt/x"],
  ["/modelling/joint", "/models/joint"],
  ["/modelling/joint/new", "/models/joint/new"],
  ["/modelling/joint/x", "/models/joint/x"],
  ["/datasets", "/data"],
  ["/datasets/list", "/data"],
  ["/datasets/d/x", "/data/x"],
  ["/rbds", "/systems"],
  ["/rbds/list", "/systems"],
  ["/rbds/b", "/systems/b"],
  ["/rbds/b/x", "/systems/b/x"],
  ["/rbds/runs", "/systems/runs"],
  ["/rbds/runs/compare", "/systems/runs/compare"],
  ["/rbds/runs/x", "/systems/runs/x"],
  ["/fleet", "/forecasts"],
  ["/fleet/forecasts", "/forecasts"],
  ["/fleet/forecasts/x", "/forecasts/x"],
  ["/fleet/tracking", "/models/tracking"],
  ["/fleet/tracking/x", "/models/tracking/x"],
  ["/strategy/analyses", "/strategy"],
  ["/strategy/tracking", "/models/tracking"],
  ["/strategy/tracking/x", "/models/tracking"],
  ["/strategy/demonstration-test", "/strategy/test-planning"],
  ["/rcm", "/maintenance/rcm"],
  ["/rcm/studies", "/maintenance/rcm"],
  ["/rcm/studies/x", "/maintenance/rcm/x"],
  ["/maintenance/positions/x", "/asset-register/positions/x"],
  ["/maintenance/items", "/asset-register/items"],
  ["/maintenance/items/x", "/asset-register/items/x"],
  ["/maintenance/locations", "/asset-register/locations"],
  ["/maintenance/locations/x", "/asset-register/locations/x"],
  ["/maintenance/classes", "/asset-register/classes"],
  ["/maintenance/classes/x", "/asset-register/classes/x"],
  ["/maintenance/parts", "/asset-register/parts"],
  ["/maintenance/parts/x", "/asset-register/parts/x"],
];

test("every earlier address redirects to its page's new place, with its id", () => {
  for (const [from, to] of OLD_TO_NEW) assert.equal(movedTo(from), to, from);
  assert.equal(MOVED.length, OLD_TO_NEW.length, "redirects.js and this table differ");
  // Ids are carried as they come (already encoded in the address).
  assert.equal(movedTo("/maintenance/classes/Pool%20pump"), "/asset-register/classes/Pool%20pump");
  assert.equal(movedTo("/modelling/m/"), null);
  // Addresses that didn't move.
  for (const path of ["/home", "/strategy", "/strategy/replacement", "/maintenance", "/maintenance/work-orders/w"]) {
    assert.equal(movedTo(path), null, path);
  }
});

test("every redirect lands on a page of the app, and no page is also a redirect", () => {
  for (const m of MOVED) {
    assert.ok(PAGES.has(m.to), `${m.path} → ${m.to}, which isn't a page`);
    assert.ok(!PAGES.has(m.path), `${m.path} is both a page and a redirect`);
    for (const name of m.to.match(/:\w+/g) || []) assert.ok(m.path.includes(name), `${m.path} → ${m.to}`);
  }
});

test("no link in the app's own code points at an earlier address", () => {
  const old = /["'`(](\/(?:modelling|rbds|datasets|fleet|rcm)(?:[/"'`?#)]|$)|\/maintenance\/(?:positions|items|locations|classes|parts)\b)/;
  const bad = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const path = new URL(name, dir);
      if (statSync(path).isDirectory()) walk(new URL(`${name}/`, dir));
      else if (/\.(jsx?|md)$/.test(name) && !/redirects\.js$|navigation\.test\.js$/.test(name)) {
        readFileSync(path, "utf8").split("\n").forEach((line, i) => {
          if (old.test(line) && !line.includes("/api/")) bad.push(`${path.pathname.split("/src/")[1]}:${i + 1}: ${line.trim()}`);
        });
      }
    }
  };
  walk(new URL("./", import.meta.url));
  assert.deepEqual(bad, []);
});
