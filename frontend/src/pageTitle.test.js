import { test } from "node:test";
import assert from "node:assert/strict";
import { formatTitle, titleFor, titleParts } from "./pageTitle.js";
import { MENU_ENTRIES } from "./navigation.js";

test("formatTitle joins parts, drops blanks and repeats, ends with Reliafy", () => {
  assert.equal(formatTitle("Feed pump train", "RBDs"), "Feed pump train · RBDs · Reliafy");
  assert.equal(formatTitle(null, "", "RBDs", "RBDs"), "RBDs · Reliafy");
  assert.equal(formatTitle(), "Reliafy");
});

test("landing and child pages take their menu labels", () => {
  assert.equal(titleFor("/home"), "Home · Reliafy");
  assert.equal(titleFor("/models"), "Models · Reliafy");
  assert.equal(titleFor("/models/life"), "Non-repairable · Models · Reliafy");
  assert.equal(titleFor("/strategy/failure-finding"), "Failure finding · Strategy · Reliafy");
  assert.equal(titleFor("/asset-register/explorer"), "Explorer · Assets · Reliafy");
  assert.equal(titleFor("/asset-register"), "Assets · Reliafy");
  assert.equal(titleFor("/asset-register/parts"), "Parts and stock · Assets · Reliafy");
  assert.equal(titleFor("/asset-register/classes/Pool%20pump"), "Classes · Assets · Reliafy");
  assert.equal(titleFor("/systems/structure"), "Product structure · Assets · Reliafy");
});

test("an entry that opens on a child is named by the child, as its crumbs are", () => {
  assert.equal(titleFor("/systems/rbds"), "RBDs · Reliafy");
  assert.equal(titleFor("/risk"), "Condition monitoring · Reliafy");
  assert.equal(titleFor("/systems/runs"), "Simulation runs · System models · Reliafy");
});

test("detail pages lead with the record's name", () => {
  assert.equal(titleFor("/systems/b/abc", "Feed pump train"), "Feed pump train · RBDs · Reliafy");
  assert.equal(titleFor("/models/m/x", "Bearing life"), "Bearing life · Non-repairable · Models · Reliafy");
  assert.equal(titleFor("/models/m/x"), "Non-repairable · Models · Reliafy");
  assert.equal(titleFor("/asset-register/items/i1", "Pump 3"), "Pump 3 · Items · Reliafy");
  assert.equal(titleFor("/asset-register/positions/p1", "Pump 3"), "Pump 3 · Explorer · Assets · Reliafy");
  assert.equal(titleFor("/products/p1", "Pump skid"), "Pump skid · Products · Reliafy");
  assert.equal(titleFor("/items"), "Items · Reliafy");
  assert.equal(titleFor("/data/d1", "Bearings"), "Bearings · Data · Reliafy");
  assert.equal(titleFor("/strategy/analyses/a1", "Pump PM"), "Pump PM · Strategy · Reliafy");
});

test("pages outside the menu are named", () => {
  assert.equal(titleFor("/systems/runs/compare"), "Compare runs · Simulation runs · System models · Reliafy");
  assert.equal(titleFor("/systems/runs/r1"), "Run · Simulation runs · System models · Reliafy");
  assert.equal(titleFor("/systems/b"), "New diagram · RBDs · Reliafy");
  assert.equal(titleFor("/strategy/test-planning/life"), "Life test · Test planning · Strategy · Reliafy");
  assert.equal(titleFor("/settings"), "Settings · Reliafy");
  assert.equal(titleFor("/requirements"), "Requirements · Reliafy");
  assert.equal(titleFor("/asset-register/fleets"), "Fleets · Assets · Reliafy");
  assert.equal(titleFor("/data-model"), "Data model · Reliafy");
  assert.equal(titleFor("/api-docs"), "API docs · Reliafy");
  assert.equal(titleFor("/api-docs/cli"), "Command line · API docs · Reliafy");
  assert.equal(titleFor("/models/new"), "New model · Non-repairable · Models · Reliafy");
  assert.equal(titleFor("/models/alt/new"), "New model · Accelerated life · Models · Reliafy");
  assert.equal(titleFor("/models/degradation/new"), "New model · Degradation · Models · Reliafy");
  assert.deepEqual(titleParts("/nowhere"), []);
});

test("every menu page gets a distinct title", () => {
  const paths = new Set();
  for (const e of MENU_ENTRIES) {
    paths.add(e.to);
    for (const c of e.children || []) paths.add(c.to);
  }
  const titles = [...paths].map((p) => titleFor(p));
  assert.equal(new Set(titles).size, paths.size, titles.join("\n"));
});
