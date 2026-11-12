// Run with: node --test src/
// What a task or work order is on: a position, an item or a location.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  actionKinds, closeActionKind, defaultCloseKind, defaultFailed, itemAtText, replaceReason, replaceRecordText, subjectApiPath, subjectBadge, subjectPath, taskUnits, whileStoredText,
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

test("a close form starts from what the work order's task is", () => {
  const pos = { can_replace: true, subject: { kind: "position" } };
  // A weekly pH check (on condition) or a failure-finding test: checked, nothing replaced.
  assert.equal(defaultCloseKind({ ...pos, task: { id: "t", outcome: "on_condition" } }), "checked");
  assert.equal(defaultCloseKind({ ...pos, task: { id: "t", outcome: "failure_finding" } }), "checked");
  // A task that asks for a reading (its tool reads a point) is a check too.
  assert.equal(defaultCloseKind({ ...pos, task: { id: "t" }, reading_points: [{ task_id: "t", why: ["tool"] }] }), "checked");
  // A setting where it is doesn't make the task a check.
  assert.equal(defaultCloseKind({ ...pos, task: { id: "t" }, reading_points: [{ task_id: "t", why: ["setting"] }] }), "replace");
  // A fixed-interval replacement: replaced.
  assert.equal(defaultCloseKind({ ...pos, task: { id: "t", outcome: "fixed_interval" } }), "replace");
  // A package of checks only: checked; a replacement among them: replaced.
  assert.equal(defaultCloseKind({ ...pos, tasks: [{ outcome: "on_condition" }, { outcome: "failure_finding" }] }), "checked");
  assert.equal(defaultCloseKind({ ...pos, tasks: [{ outcome: "on_condition" }, { outcome: "fixed_interval" }] }), "replace");
  // No task: as before (a replacement at a position, a repair elsewhere); rounds and inspections inspect.
  assert.equal(defaultCloseKind(pos), "replace");
  assert.equal(defaultCloseKind({ can_replace: false, subject: { kind: "item" } }), "repair");
  assert.equal(defaultCloseKind({ subject: { kind: "location" }, can_replace: false }), "inspect");
  assert.equal(defaultCloseKind({ ...pos, type: "inspection", task: { outcome: "fixed_interval" } }), "inspect");
});

test("checked, nothing done is sent as an inspection that found it OK", () => {
  assert.deepEqual(closeActionKind("checked"), { kind: "inspect", finding: "ok" });
  assert.deepEqual(closeActionKind("replace"), { kind: "replace" });
});

test("a breakdown's replacement starts as a failure; planned work as a planned replacement", () => {
  const fitted = { fitted: { item: { name: "Pump P1" } }, subject: { kind: "position", name: "Pump 3" } };
  // A corrective work order closed with the defaults records a failure (c = 0 in the life data).
  const breakdown = { ...fitted, type: "corrective" };
  assert.equal(defaultFailed(breakdown), true);
  assert.equal(replaceReason({ kind: "replace", failed: defaultFailed(breakdown) }), "failure");
  assert.match(replaceRecordText({ failed: true }, breakdown), /^Records a failure: Pump P1's time at Pump 3 ends as a failure \(mode not known\)/);
  assert.match(replaceRecordText({ failed: true }, breakdown, "Seal leaking"), /\(Seal leaking\)/);
  // Preventive work keeps the planned replacement, and says it's a suspension.
  for (const type of ["preventive", "inspection", "other", undefined]) {
    assert.equal(defaultFailed({ ...fitted, type }), false);
  }
  assert.equal(replaceReason({ failed: false }), "planned");
  assert.match(replaceRecordText({ failed: false }, { ...fitted, type: "preventive" }), /still running \(a suspension\)/);
  assert.match(replaceRecordText({ failed: true }, { type: "corrective" }), /Nothing is fitted here/);
});
