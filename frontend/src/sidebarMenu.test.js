import { test } from "node:test";
import assert from "node:assert/strict";
import { activeTrail, buildMenu, flatEntries, liveEntries } from "./navigation.js";
import {
  menuKey, parseStored, startOpen, subItemLit, subItems, toggleKey, toggles, withOpen,
} from "./sidebarMenu.js";

const ALL = { maintenance: true, agent: true, risk: true };
const PREVIEW = { ...ALL, preview: true };
const find = (live, id) => flatEntries(live).find((e) => e.id === id) || live.find((e) => e.id === id);
const labels = (items) => items.map((i) => i.label);

test("entries with sub-pages toggle; the rest are links", () => {
  const live = liveEntries(ALL);
  const top = Object.fromEntries(live.map((e) => [e.id, toggles(e)]));
  assert.deepEqual(top, {
    home: false, products: false, assets: false, items: false, maintenance: true,
    modelling: true, decisions: true, reports: false, agent: false,
  });
  const second = (id) => Object.fromEntries(find(live, id).entries.map((e) => [e.id, toggles(e)]));
  assert.deepEqual(second("modelling"), { data: false, models: true, prediction: false, maintainability: false, systems: true });
  assert.deepEqual(second("decisions"), { strategy: true, forecasts: false, risk: true });
  // Maintenance has the RCM studies under it; without Reliafy Maintenance it is that page, a plain link.
  assert.equal(toggles(find(liveEntries(PREVIEW), "maintenance")), true);
  assert.equal(toggles(find(liveEntries({}), "maintenance")), false);
});

test("a group lists its entries; an entry lists exactly its children, never its landing page", () => {
  const live = liveEntries(PREVIEW);
  assert.deepEqual(labels(subItems(find(live, "modelling"))),
    ["Data", "Models", "Reliability prediction", "Maintainability prediction", "System models"]);
  assert.deepEqual(labels(subItems(find(live, "decisions"))), ["Strategy", "Forecasts", "Risk"]);
  assert.deepEqual(labels(subItems(find(live, "models"))), ["Non-repairable", "Repairable", "Accelerated life", "Degradation",
    "Condition and life", "Library"]);
  assert.deepEqual(labels(subItems(find(live, "strategy"))), ["Optimal replacement", "Compare two models", "Failure finding",
    "Test planning"]);
  // Maintenance lists its own page first (it only opens the list itself), then its sub-pages.
  assert.deepEqual(labels(subItems(find(live, "maintenance"))), ["Overview", "RCM studies", "Requests"]);
  assert.equal(subItems(find(live, "maintenance"))[0].to, "/maintenance");
  assert.deepEqual(labels(subItems(find(live, "systems"))), ["RBDs", "Fault trees", "Simulation runs"]);
  assert.deepEqual(labels(subItems(find(live, "risk"))), ["Condition monitoring"]);
  // The landing pages that drop out of the full menu (still pages, reached by breadcrumbs and links).
  for (const has of [{}, ALL, PREVIEW]) {
    for (const e of flatEntries(liveEntries(has))) {
      if (e.entries || e.opensOnFirstChild || e.landingLabel) continue;
      for (const i of subItems(e)) assert.notEqual(i.to, e.to, `${e.id} lists its landing page`);
    }
  }
  // No sub-pages, nothing.
  for (const id of ["home", "assets", "items", "data", "forecasts", "reports"]) assert.deepEqual(subItems(find(live, id)), [], id);
});

test("an entry whose landing page isn't available opens on its first child; with nothing left under it, it's a link", () => {
  // Maintenance without Reliafy Maintenance is the RCM studies page: a link, nothing under it.
  const m = find(liveEntries({}), "maintenance");
  assert.equal(m.to, "/maintenance/rcm");
  assert.equal(toggles(m), false);
  assert.deepEqual(subItems(m), []);
  // With Reliafy Maintenance: its own page first, then the RCM studies.
  const m2 = find(liveEntries(ALL), "maintenance");
  assert.equal(m2.to, "/maintenance");
  assert.deepEqual(labels(subItems(m2)), ["Overview", "RCM studies"]);
  // The landing page's line is lit on the entry's pages that no child names.
  const lit = (path) => {
    const trail = activeTrail(liveEntries(ALL), path);
    return labels(subItems(m2).filter((i) => subItemLit(i, trail)));
  };
  assert.deepEqual(lit("/maintenance"), ["Overview"]);
  assert.deepEqual(lit("/maintenance/work-orders/w1"), ["Overview"]);
  assert.deepEqual(lit("/maintenance/rcm/s1"), ["RCM studies"]);
  assert.deepEqual(lit("/home"), []);
});

