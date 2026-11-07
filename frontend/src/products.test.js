import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildProblem, designActions, hoursText, isDesignScope, itemFilters, itemTreePath, productFmeaPath, productPath,
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

test("the product page's tabs: Functional structure unless the address names another", () => {
  assert.equal(productTab(null), "structure");
  assert.equal(productTab("items"), "items");
  assert.equal(productTab("rcm"), "structure");
  assert.equal(productPath("p 1"), "/products/p%201");
  assert.equal(productPath("p1", "reports"), "/products/p1?tab=reports");
  assert.equal(productPath("p1", "structure"), "/products/p1");
  assert.equal(productFmeaPath("p 1"), "/products/p%201?view=fmea&sel=p%201");
});

test("designs and built trees are left out of the whole Explorer, and shown alone when scoped", () => {
  assert.deepEqual([...productTreeIds(positions)].sort(), ["b", "b1", "d", "d1", "d2"]);
  assert.deepEqual(scopeTree(data).positions.map((p) => p.id), ["plant", "pump"]);
  assert.deepEqual(scopeTree(data, "d").positions.map((p) => p.id), ["d", "d1", "d2"]);
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
