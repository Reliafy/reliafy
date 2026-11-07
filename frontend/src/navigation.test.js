import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import {
  ENTRIES, MENU_ENTRIES, RESERVED_IDS, ROLES, ROLE_IDS, activeEntry, activeTrail, buildMenu, childActive, crumbsFor,
  datasetPath, entryActive, flatEntries, homeCards, itemPath, liveEntries,
} from "./navigation.js";
import { MOVED, movedHref, movedTo } from "./redirects.js";
import { PLANNED } from "./plannedPages.js";
import { appRoutes, hasParam } from "../smoke/routes.js";

const ALL = { maintenance: true, agent: true, risk: true };
const PREVIEW = { ...ALL, preview: true };
const ids = (entries) => entries.map((e) => e.id);
// Every page the menu links to, at every level (a group has no page of its own).
const everyLink = (entries) => flatEntries(entries).flatMap((e) => [e.to, ...(e.children || []).map((c) => c.to)]);
const PAGES = new Set(appRoutes().filter((r) => !r.redirect).map((r) => r.path));
const find = (live, id) => flatEntries(live).find((e) => e.id === id);
const kids = (live, id) => find(live, id)?.children?.map((c) => c.label) || [];

// Pages that aren't in the menu themselves, and where they're opened from.
const REACHED_FROM = {
  "/": "redirects to Home",
  "/models/new": "Models › New model, Home's starts, a dataset's Fit menu",
  "/models/recurrent/new": "Models › Repairable › New model",
  "/models/alt/new": "Models › Accelerated life › New model",
  "/models/joint/new": "Models › Condition and life › New model",
  "/maintainability/new": "Maintainability prediction › New prediction",
  "/systems/b": "RBDs › New diagram, Home's starts",
  "/predictions/new": "Reliability prediction › New prediction, a product's Analysis tab",
  "/systems/runs/compare": "Simulation runs › Compare",
  "/asset-register/explorer": "an asset on Assets' landing page, and every position's, location's and item's breadcrumbs",
  "/strategy/test-planning/sequential": "Test planning's tabs",
  "/strategy/test-planning/life": "Test planning's tabs",
  "/strategy/test-planning/accelerated": "Test planning's tabs",
  "/strategy/test-planning/comparison": "Test planning's tabs",
  "/requirements": "a preview-only placeholder, by address",
  "/failures": "a preview-only placeholder, by address",
  "/asset-register/fleets": "a preview-only placeholder, by address",
  "/settings": "the menu's Account group",
  "/billing": "the menu's Account group",
  "/api-docs": "the menu's Account group",
  "/team": "the top bar's team settings",
  "/data-model": "graph-access users: the menu's Account group where the preview is on, or by address",
  "/changes": "Home's What changed panel",
  "/systems/fault-trees/new": "Fault trees' New fault tree",
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

test("the menu is one flat list: Home, Products, Assets, Items, Maintenance, Modelling, Decisions, Reports, the Agent", () => {
  const { main } = buildMenu({ has: ALL });
  assert.deepEqual(ids(main), ["home", "products", "assets", "items", "maintenance", "modelling", "decisions", "reports", "agent"]);
  assert.deepEqual(main.map((e) => e.label),
    ["Home", "Products", "Assets", "Items", "Maintenance", "Modelling", "Decisions", "Reports", "Reliability Agent"]);
  // No section headings any more.
  for (const e of ENTRIES) assert.equal(e.section, undefined, e.id);
});

test("Modelling and Decisions are groups: their entries, each with its children", () => {
  const live = liveEntries(ALL);
  const group = (id) => live.find((e) => e.id === id).entries.map((e) => e.label);
  assert.deepEqual(group("modelling"), ["Data", "Models", "Reliability prediction", "Maintainability prediction", "System models"]);
  assert.deepEqual(kids(live, "prediction"), []);
  assert.deepEqual(group("decisions"), ["Strategy", "Forecasts", "Risk"]);
  assert.deepEqual(kids(live, "data"), []);
  assert.deepEqual(kids(live, "models"), ["Non-repairable", "Repairable", "Accelerated life", "Degradation",
    "Condition and life"]);
  assert.deepEqual(kids(live, "maintainability"), []);
  assert.deepEqual(kids(live, "systems"), ["RBDs", "Fault trees", "Simulation runs"]);
  assert.deepEqual(kids(live, "strategy"), ["Optimal replacement", "Compare two models", "Failure finding",
    "Test planning"]);
  assert.deepEqual(kids(live, "forecasts"), []);
  assert.deepEqual(kids(live, "risk"), ["Condition monitoring"]);
  // Assets is one entry with no children; Maintenance has none outside the preview.
  assert.deepEqual(kids(live, "assets"), []);
  assert.deepEqual(kids(live, "maintenance"), []);
  // Three levels at most: a group's entries have children, never entries.
  for (const e of live) for (const x of e.entries || []) assert.equal(x.entries, undefined, x.id);
});

test("a group opens on its first live entry; an entry with no landing page opens on its first child", () => {
  const live = liveEntries(ALL);
  const to = (id) => find(live, id)?.to || live.find((e) => e.id === id).to;
  assert.equal(live.find((e) => e.id === "modelling").to, "/data");
  assert.equal(live.find((e) => e.id === "decisions").to, "/strategy");
  // Entries with a landing page of their own open on it.
  assert.equal(to("data"), "/data");
  assert.equal(to("models"), "/models");
  assert.equal(to("strategy"), "/strategy");
  assert.equal(to("forecasts"), "/forecasts");
  // System models and Risk open on, and list, their first child.
  assert.equal(to("systems"), "/systems/rbds");
  assert.equal(find(live, "systems").children[0].to, "/systems/rbds");
  assert.equal(to("risk"), "/risk");
  assert.equal(find(live, "risk").children[0].label, "Condition monitoring");
  assert.equal(to("assets"), "/asset-register");
  assert.equal(to("maintenance"), "/maintenance");
});

test("a menu word is the title of the page it opens", () => {
  // The page titles (SectionHeader's title) of each entry's landing page.
  const TITLES = {
    home: "Home", products: "Products", assets: "Assets", items: "Items", maintenance: "Maintenance", data: "Data", models: "Models",
    prediction: "Reliability prediction",
    strategy: "Strategy", forecasts: "Forecasts", reports: "Reports", agent: "Reliability Agent",
    maintainability: "Maintainability prediction",
  };
  for (const e of MENU_ENTRIES) {
    if (e.opensOnFirstChild) continue;
    assert.equal(e.label, TITLES[e.id], e.id);
  }
  // Those that open on a child: that child names the page (RBDs; Condition monitoring).
  const live = liveEntries(ALL);
  assert.equal(find(live, "risk").children[0].label, "Condition monitoring");
  assert.equal(find(live, "systems").children[0].label, "RBDs");
});

test("an entry's landing page is never also one of its children", () => {
  for (const has of [{}, ALL, PREVIEW]) {
    for (const e of flatEntries(liveEntries(has))) {
      (e.children || []).forEach((c, i) => {
        if (e.opensOnFirstChild && i === 0) assert.equal(c.to, e.to, `${e.label} opens on its first child`);
        else assert.notEqual(c.to, e.to, `${e.label} repeats its landing page`);
      });
    }
  }
});

test("without Reliafy Maintenance: no Assets and no Maintenance", () => {
  const none = liveEntries({});
  assert.deepEqual(ids(none), ["home", "modelling", "decisions", "reports"]);
  assert.ok(!everyLink(none).includes("/asset-register"));
  assert.equal(liveEntries(ALL).find((e) => e.id === "maintenance").to, "/maintenance");
  // With only the preview, Maintenance opens on its Field inbox.
  assert.equal(liveEntries({ preview: true }).find((e) => e.id === "maintenance").to, "/maintenance/inbox");
});

test("Risk shows where the workspace uses it", () => {
  // Uses it: tracked items, or a degradation or condition-and-life model (the
  // server's /api/me/roles `uses`), or the menu preview is on.
  assert.ok(!find(liveEntries({ maintenance: true, agent: true }), "risk"));
  assert.deepEqual(liveEntries({}).find((e) => e.id === "decisions").entries.map((e) => e.id), ["strategy", "forecasts"]);
  for (const has of [{ risk: true }, ALL, PREVIEW]) assert.ok(find(liveEntries(has), "risk"));
  // Its pages light it; the old Degradation tracking addresses land on them.
  const live = liveEntries(ALL);
  assert.equal(activeEntry(live, "/risk").id, "decisions");
  assert.deepEqual(crumbsFor(live, "risk", "/risk"), []);
  assert.deepEqual(crumbsFor(live, "risk", "/risk/f1"), [{ label: "Condition monitoring", to: "/risk" }]);
  assert.equal(movedTo("/models/tracking/f1"), "/risk/f1");
  assert.equal(itemPath("tracked_fleets", "f1"), "/risk/f1");
});

test("no placeholder entries: Requirements, Failures, Fleets and FMECA aren't in the menu", () => {
  for (const has of [{}, ALL, PREVIEW]) {
    const links = everyLink(liveEntries(has));
    for (const to of ["/requirements", "/failures", "/asset-register/fleets", "/systems/fmeca"]) {
      assert.ok(!links.includes(to), to);
    }
  }
});

test("Fault trees sits under System models, between RBDs and Simulation runs, for everyone", () => {
  for (const has of [{}, ALL]) {
    const systems = liveEntries(has).find((e) => e.id === "modelling").entries.find((e) => e.id === "systems");
    assert.deepEqual(systems.children.map((c) => c.to), ["/systems/rbds", "/systems/fault-trees", "/systems/runs"]);
  }
  const live = liveEntries(ALL);
  assert.equal(activeEntry(live, "/systems/fault-trees/abc").id, "modelling");
  assert.equal(movedTo("/systems/fault-trees"), null);
});

test("no roles shows everything the workspace has, nothing under More", () => {
  const { main, more } = buildMenu({ roles: [], has: ALL });
  assert.deepEqual(ids(main), ids(liveEntries(ALL)));
  assert.deepEqual(more, []);
});

test("a technician sees Home, Assets, Items and Maintenance; the rest is under More", () => {
  const { main, more } = buildMenu({ roles: ["technician"], has: ALL });
  assert.deepEqual(ids(main), ["home", "assets", "items", "maintenance"]);
  assert.deepEqual(ids(more), ["products", "modelling", "decisions", "reports", "agent"]);
  assert.equal(main[3].to, "/maintenance");
});

test("a role keeps the menu's own order", () => {
  assert.deepEqual(ids(buildMenu({ roles: ["fleet"], has: ALL }).main),
    ["home", "assets", "items", "maintenance", "modelling", "decisions", "reports"]);
  assert.deepEqual(ids(buildMenu({ roles: ["planner", "analyst"], has: ALL }).main),
    ["home", "assets", "items", "maintenance", "modelling", "decisions", "reports", "agent"]);
  assert.deepEqual(ids(buildMenu({ roles: ["manager"], has: ALL }).main),
    ["home", "maintenance", "modelling", "decisions", "reports"]);
  assert.deepEqual(homeCards(["fleet"]), ["fleets", "due"]);
});

test("picking every role shows everything", () => {
  const { main, more } = buildMenu({ roles: ROLE_IDS, has: ALL });
  assert.deepEqual(ids(main), ids(liveEntries(ALL)));
  assert.deepEqual(more, []);
});

test("unknown roles are ignored: everything shown", () => {
  assert.deepEqual(buildMenu({ roles: ["astronaut"], has: ALL }).more, []);
});

test("roles name only top-level entries (or ones reserved for later)", () => {
  const known = new Set([...ENTRIES.map((e) => e.id), ...RESERVED_IDS]);
  for (const role of ROLES) for (const id of role.entries) assert.ok(known.has(id), `${role.id}: ${id}`);
  for (const id of RESERVED_IDS) assert.ok(!ENTRIES.some((e) => e.id === id), `${id} is in the menu: drop it from RESERVED_IDS`);
  assert.equal(new Set(ROLE_IDS).size, ROLES.length);
});

test("the roles are the server's", () => {
  const py = readFileSync(new URL("../../backend/services/roles.py", import.meta.url), "utf8");
  const server = /ROLE_IDS = \(([^)]*)\)/.exec(py)[1].match(/"(\w+)"/g).map((s) => s.slice(1, -1));
  assert.deepEqual(server, ROLE_IDS);
});

