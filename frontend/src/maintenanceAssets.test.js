import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NOT_PLACED_PATH, assetPath, assetsSummary, dueText, insideText, openWorkPath, placePath,
} from "./maintenanceAssets.js";

test("a place's page, its open work and the positions at no place", () => {
  assert.equal(placePath("l1"), "/asset-register/locations/l1");
  assert.equal(assetPath("l1"), "/asset-register/explorer?arrange=locations&sel=l1");
  assert.equal(openWorkPath("l 1"), "/maintenance?location=l%201");
  assert.equal(NOT_PLACED_PATH, "/asset-register/explorer?arrange=positions&place=none");
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

test("the list's summary line", () => {
  assert.equal(assetsSummary(null), "");
  assert.equal(assetsSummary({ places: [{ positions: 24 }], not_placed: { positions: 13 } }),
    "1 asset · 37 positions · 13 not at a place yet");
  assert.equal(assetsSummary({ places: [{ positions: 2 }, { positions: 1 }], not_placed: { positions: 0 } }),
    "2 assets · 3 positions");
});
