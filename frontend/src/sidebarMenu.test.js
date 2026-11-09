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
    home: false, products: false, assets: false, items: false, maintenance: false,
    modelling: true, decisions: true, reports: false, agent: false,
  });
  const second = (id) => Object.fromEntries(find(live, id).entries.map((e) => [e.id, toggles(e)]));
  assert.deepEqual(second("modelling"), { data: false, models: true, prediction: false, maintainability: false, systems: true });
  assert.deepEqual(second("decisions"), { strategy: true, forecasts: false, risk: true });
  // Maintenance has sub-pages only where the menu preview is on.
  assert.equal(toggles(find(liveEntries(PREVIEW), "maintenance")), true);
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
  assert.deepEqual(labels(subItems(find(live, "maintenance"))), ["Requests"]);
  assert.deepEqual(labels(subItems(find(live, "systems"))), ["RBDs", "Fault trees", "Simulation runs"]);
  assert.deepEqual(labels(subItems(find(live, "risk"))), ["Condition monitoring"]);
  // The landing pages that drop out of the full menu (still pages, reached by breadcrumbs and links).
  for (const has of [{}, ALL, PREVIEW]) {
    for (const e of flatEntries(liveEntries(has))) {
      if (e.entries || e.opensOnFirstChild) continue;
      for (const i of subItems(e)) assert.notEqual(i.to, e.to, `${e.id} lists its landing page`);
    }
  }
  // No sub-pages, nothing.
  for (const id of ["home", "assets", "items", "data", "forecasts", "reports"]) assert.deepEqual(subItems(find(live, id)), [], id);
});

test("an entry whose landing page isn't available opens on its first child; with nothing left under it, it's a link", () => {
  // Maintenance without Reliafy Maintenance opens on the preview's Requests page.
  const m = find(liveEntries({ preview: true }), "maintenance");
  assert.equal(m.to, "/maintenance/inbox");
  assert.equal(toggles(m), false);
  // With Reliafy Maintenance but no preview: no sub-pages, a link to /maintenance.
  const m2 = find(liveEntries(ALL), "maintenance");
  assert.equal(m2.to, "/maintenance");
  assert.equal(toggles(m2), false);
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
  assert.deepEqual(startOpen(liveEntries(ALL), "/maintenance"), []);
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
