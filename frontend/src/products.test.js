import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildProblem, designActions, hoursText, isDesignScope, itemFilters, itemTreePath, productViewPath, productPath,
  productRbds, productTab, productTreeIds, scopeTree, statusText,
} from "./products.js";

// A plant, a product's design (d…) and an item's tree built from it (b…).
const positions = [
  { id: "plant", name: "Plant" }, { id: "pump", name: "Pump", parent_id: "plant" },
  { id: "d", name: "Quad", design: { rev: "C" } }, { id: "d1", name: "Propulsion", parent_id: "d" },
  { id: "d2", name: "Motor 1", parent_id: "d1" },
  { id: "b", name: "Quad · 0007", design_position_id: "d", built_from: { product_id: "d" } },
  { id: "b1", name: "Propulsion", parent_id: "b", design_position_id: "d1" },
];
const data = { positions, locations: [] };

test("the product page is the Explorer on its design: the earlier page tabs land on the tree's Parts tab or the Summary", () => {
  assert.equal(productTab(null), null);
  assert.equal(productTab("parts"), "parts");
  assert.equal(productTab("items"), null);
  assert.equal(productTab("rcm"), null);
  assert.equal(productPath("p 1"), "/products/p%201");
  assert.equal(productPath("p1", "parts"), "/products/p1?view=parts");
  assert.equal(productPath("p1", "reports"), "/products/p1");
  assert.equal(productPath("p1", "structure"), "/products/p1");
  assert.equal(productViewPath("p 1"), "/products/p%201?view=fmea&sel=p%201");
  assert.equal(productViewPath("p 1", "rcm"), "/products/p%201?view=rcm&sel=p%201");
});

test("designs and built trees are left out of the whole Explorer, and shown alone when scoped", () => {
  assert.deepEqual([...productTreeIds(positions)].sort(), ["b", "b1", "d", "d1", "d2"]);
  assert.deepEqual(scopeTree(data).positions.map((p) => p.id), ["plant", "pump"]);
  assert.deepEqual(scopeTree(data, "d").positions.map((p) => p.id), ["d", "d1", "d2"]);
  // A design's positions are marked as a design's (the top already is); a built tree's aren't.
  assert.deepEqual(scopeTree(data, "d").positions.map((p) => !!(p.design || p.in_design)), [true, true, true]);
  assert.ok(!scopeTree(data, "b").positions.some((p) => p.in_design));
  assert.ok(!scopeTree(data).positions.some((p) => p.in_design));
  assert.deepEqual(scopeTree(data, "b").positions.map((p) => p.id), ["b", "b1"]);
  assert.deepEqual(scopeTree(data, "gone").positions, []);
  const plain = { positions: positions.slice(0, 2) };
  assert.equal(scopeTree(plain), plain); // nothing to leave out: the same read
  assert.equal(scopeTree(null), null);
});

test("on a design no failure report is filed", () => {
  assert.equal(isDesignScope(scopeTree(data, "d"), "d"), true);
  assert.equal(isDesignScope(scopeTree(data, "b"), "b"), false);
  assert.equal(isDesignScope(data, null), false);
  const actions = [{ id: "tree-new" }, { id: "report-new" }, { id: "tree-rename" }];
  assert.deepEqual(designActions(actions, true).map((a) => a.id), ["tree-new", "tree-rename"]);
  assert.equal(designActions(actions, false), actions);
});

test("the product's own row offers Build an item…, first; the rows inside don't", () => {
  const actions = [{ id: "tree-new" }, { id: "report-new" }, { id: "tree-rename" }];
  const product = { type: "pos", key: "d", ref: { design: true } };
  const inside = { type: "pos", key: "d1", ref: { in_design: true } };
  assert.deepEqual(designActions(actions, true, { row: product }).map((a) => a.id), ["build-item", "tree-new", "tree-rename"]);
  assert.equal(designActions(actions, true, { row: product })[0].label, "Build an item…");
  assert.deepEqual(designActions(actions, true, { row: inside }).map((a) => a.id), ["tree-new", "tree-rename"]);
  // View only: there, greyed with the reason.
  const greyed = designActions(actions, true, { row: product, viewOnly: "View only." })[0];
  assert.deepEqual([greyed.id, greyed.disabled, greyed.reason], ["build-item", true, "View only."]);
  // Not a design (an item's tree): never.
  assert.equal(designActions(actions, false, { row: product }), actions);
});

test("an item's tree is the Explorer scoped to it", () => {
  assert.equal(itemTreePath("t1"), "/asset-register/explorer?arrange=positions&root=t1");
  assert.equal(itemTreePath("t1", "b5"), "/asset-register/explorer?arrange=positions&root=t1&sel=b5");
});

test("words: hours with their unit, statuses, a serial needed", () => {
  assert.equal(hoursText({ value: 212, unit: "hours" }), "212 hours");
  assert.equal(hoursText({ value: 1234.56, unit: "h" }), "1,234.6 h");
  assert.equal(hoursText(null), "—");
  assert.equal(statusText("spare"), "Spare (placed)");
  assert.equal(statusText("not placed"), "Not placed");
  assert.equal(buildProblem("  "), "Give the item's serial number.");
  assert.equal(buildProblem("0010"), null);
});

test("the Items filters list products and types by name", () => {
  const f = itemFilters([{ id: "2", name: "Rover" }, { id: "1", name: "Quad" }], [{ id: "c", name: "UAV" }]);
  assert.deepEqual(f.products, [{ value: "1", label: "Quad" }, { value: "2", label: "Rover" }]);
  assert.deepEqual(f.types, [{ value: "c", label: "UAV" }]);
});

test("a product's RBDs: made from its structure, or named after it", () => {
  const rbds = [
    { id: "1", name: "Quad (from Maintenance)" }, { id: "2", name: "Quad: flight-critical RBD" },
    { id: "3", name: "Quadruple pumps" }, { id: "4", name: "Quad" }, { id: "5", name: "Pump train" },
  ];
  assert.deepEqual(productRbds({ name: "Quad" }, rbds).map((r) => r.id), ["1", "2", "4"]);
  assert.deepEqual(productRbds(null, rbds), []);
});

test("a product's layout (design locations) and a built item's copies stay off the whole Explorer and show on their own tree", () => {
  const locations = [
    { id: "site", name: "Site", parent_id: null },
    { id: "arm", name: "Forward left arm", parent_id: null, design_of: "d" },
    { id: "bay", name: "Battery bay", parent_id: "arm", design_of: "d" },
    { id: "barm", name: "Forward left arm", parent_id: null, carried_by: "b" },
  ];
  const all = { positions, locations };
  assert.deepEqual(scopeTree(all).locations.map((l) => l.id), ["site"]);
  const design = scopeTree(all, "d");
  assert.deepEqual(design.locations.map((l) => l.id), ["arm", "bay"]);
  assert.ok(design.locations.every((l) => l.in_design));
  assert.deepEqual(design.scope, { kind: "design", id: "d", name: "Quad" });
  const built = scopeTree(all, "b");
  assert.deepEqual(built.locations.map((l) => l.id), ["barm"]);
  assert.ok(!built.locations.some((l) => l.in_design));
  assert.equal(built.scope.kind, "unit");
  assert.deepEqual(scopeTree(all, "gone").locations, []);
  assert.equal(scopeTree(all).scope, undefined);
});