test("a page lights its place in the menu at every level", () => {
  const live = liveEntries(ALL);
  const at = (path) => {
    const t = activeTrail(live, path);
    return [t.top?.id || null, t.entry && t.entry !== t.top ? t.entry.id : null, t.child?.label || null];
  };
  assert.deepEqual(at("/home"), ["home", null, null]);
  assert.deepEqual(at("/models"), ["modelling", "models", null]);
  assert.deepEqual(at("/models/life"), ["modelling", "models", "Non-repairable"]);
  assert.deepEqual(at("/models/m/abc"), ["modelling", "models", "Non-repairable"]);
  assert.deepEqual(at("/models/new"), ["modelling", "models", "Non-repairable"]);
  assert.deepEqual(at("/models/recurrent/x"), ["modelling", "models", "Repairable"]);
  assert.deepEqual(at("/models/joint/x"), ["modelling", "models", "Condition and life"]);
  assert.deepEqual(at("/data"), ["modelling", "data", null]);
  assert.deepEqual(at("/data/d1"), ["modelling", "data", null]);
  assert.deepEqual(at("/systems/rbds"), ["modelling", "systems", "RBDs"]);
  assert.deepEqual(at("/systems/b/r1"), ["modelling", "systems", "RBDs"]);
  assert.deepEqual(at("/systems/b"), ["modelling", "systems", "RBDs"]);
  assert.deepEqual(at("/systems/runs/x"), ["modelling", "systems", "Simulation runs"]);
  assert.deepEqual(at("/strategy/test-planning/life"), ["decisions", "strategy", "Test planning"]);
  assert.deepEqual(at("/strategy/analyses/x"), ["decisions", "strategy", null]);
  assert.deepEqual(at("/forecasts/f"), ["decisions", "forecasts", null]);
  assert.deepEqual(at("/risk"), ["decisions", "risk", "Condition monitoring"]);
  assert.deepEqual(at("/risk/f1"), ["decisions", "risk", "Condition monitoring"]);
  // Assets is current on every page of the register, and on Product structure
  // (the longest match beats System models' /systems).
  for (const path of ["/asset-register", "/asset-register/explorer", "/asset-register/positions/p1",
    "/asset-register/locations/l1", "/asset-register/parts/x", "/asset-register/classes",
    "/systems/structure"]) {
    assert.deepEqual(at(path), ["assets", null, null], path);
  }
  // Products and Items: their landing pages, a product's page, and each item's own page.
  assert.deepEqual(at("/products"), ["products", null, null]);
  assert.deepEqual(at("/products/p1"), ["products", null, null]);
  assert.deepEqual(at("/items"), ["items", null, null]);
  assert.deepEqual(at("/asset-register/items/i1"), ["items", null, null]);
  assert.deepEqual(at("/maintenance/work-orders/w1"), ["maintenance", null, null]);
  assert.deepEqual(at("/reports"), ["reports", null, null]);
  assert.deepEqual(at("/settings"), [null, null, null]);
  // A prefix of a word isn't a match.
  assert.deepEqual(at("/modelsx"), [null, null, null]);
  assert.ok(entryActive(find(live, "models"), "/models"));
  assert.ok(childActive(find(live, "models").children[1], "/models/recurrent/x"));
  // Without Reliafy Maintenance there is no Maintenance entry to light.
  assert.equal(activeEntry(liveEntries({}), "/maintenance/work-orders/w1"), null);
});

