import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  ENTRIES, ROLES, ROLE_IDS, SECTIONS, activeEntry, buildMenu, childActive, entryActive, groupBySection,
  homeCards, itemPath, liveEntries,
} from "./navigation.js";
import { appRoutes, hasParam } from "../smoke/routes.js";

const ALL = { maintenance: true, agent: true };
const ids = (entries) => entries.map((e) => e.id);
const everyLink = (entries) => entries.flatMap((e) => [e.to, ...(e.children || []).map((c) => c.to)]);

// Pages that aren't in the menu themselves, and where they're opened from.
const REACHED_FROM = {
  "/": "redirects to Home",
  "/models/new": "Models › New model, Home's quick starts, a dataset's Fit a model",
  "/models/recurrent/new": "Models › Recurrent › New",
  "/models/alt/new": "Models › Accelerated life › New",
  "/systems/b": "Systems › New diagram, Home's quick starts",
  "/systems/runs/compare": "Systems › Simulation runs › Compare",
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
  const missing = appRoutes()
    .filter((r) => !r.redirect && !hasParam(r.path))
    .map((r) => r.path)
    .filter((p) => !menu.has(p) && !REACHED_FROM[p]);
  assert.deepEqual(missing, []);
});

test("every menu link is a page of the app", () => {
  const pages = new Set(appRoutes().filter((r) => !r.redirect).map((r) => r.path));
  for (const to of everyLink(liveEntries(ALL))) assert.ok(pages.has(to), to);
});

test("every earlier address redirects to a page that exists, with its id", () => {
  const routes = appRoutes();
  const pages = new Set(routes.filter((r) => !r.redirect).map((r) => r.path));
  const moved = routes.filter((r) => r.redirect);
  for (const r of moved) {
    assert.ok(r.target, `${r.path} has no target`);
    assert.ok(pages.has(r.target), `${r.path} → ${r.target}, which isn't a page`);
    // An id in the new address comes from the old one.
    for (const name of r.target.match(/:\w+/g) || []) assert.ok(r.path.includes(name), `${r.path} → ${r.target}`);
  }
  // The renamed sections (#438), every one of their old addresses.
  const old = new Set(moved.map((r) => r.path));
  for (const path of [
    "/modelling", "/modelling/models", "/modelling/life", "/modelling/new", "/modelling/m/:id",
    "/modelling/degradation", "/modelling/degradation/:id", "/modelling/recurrent", "/modelling/recurrent/new",
    "/modelling/recurrent/:id", "/modelling/alt", "/modelling/alt/new", "/modelling/alt/:id",
    "/rbds", "/rbds/list", "/rbds/b", "/rbds/b/:id", "/rbds/runs", "/rbds/runs/compare", "/rbds/runs/:runId",
    "/datasets", "/datasets/list", "/datasets/d/:id", "/fleet", "/fleet/forecasts", "/fleet/forecasts/:id",
    "/fleet/tracking", "/fleet/tracking/:fleetId", "/strategy/tracking", "/strategy/tracking/:modelId",
    "/strategy/analyses", "/rcm", "/rcm/studies", "/rcm/studies/:id", "/maintenance/positions/:id",
    "/maintenance/items", "/maintenance/items/:id", "/maintenance/locations", "/maintenance/locations/:id",
    "/maintenance/classes", "/maintenance/classes/:name", "/maintenance/parts", "/maintenance/parts/:id", "/tokens",
  ]) assert.ok(old.has(path), `${path} doesn't redirect`);
});

test("the menu is Home, then Design, Operate and Analyse, then Reports and the Agent", () => {
  assert.deepEqual(SECTIONS.map((s) => s.label), ["Design", "Operate", "Analyse"]);
  const groups = groupBySection(buildMenu({ has: ALL }).main);
  assert.deepEqual(groups.map((g) => g.section?.label || g.key), ["home", "Design", "Operate", "Analyse", "end"]);
  assert.deepEqual(groups.map((g) => ids(g.entries)), [
    ["home"], ["systems"], ["assets", "maintenance"], ["data", "models", "strategy", "forecasts"], ["reports", "agent"],
  ]);
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
  // Maintenance opens on the work orders.
  assert.equal(main[1].to, "/maintenance");
});

