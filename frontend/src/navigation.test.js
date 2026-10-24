import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import {
  ENTRIES, ROLES, ROLE_IDS, SECTIONS, activeEntry, buildMenu, childActive, crumbsFor, datasetPath, entryActive,
  groupBySection, homeCards, itemPath, liveEntries,
} from "./navigation.js";
import { MOVED, movedHref, movedTo } from "./redirects.js";
import { PLANNED } from "./plannedPages.js";
import { appRoutes, hasParam } from "../smoke/routes.js";

const ALL = { maintenance: true, agent: true, risk: true };
const PREVIEW = { ...ALL, preview: true };
const ids = (entries) => entries.map((e) => e.id);
const everyLink = (entries) => entries.flatMap((e) => [e.to, ...(e.children || []).map((c) => c.to)]);
const PAGES = new Set(appRoutes().filter((r) => !r.redirect).map((r) => r.path));

// Pages that aren't in the menu themselves, and where they're opened from.
const REACHED_FROM = {
  "/": "redirects to Home",
  "/models/new": "Model › New model, Home's starts, a dataset's Fit menu",
  "/models/recurrent/new": "Model › Repairable › New model",
  "/models/alt/new": "Model › Accelerated life › New model",
  "/models/joint/new": "Model › Condition and life › New model",
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
  "/data-model": "graph-access users: the menu's Account group where the preview is on, or by address",
  "/changes": "Home's What changed panel",
  "/oauth/consent": "an MCP client's sign-in",
};

test("every page in the app is in the menu or opened from a page that is", () => {
  const menu = new Set(everyLink(liveEntries(PREVIEW)));
  const missing = [...PAGES]
    .filter((p) => !hasParam(p) && !p.startsWith("/api-docs/"))
    .filter((p) => !menu.has(p) && !REACHED_FROM[p]);
  assert.deepEqual(missing, []);
});

test("every menu link is a page of the app", () => {
  for (const has of [{}, ALL, PREVIEW]) {
    for (const to of everyLink(liveEntries(has))) assert.ok(PAGES.has(to), to);
  }
});

test("the menu is Home, then Design, Operate and Analyse, then Reports and the Agent", () => {
  assert.deepEqual(SECTIONS.map((s) => s.label), ["Design", "Operate", "Analyse"]);
  const groups = groupBySection(buildMenu({ has: ALL }).main);
  assert.deepEqual(groups.map((g) => g.section?.label || g.key), ["home", "Design", "Operate", "Analyse", "end"]);
  assert.deepEqual(groups.map((g) => ids(g.entries)), [
    ["home"], ["systems"], ["assets", "maintenance", "risk"], ["data", "models", "strategy", "forecasts"],
    ["reports", "agent"],
  ]);
  const labels = buildMenu({ has: ALL }).main.map((e) => e.label);
  assert.deepEqual(labels, ["Home", "Systems", "Assets", "Maintenance", "Risk", "Data", "Model", "Strategy",
    "Forecasts", "Reports", "Reliability Agent"]);
});

test("each entry's children, as agreed", () => {
  const live = liveEntries(ALL);
  const kids = (id) => live.find((e) => e.id === id).children?.map((c) => c.label) || [];
  assert.deepEqual(kids("systems"), ["RBDs", "Simulation runs", "Product structure"]);
  assert.deepEqual(kids("assets"), ["Explorer", "Parts and stock", "Classes"]);
  assert.deepEqual(kids("maintenance"), ["RCM studies"]);
  assert.deepEqual(kids("data"), []);
  assert.deepEqual(kids("models"), ["Non-repairable", "Repairable", "Accelerated life", "Degradation",
    "Condition and life"]);
  assert.deepEqual(kids("risk"), []);
  assert.deepEqual(kids("strategy"), ["Optimal replacement", "Compare two models", "Failure finding", "Test planning"]);
  assert.deepEqual(kids("forecasts"), []);
});

