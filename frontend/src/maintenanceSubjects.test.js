// Run with: node --test src/
// What a task or work order is on: a position, an item or a location.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  actionKinds, itemAtText, subjectApiPath, subjectBadge, subjectPath, taskUnits, whileStoredText,
} from "./maintenanceSubjects.js";

test("each subject has its own page and API path", () => {
  assert.equal(subjectPath({ kind: "item", id: "i1" }), "/asset-register/items/i1");
  assert.equal(subjectPath({ kind: "location", id: "l1" }), "/asset-register/locations/l1");
  assert.equal(subjectPath({ kind: "position", id: "p1" }), "/asset-register/positions/p1");
  assert.equal(subjectPath(null), null);
  assert.equal(subjectApiPath({ kind: "item", id: "i1" }, "tasks"), "/api/maintenance/items/i1/tasks");
  assert.equal(subjectApiPath({ kind: "location", id: "l1" }, "tasks"), "/api/maintenance/locations/l1/tasks");
});

test("a location's task goes by the calendar only", () => {
  assert.deepEqual(taskUnits("location"), ["days", "weeks", "months", "years"]);
  assert.ok(taskUnits("item").includes("hours") && taskUnits("position").includes("cycles"));
});

test("only what isn't a position is marked", () => {
  assert.equal(subjectBadge({ kind: "position" }), "");
  assert.equal(subjectBadge({ kind: "item" }), "item");
  assert.equal(subjectBadge(null), "");
});

test("an item's work says where the item is now", () => {
  assert.equal(itemAtText({ how: "fitted", position: { name: "Truck B" }, location: { display: "Site › Yard" } }),
    "fitted to Truck B (Site › Yard)");
  assert.equal(itemAtText({ how: "fitted", position: { name: "Truck B" }, location: null }), "fitted to Truck B");
  assert.equal(itemAtText({ how: "placed", position: null, location: { name: "Store", display: "Store" } }), "in Store");
  assert.equal(itemAtText({ how: "last_at", position: null, location: { name: "Area 1" } }), "last at Area 1");
  assert.equal(itemAtText(null), "");
});

test("an item's task says what happens in store", () => {
  assert.equal(whileStoredText({ subject: { kind: "item" }, unit: "months", while_stored: "pause" }), "pauses while in store");
  assert.equal(whileStoredText({ subject: { kind: "item" }, unit: "months", while_stored: "run" }), "keeps running in store");
  assert.equal(whileStoredText({ subject: { kind: "position" } }), "");
  // By use only, a store makes no difference.
  assert.equal(whileStoredText({ subject: { kind: "item" }, unit: "hours", while_stored: "run" }), "");
  assert.equal(whileStoredText({ subject: { kind: "item" }, unit: "hours", also_interval: 2, also_unit: "years",
    while_stored: "pause" }), "pauses while in store");
});

test("a replacement is offered only where it can be recorded", () => {
  const kinds = [{ id: "replace" }, { id: "repair" }];
  assert.deepEqual(actionKinds(kinds, { can_replace: false }), [{ id: "repair" }]);
  assert.deepEqual(actionKinds(kinds, { can_replace: true }), kinds);
  assert.deepEqual(actionKinds(kinds, {}), kinds);
});