test("a page's breadcrumbs: its entry, then its child, never a group", () => {
  const live = liveEntries(ALL);
  assert.deepEqual(crumbsFor(live, "models", "/models"), []);
  assert.deepEqual(crumbsFor(live, "models", "/models/life"), [{ label: "Models", to: "/models" }]);
  assert.deepEqual(crumbsFor(live, "models", "/models/recurrent/x", "/models/recurrent"),
    [{ label: "Models", to: "/models" }, { label: "Repairable", to: "/models/recurrent" }]);
  assert.deepEqual(crumbsFor(live, "models", "/models/m/x", "/models/life"),
    [{ label: "Models", to: "/models" }, { label: "Non-repairable", to: "/models/life" }]);
  assert.deepEqual(crumbsFor(live, "data", "/data/library"), [{ label: "Data", to: "/data" }]);
  assert.deepEqual(crumbsFor(live, "maintenance", "/maintenance/work-orders/w"), [{ label: "Maintenance", to: "/maintenance" }]);
  // No crumb names a group.
  assert.deepEqual(crumbsFor(live, "modelling", "/models/life"), []);
  assert.deepEqual(crumbsFor(live, "decisions", "/strategy/compare"), []);
  // Without Reliafy Maintenance there is no Maintenance entry: no crumb to a page the user doesn't have.
  const none = liveEntries({});
  assert.deepEqual(crumbsFor(none, "maintenance", "/maintenance/work-orders/w"), []);
  // System models opens on its RBDs: a diagram's crumb is RBDs alone; a run's starts at System models.
  assert.deepEqual(crumbsFor(live, "systems", "/systems/rbds", "/systems/rbds"), []);
  assert.deepEqual(crumbsFor(live, "systems", "/systems/b/x", "/systems/rbds"), [{ label: "RBDs", to: "/systems/rbds" }]);
  assert.deepEqual(crumbsFor(live, "systems", "/systems/b/x"), [{ label: "RBDs", to: "/systems/rbds" }]);
  assert.deepEqual(crumbsFor(live, "systems", "/systems/runs/x", "/systems/runs"),
    [{ label: "System models", to: "/systems/rbds" }, { label: "Simulation runs", to: "/systems/runs" }]);
  assert.deepEqual(crumbsFor(none, "assets", "/asset-register/classes"), []);
  assert.deepEqual(crumbsFor(live, "assets", "/asset-register/classes"), [{ label: "Assets", to: "/asset-register" }]);
  assert.deepEqual(crumbsFor(live, "assets", "/systems/structure"), [{ label: "Assets", to: "/asset-register" }]);
});