test("picking every role shows everything", () => {
  const { main, more } = buildMenu({ roles: ROLE_IDS, has: ALL });
  assert.deepEqual(new Set(ids(main)), new Set(ids(liveEntries(ALL))));
  assert.deepEqual(more, []);
});

test("shown entries keep their sections, in role order within each", () => {
  const { main } = buildMenu({ roles: ["planner", "analyst"], has: ALL });
  // planner: maintenance, assets, forecasts, strategy, reports; then analyst's.
  assert.deepEqual(ids(main), ["home", "systems", "maintenance", "assets", "forecasts", "strategy", "data", "models",
    "reports", "agent"]);
  assert.deepEqual(groupBySection(main).map((g) => g.key), ["home", "design", "operate", "analyse", "end"]);
});

test("unknown roles are ignored: everything shown", () => {
  assert.deepEqual(buildMenu({ roles: ["astronaut"], has: ALL }).more, []);
});

test("entries for what a workspace doesn't have are hidden", () => {
  const none = liveEntries({});
  assert.ok(!ids(none).includes("assets"));
  assert.ok(!ids(none).includes("agent"));
  // Maintenance without Reliafy Maintenance is the RCM studies.
  const maint = none.find((e) => e.id === "maintenance");
  assert.equal(maint.to, "/maintenance/rcm");
  assert.deepEqual(maint.children.map((c) => c.to), ["/maintenance/rcm"]);
  // Product structure is in Reliafy Maintenance's parts.
  assert.ok(!everyLink(none).includes("/systems/structure"));
  // Requirements and Failures until they exist.
  for (const has of [{}, ALL]) {
    assert.ok(!ids(liveEntries(has)).includes("requirements"));
    assert.ok(!ids(liveEntries(has)).includes("failures"));
  }
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

test("a page lights its entry, and its child", () => {
  const live = liveEntries(ALL);
  assert.equal(activeEntry(live, "/models/m/abc").id, "models");
  assert.equal(activeEntry(live, "/asset-register/items/i1").id, "assets");
  assert.equal(activeEntry(live, "/maintenance/rcm/s1").id, "maintenance");
  assert.equal(activeEntry(live, "/systems/structure").id, "systems");
  assert.equal(activeEntry(live, "/home").id, "home");
  assert.equal(activeEntry(live, "/settings"), null);
  const models = live.find((e) => e.id === "models");
  assert.ok(entryActive(models, "/models"));
  assert.ok(!entryActive(models, "/modelsx"));
  const [all, life] = models.children;
  assert.ok(childActive(all, "/models") && !childActive(all, "/models/life"));
  assert.ok(childActive(life, "/models/life"));
});

test("Home leads with the primary role's cards", () => {
  assert.deepEqual(homeCards([]), ["due", "recent-models", "recent-systems", "recent-data"]);
  assert.equal(homeCards(["technician"])[0], "work-today");
  assert.equal(homeCards(["planner"])[0], "due");
  assert.deepEqual(homeCards(["analyst"]).slice(0, 2), ["recent-models", "recent-data"]);
  assert.equal(homeCards(["manager", "technician"])[0], "waiting");
  assert.equal(homeCards(["manager", "technician"])[1], "work-today");
  // Each card once.
  const cards = homeCards(ROLE_IDS);
  assert.equal(new Set(cards).size, cards.length);
});

test("saved items open at their new addresses", () => {
  assert.equal(itemPath("models", "m 1"), "/models/m/m%201");
  assert.equal(itemPath("rcm_studies", "s"), "/maintenance/rcm/s");
  assert.equal(itemPath("reports", "r"), null);
});
