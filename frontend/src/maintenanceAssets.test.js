import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NOT_PLACED_PATH, assetsSummary, dueText, insideText, openWorkPath, placePath, treeOf, treeSize,
} from "./maintenanceAssets.js";

test("a place's page, its open work and the positions at no place", () => {
  assert.equal(placePath("l1"), "/asset-register/locations/l1");
  assert.equal(openWorkPath("l 1"), "/maintenance?location=l%201");
  assert.equal(NOT_PLACED_PATH, "/asset-register/positions?place=none");
});

test("what's inside and what's due, in words", () => {
  assert.equal(insideText({ locations: 0 }), "");
  assert.equal(insideText({ locations: 1 }), "1 place inside");
  assert.equal(insideText({ locations: 27 }), "27 places inside");
  assert.deepEqual(dueText({ due: 0 }), { text: "Nothing due", overdue: "" });
  assert.deepEqual(dueText({ due: 3, overdue: 1, next_due: "2026-10-01" }, (d) => `on ${d}`),
    { text: "3 due", overdue: "1 overdue" });
  assert.deepEqual(dueText({ due: 1, overdue: 0, next_due: "2026-11-04" }), { text: "1 due, next 2026-11-04", overdue: "" });
});

test("the positions tree cut to those at no place", () => {
  const tree = [
    { id: "car", children: [{ id: "tyres", children: [] }, { id: "towbar", children: [] }] },
    { id: "pool", children: [{ id: "pump", children: [] }] },
    { id: "dishwasher", children: [] },
  ];
  // The towbar has a place of its own (in the garage); the pool and its pump are in the pool area.
  const cut = treeOf(tree, ["car", "tyres", "dishwasher"]);
  assert.deepEqual(cut, [
    { id: "car", children: [{ id: "tyres", children: [] }] },
    { id: "dishwasher", children: [] },
  ]);
  assert.equal(treeSize(cut), 3);
  assert.equal(treeSize(tree), 6);
  assert.deepEqual(treeOf(tree, []), []);
});

test("the list's summary line", () => {
  assert.equal(assetsSummary(null), "");
  assert.equal(assetsSummary({ places: [{ positions: 24 }], not_placed: { positions: 13 } }),
    "1 asset · 37 positions · 13 not at a place yet");
  assert.equal(assetsSummary({ places: [{ positions: 2 }, { positions: 1 }], not_placed: { positions: 0 } }),
    "2 assets · 3 positions");
});