test("RBDs show for everyone, on every plan and in every role's lens", () => {
  for (const has of [{}, ALL, PREVIEW]) {
    for (const roles of [[], ...ROLE_IDS.map((r) => [r])]) {
      const { main, more } = buildMenu({ roles, has });
      const systems = find([...main, ...more], "systems");
      assert.ok(systems, `System models is in the menu for ${roles}`);
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
  // RCM studies are gone: the RCM is on the asset tree, not a saved item of its own.
  assert.equal(itemPath("rcm_studies", "s"), null);
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
  // The RCM studies, at /rcm and then under Maintenance: all to the Explorer's RCM tab (no study survives).
  ["/rcm", "/asset-register/explorer?tab=rcm"],
  ["/rcm/studies", "/asset-register/explorer?tab=rcm"],
  ["/rcm/studies/x", "/asset-register/explorer?tab=rcm"],
  ["/maintenance/rcm", "/asset-register/explorer?tab=rcm"],
  ["/maintenance/rcm/x", "/asset-register/explorer?tab=rcm"],
  ["/maintenance/positions/x", "/asset-register/positions/x"],
  ["/maintenance/items", "/items"],
  ["/maintenance/items/x", "/asset-register/items/x"],
  ["/maintenance/locations", "/asset-register/explorer?arrange=locations"],
  ["/maintenance/locations/x", "/asset-register/locations/x"],
  ["/maintenance/classes", "/asset-register/explorer?tab=classes&scope=all"],
  ["/maintenance/classes/x", "/asset-register/explorer?tab=classes&scope=all&class=x"],
  ["/maintenance/parts", "/asset-register/explorer?tab=parts&scope=all"],
  ["/maintenance/parts/x", "/asset-register/parts/x"],
  ["/systems", "/systems/rbds"],
  ["/asset-register/positions", "/asset-register/explorer?arrange=positions"],
  ["/asset-register/items", "/items"],
  ["/asset-register/locations", "/asset-register/explorer?arrange=locations"],
  ["/systems/fmeca", "/asset-register/explorer?tab=fmea"],
  // Parts and stock and Classes are tabs of the asset tree, on everything.
  ["/asset-register/parts", "/asset-register/explorer?tab=parts&scope=all"],
  ["/asset-register/classes", "/asset-register/explorer?tab=classes&scope=all"],
  ["/asset-register/classes/x", "/asset-register/explorer?tab=classes&scope=all&class=x"],
  ["/systems/structure", "/asset-register/explorer?tab=parts&scope=all&show=structure"],
];

test("every earlier address redirects to its page's new place, with its id", () => {
  for (const [from, to] of OLD_TO_NEW) assert.equal(movedTo(from), to, from);
  assert.equal(MOVED.length, OLD_TO_NEW.length, "redirects.js and this table differ");
  // Ids are carried as they come (already encoded in the address).
  assert.equal(movedTo("/maintenance/classes/Pool%20pump"), "/asset-register/explorer?tab=classes&scope=all&class=Pool%20pump");
  assert.equal(movedTo("/asset-register/classes/Pool%20pump"), "/asset-register/explorer?tab=classes&scope=all&class=Pool%20pump");
  // A class's address with a query of its own keeps it after the tab's.
  assert.equal(movedHref(movedTo("/asset-register/classes/Pump"), "?sel=p1"), "/asset-register/explorer?tab=classes&scope=all&class=Pump&sel=p1");
  // Each part's own page stays.
  assert.equal(movedTo("/asset-register/parts/pt1"), null);
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
  // An RCM study's address from an email: the tab first, then the rest.
  assert.equal(movedHref("/asset-register/explorer?tab=rcm", "?from=email"), "/asset-register/explorer?tab=rcm&from=email");
  // The old Positions page's Flat arrangement is gone: by positions, p1 picked.
  assert.equal(movedHref("/asset-register/explorer?arrange=positions", "?arrange=flat&sel=p1"),
    "/asset-register/explorer?arrange=positions&sel=p1");
  assert.equal(movedHref("/asset-register/explorer?arrange=locations", "?sel=l1", "#top"),
    "/asset-register/explorer?arrange=locations&sel=l1#top");
  assert.equal(movedHref("/items", "?sel=i1"), "/items?sel=i1");
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
  const plain = liveEntries(ALL);
  const preview = liveEntries(PREVIEW);
  assert.deepEqual(kids(plain, "data"), []);
  assert.deepEqual(kids(preview, "data"), ["Library"]);
  assert.deepEqual(kids(plain, "maintenance"), []);
  assert.deepEqual(kids(preview, "maintenance"), ["Field inbox"]);
  assert.deepEqual(kids(preview, "systems"), ["RBDs", "Fault trees", "Simulation runs"]);
  assert.deepEqual(kids(preview, "assets"), []);
});

test("every placeholder page has its text; Library and Field inbox are in the preview menu", () => {
  const links = new Set(everyLink(liveEntries(PREVIEW)));
  for (const [id, page] of Object.entries(PLANNED)) assert.ok(page.title && page.purpose && page.will.length, id);
  assert.ok(links.has("/data/library"));
  assert.ok(links.has("/maintenance/inbox"));
  assert.deepEqual(Object.keys(PLANNED).sort(), ["failures", "fleets", "inbox", "library", "requirements"]);
});