test("the current page's entry and its group start open; nothing else does", () => {
  const live = liveEntries(ALL);
  assert.deepEqual(startOpen(live, "/home"), []);
  assert.deepEqual(startOpen(live, "/data"), ["modelling"]);
  assert.deepEqual(startOpen(live, "/models"), ["modelling", "models"]);
  assert.deepEqual(startOpen(live, "/models/recurrent"), ["modelling", "models"]);
  assert.deepEqual(startOpen(live, "/models/m/abc"), ["modelling", "models"]);
  assert.deepEqual(startOpen(live, "/systems/b/abc"), ["modelling", "systems"]);
  assert.deepEqual(startOpen(live, "/strategy/analyses/x"), ["decisions", "strategy"]);
  assert.deepEqual(startOpen(live, "/forecasts"), ["decisions"]);
  assert.deepEqual(startOpen(live, "/risk"), ["decisions", "risk"]);
  assert.deepEqual(startOpen(live, "/asset-register/explorer"), []);
  assert.deepEqual(startOpen(liveEntries(PREVIEW), "/maintenance/inbox"), ["maintenance"]);
  assert.deepEqual(startOpen(liveEntries(ALL), "/maintenance"), ["maintenance"]);
  assert.deepEqual(startOpen(liveEntries({}), "/maintenance/rcm"), []);
  // Under More too: the roles don't change what's open.
  const { main, more } = buildMenu({ roles: ["technician"], has: ALL });
  assert.deepEqual(startOpen([...main, ...more], "/models/alt"), ["modelling", "models"]);
});

test("opening one never closes another; toggling flips one key", () => {
  assert.deepEqual(toggleKey([], "modelling"), ["modelling"]);
  assert.deepEqual(toggleKey(["modelling", "decisions"], "modelling"), ["decisions"]);
  assert.deepEqual(toggleKey(["decisions"], "models"), ["decisions", "models"]);
  const open = ["decisions"];
  assert.equal(withOpen(open, ["decisions"]), open);
  assert.deepEqual(withOpen(open, ["modelling", "models"]), ["decisions", "modelling", "models"]);
  assert.equal(menuKey({ id: "models", to: "/models" }), "models");
});

test("what the session kept is read defensively", () => {
  assert.deepEqual(parseStored('["modelling","models"]'), ["modelling", "models"]);
  assert.deepEqual(parseStored(null), []);
  assert.deepEqual(parseStored("not json"), []);
  assert.deepEqual(parseStored('{"a":1}'), []);
  assert.deepEqual(parseStored('["a",2,null]'), ["a"]);
});

test("lit sub-items: a child on its own pages; a toggle on its pages no child names, or on all of them while closed", () => {
  const live = liveEntries(ALL);
  const models = find(live, "models");
  const [nonRep, rep] = subItems(models);
  let trail = activeTrail(live, "/models");
  assert.equal(subItemLit(rep, trail), false);
  assert.equal(subItemLit(models, trail, true), true);
  assert.equal(subItemLit(models, trail, false), true);
  trail = activeTrail(live, "/models/recurrent");
  assert.equal(subItemLit(rep, trail), true);
  assert.equal(subItemLit(models, trail, true), false);
  assert.equal(subItemLit(models, trail, false), true);
  trail = activeTrail(live, "/models/m/abc");
  assert.equal(subItemLit(nonRep, trail), true);
  // A saved analysis's page (no child names it) lights Strategy.
  trail = activeTrail(live, "/strategy/analyses/x");
  assert.equal(subItemLit(find(live, "strategy"), trail, true), true);
  // A plain entry is lit on its pages.
  trail = activeTrail(live, "/data/abc");
  assert.equal(subItemLit(find(live, "data"), trail), true);
});