test("an entry's landing page is never also one of its children", () => {
  for (const has of [{}, ALL]) {
    for (const e of liveEntries(has)) {
      // Only an entry that opens on its first child (Systems on its RBDs) lists it.
      (e.children || []).forEach((c, i) => {
        if (e.opensOnFirstChild && i === 0) assert.equal(c.to, e.to, `${e.label} opens on its first child`);
        else assert.notEqual(c.to, e.to, `${e.label} repeats its landing page`);
      });
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

test("Risk shows where the workspace uses it, and opens straight on Condition monitoring", () => {
  // Uses it: tracked items, or a degradation or condition-and-life model (the
  // server's /api/me/roles `uses`), or the menu preview is on.
  assert.ok(!ids(liveEntries({ maintenance: true, agent: true })).includes("risk"));
  for (const has of [{ risk: true }, ALL, PREVIEW]) {
    const risk = liveEntries(has).find((e) => e.id === "risk");
    assert.equal(risk.label, "Risk");
    assert.equal(risk.section, "operate");
    // Its one page so far is its landing: no children, nothing repeated.
    assert.equal(risk.to, "/risk");
    assert.equal(risk.children, undefined);
  }
  // A Risk landing of its own, when there is one, puts Condition monitoring under it.
  const later = liveEntries({ risk: true, riskOverview: true }).find((e) => e.id === "risk");
  assert.deepEqual(later.children.map((c) => c.label), ["Condition monitoring"]);
  // The analyst, planner and fleet manager use it.
  for (const role of ["analyst", "planner", "fleet"]) {
    assert.ok(ROLES.find((r) => r.id === role).entries.includes("risk"), role);
  }
  // Its pages light it; the old Degradation tracking addresses land on them.
  const live = liveEntries(ALL);
  assert.equal(activeEntry(live, "/risk").id, "risk");
  assert.equal(activeEntry(live, "/risk/f1").id, "risk");
  assert.deepEqual(crumbsFor(live, "risk", "/risk"), []);
  assert.deepEqual(crumbsFor(live, "risk", "/risk/f1"), [{ label: "Risk", to: "/risk" }]);
  assert.equal(movedTo("/models/tracking/f1"), "/risk/f1");
  assert.equal(itemPath("tracked_fleets", "f1"), "/risk/f1");
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
  assert.deepEqual(ids(more), ["systems", "risk", "data", "models", "strategy", "forecasts", "reports", "agent"]);
  assert.equal(main[1].to, "/maintenance");
});

test("a fleet manager leads with Forecasts, then the assets and their maintenance", () => {
  const { main } = buildMenu({ roles: ["fleet"], has: ALL });
  assert.deepEqual(ids(main), ["home", "assets", "risk", "maintenance", "forecasts", "models", "data", "reports"]);
  assert.deepEqual(homeCards(["fleet"]), ["fleets", "due"]);
});

test("picking every role shows everything", () => {
  const { main, more } = buildMenu({ roles: ROLE_IDS, has: ALL });
  assert.deepEqual(new Set(ids(main)), new Set(ids(liveEntries(ALL))));
  assert.deepEqual(more, []);
});

test("shown entries keep their sections, in role order within each", () => {
  const { main } = buildMenu({ roles: ["planner", "analyst"], has: ALL });
  assert.deepEqual(ids(main), ["home", "systems", "maintenance", "assets", "risk", "forecasts", "strategy", "data",
    "models", "reports", "agent"]);
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
  assert.deepEqual(at("/models/life"), ["models", "Non-repairable"]);
  assert.deepEqual(at("/models/m/abc"), ["models", "Non-repairable"]);
  assert.deepEqual(at("/models/new"), ["models", "Non-repairable"]);
  assert.deepEqual(at("/models/joint/x"), ["models", "Condition and life"]);
  assert.deepEqual(at("/risk"), ["risk", null]);
  assert.deepEqual(at("/risk/f1"), ["risk", null]);
  assert.deepEqual(at("/data"), ["data", null]);
  assert.deepEqual(at("/data/d1"), ["data", null]);
  // Systems opens on its RBDs; a diagram's page lights RBDs.
  assert.deepEqual(at("/systems/rbds"), ["systems", "RBDs"]);
  assert.deepEqual(at("/systems/b/r1"), ["systems", "RBDs"]);
  assert.deepEqual(at("/systems/b"), ["systems", "RBDs"]);
  assert.deepEqual(at("/systems/runs"), ["systems", "Simulation runs"]);
  assert.deepEqual(at("/systems/runs/x"), ["systems", "Simulation runs"]);
  assert.deepEqual(at("/strategy/test-planning/life"), ["strategy", "Test planning"]);
  assert.deepEqual(at("/strategy/analyses/x"), ["strategy", null]);
  assert.deepEqual(at("/forecasts/f"), ["forecasts", null]);
  // Assets opens on the top-level places; a position's, location's or item's
  // page is under the Explorer, as the Explorer itself is.
  assert.deepEqual(at("/asset-register"), ["assets", null]);
  assert.deepEqual(at("/asset-register/explorer"), ["assets", "Explorer"]);
  assert.deepEqual(at("/asset-register/positions/p1"), ["assets", "Explorer"]);
  assert.deepEqual(at("/asset-register/locations/l1"), ["assets", "Explorer"]);
  assert.deepEqual(at("/asset-register/items/i1"), ["assets", "Explorer"]);
  assert.deepEqual(at("/asset-register/parts/x"), ["assets", "Parts and stock"]);
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
  assert.deepEqual(crumbsFor(live, "models", "/models/life"), [{ label: "Model", to: "/models" }]);
  assert.deepEqual(crumbsFor(live, "models", "/models/m/x", "/models/life"),
    [{ label: "Model", to: "/models" }, { label: "Non-repairable", to: "/models/life" }]);
  assert.deepEqual(crumbsFor(live, "maintenance", "/maintenance/rcm/s", "/maintenance/rcm"),
    [{ label: "Maintenance", to: "/maintenance" }, { label: "RCM studies", to: "/maintenance/rcm" }]);
  // Without Reliafy Maintenance, Maintenance is the RCM studies: one crumb, to a page the user has.
  const none = liveEntries({});
  assert.deepEqual(crumbsFor(none, "maintenance", "/maintenance/rcm"), []);
  // Systems opens on its RBDs: a diagram's crumb is RBDs alone; a run's starts at Systems.
  assert.deepEqual(crumbsFor(live, "systems", "/systems/rbds", "/systems/rbds"), []);
  assert.deepEqual(crumbsFor(live, "systems", "/systems/b/x", "/systems/rbds"), [{ label: "RBDs", to: "/systems/rbds" }]);
  assert.deepEqual(crumbsFor(live, "systems", "/systems/runs/x", "/systems/runs"),
    [{ label: "Systems", to: "/systems/rbds" }, { label: "Simulation runs", to: "/systems/runs" }]);
  assert.deepEqual(crumbsFor(none, "maintenance", "/maintenance/rcm/s", "/maintenance/rcm"),
    [{ label: "Maintenance", to: "/maintenance/rcm" }]);
  assert.deepEqual(crumbsFor(none, "assets", "/asset-register/explorer"), []);
  assert.deepEqual(crumbsFor(live, "assets", "/asset-register/explorer"), [{ label: "Assets", to: "/asset-register" }]);
});

test("RBDs show for everyone who sees Systems, on every plan and in every role's lens", () => {
  for (const has of [{}, ALL, PREVIEW]) {
    for (const roles of [[], ...ROLE_IDS.map((r) => [r])]) {
      const { main, more } = buildMenu({ roles, has });
      const systems = [...main, ...more].find((e) => e.id === "systems");
      assert.ok(systems, `Systems is in the menu for ${roles}`);
      assert.equal(systems.to, "/systems/rbds");
      assert.equal(systems.children[0].label, "RBDs", `${roles}`);
    }
  }
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
  ["/rbds", "/systems/rbds"],
  ["/rbds/list", "/systems/rbds"],
  ["/rbds/b", "/systems/b"],
  ["/rbds/b/x", "/systems/b/x"],
  ["/rbds/runs", "/systems/runs"],
  ["/rbds/runs/compare", "/systems/runs/compare"],
  ["/rbds/runs/x", "/systems/runs/x"],
  ["/fleet", "/forecasts"],
  ["/fleet/forecasts", "/forecasts"],
  ["/fleet/forecasts/x", "/forecasts/x"],
  ["/fleet/tracking", "/risk"],
  ["/fleet/tracking/x", "/risk/x"],
  ["/models/tracking", "/risk"],
  ["/models/tracking/x", "/risk/x"],
  ["/strategy/analyses", "/strategy"],
  ["/strategy/tracking", "/risk"],
  ["/strategy/tracking/x", "/risk"],
  ["/strategy/demonstration-test", "/strategy/test-planning"],
  ["/rcm", "/maintenance/rcm"],
  ["/rcm/studies", "/maintenance/rcm"],
  ["/rcm/studies/x", "/maintenance/rcm/x"],
  ["/maintenance/positions/x", "/asset-register/positions/x"],
  ["/maintenance/items", "/asset-register/explorer?arrange=items"],
  ["/maintenance/items/x", "/asset-register/items/x"],
  ["/maintenance/locations", "/asset-register/explorer?arrange=locations"],
  ["/maintenance/locations/x", "/asset-register/locations/x"],
  ["/maintenance/classes", "/asset-register/classes"],
  ["/maintenance/classes/x", "/asset-register/classes/x"],
  ["/maintenance/parts", "/asset-register/parts"],
  ["/maintenance/parts/x", "/asset-register/parts/x"],
  ["/systems", "/systems/rbds"],
  ["/asset-register/positions", "/asset-register/explorer?arrange=positions"],
  ["/asset-register/items", "/asset-register/explorer?arrange=items"],
  ["/asset-register/locations", "/asset-register/explorer?arrange=locations"],
];

test("every earlier address redirects to its page's new place, with its id", () => {
  for (const [from, to] of OLD_TO_NEW) assert.equal(movedTo(from), to, from);
  assert.equal(MOVED.length, OLD_TO_NEW.length, "redirects.js and this table differ");
  // Ids are carried as they come (already encoded in the address).
  assert.equal(movedTo("/maintenance/classes/Pool%20pump"), "/asset-register/classes/Pool%20pump");
  assert.equal(movedTo("/modelling/m/"), null);
  // Addresses that didn't move (a position's, item's or location's own page among them).
  for (const path of ["/home", "/strategy", "/strategy/replacement", "/maintenance", "/maintenance/work-orders/w",
    "/asset-register/positions/p1", "/asset-register/items/i1", "/asset-register/locations/l1"]) {
    assert.equal(movedTo(path), null, path);
  }
});

test("an earlier address keeps its query: the target's first, then the rest", () => {
  // No query in the target: the old query and #hash exactly as they were.
  assert.equal(movedHref("/data/x", "?compare=a%20b", "#bounds"), "/data/x?compare=a%20b#bounds");
  // The old Positions, Items and Locations pages, with what their addresses carried.
  assert.equal(movedHref("/asset-register/explorer?arrange=positions", "?place=none"),
    "/asset-register/explorer?arrange=positions&place=none");
  assert.equal(movedHref("/asset-register/explorer?arrange=positions", "?arrange=flat&sel=p1"),
    "/asset-register/explorer?arrange=flat&sel=p1");
  assert.equal(movedHref("/asset-register/explorer?arrange=locations", "?sel=l1", "#top"),
    "/asset-register/explorer?arrange=locations&sel=l1#top");
  assert.equal(movedHref("/asset-register/explorer?arrange=items", ""), "/asset-register/explorer?arrange=items");
});

test("every redirect lands on a page of the app, and no page is also a redirect", () => {
  for (const m of MOVED) {
    assert.ok(PAGES.has(m.to.split("?")[0]), `${m.path} → ${m.to}, which isn't a page`);
    assert.ok(!PAGES.has(m.path), `${m.path} is both a page and a redirect`);
    for (const name of m.to.match(/:\w+/g) || []) assert.ok(m.path.includes(name), `${m.path} → ${m.to}`);
  }
});

test("no link in the app's own code points at an earlier address", () => {
  const old = /["'`(](\/(?:modelling|rbds|datasets|fleet|rcm)(?:[/"'`?#)]|$)|\/maintenance\/(?:positions|items|locations|classes|parts)\b|\/asset-register\/(?:positions|items|locations)(?:["'`?#)]|$))|(?:\bto[=:] ?\{?|navigate\(|href: )["'`]\/systems["'`?#]/;
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

test("not-yet-built entries show only where the menu preview is on", () => {
  const unbuilt = ["requirements", "failures"];
  const plain = liveEntries(ALL);
  for (const id of unbuilt) assert.ok(!plain.some((e) => e.id === id), id);
  const preview = liveEntries(PREVIEW);
  for (const id of unbuilt) assert.ok(preview.some((e) => e.id === id), id);
  const kids = (list, id) => list.find((e) => e.id === id).children?.map((c) => c.label) || [];
  assert.deepEqual(kids(plain, "systems"), ["RBDs", "Simulation runs", "Product structure"]);
  assert.deepEqual(kids(preview, "systems"), ["RBDs", "Simulation runs", "Product structure", "Fault trees", "FMECA"]);
  assert.deepEqual(kids(preview, "assets"), ["Explorer", "Parts and stock", "Classes", "Fleets"]);
  assert.deepEqual(kids(preview, "maintenance"), ["RCM studies", "Field inbox"]);
  assert.deepEqual(kids(preview, "data"), ["Library"]);
  assert.deepEqual(kids(plain, "data"), []);
});

test("every placeholder page has its text, and its entry in the preview menu", () => {
  const links = new Set(everyLink(liveEntries(PREVIEW)));
  for (const [id, page] of Object.entries(PLANNED)) {
    assert.ok(page.title && page.purpose && page.will.length, id);
    assert.ok([...links].some((to) => to.endsWith("/" + id) || to.endsWith("/" + (id === "inbox" ? "inbox" : id))), id);
  }
});
