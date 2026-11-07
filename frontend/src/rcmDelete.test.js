import test from "node:test";
import assert from "node:assert/strict";
import {
  RCM_DELETE_KIND, RCM_DELETE_NOTE, deletesWithCascade, rcmDeleteButton, rcmDeleteCounts, rcmDeleteId, rcmDeleteLines,
  rcmDeleteTitle, rcmDeletedText, rcmUndoneText, withPositionDelete,
} from "./rcmDelete.js";

const pumpWater = {
  kind: "function", name: "Pump water", standards: 0, functional_failures: 2, failure_modes: 5, tasks: 3,
  tasks_kept: 1, links: 1, documents: 0,
};

test("a function's dialog says everything under it goes, counted", () => {
  assert.equal(rcmDeleteTitle(pumpWater), "Delete “Pump water” and everything under it?");
  assert.equal(rcmDeleteCounts(pumpWater), "2 functional failures, 5 failure modes, 3 tasks.");
  assert.deepEqual(rcmDeleteLines(pumpWater), [
    "3 tasks: no longer scheduled",
    "1 task shared with other failure modes: kept for them",
    "1 link to functional failures on other positions: unlinked",
  ]);
  assert.equal(rcmDeleteButton(pumpWater), "Delete the function");
  assert.equal(rcmDeletedText(pumpWater), "Deleted “Pump water” and everything under it.");
  assert.match(RCM_DELETE_NOTE, /undo it/);
});

test("each kind names itself; a standard counts its performance standards too", () => {
  const std = { kind: "standard", name: "At least 40 L/s", standards: 0, functional_failures: 1, failure_modes: 2, tasks: 1 };
  assert.equal(rcmDeleteCounts(std), "1 functional failure, 2 failure modes, 1 task.");
  assert.equal(rcmDeleteButton(std), "Delete the performance standard");
  assert.equal(rcmDeleteCounts({ standards: 2, functional_failures: 1 }), "2 performance standards, 1 functional failure.");
  assert.equal(rcmDeleteButton({ kind: "functional_failure" }), "Delete the functional failure");
  assert.equal(rcmDeleteButton({ kind: "failure_mode" }), "Delete the failure mode");
});

test("a row with nothing under it says just itself", () => {
  const leaf = { kind: "failure_mode", name: "Seal leaks", standards: 0, functional_failures: 0, failure_modes: 0, tasks: 0 };
  assert.equal(rcmDeleteTitle(leaf), "Delete “Seal leaks”?");
  assert.equal(rcmDeleteCounts(leaf), "");
  assert.deepEqual(rcmDeleteLines(leaf), []);
  assert.equal(rcmDeletedText(leaf), "Deleted “Seal leaks”.");
  assert.deepEqual(rcmDeleteLines({ ...leaf, documents: 2 }), ["2 documents on it: taken off"]);
  // A long name is cut, with an ellipsis.
  assert.equal(rcmDeleteTitle({ name: "x".repeat(90) }), `Delete “${"x".repeat(80)}…”?`);
});

test("undo says what came back, and what didn't", () => {
  assert.equal(rcmUndoneText({ name: "Pump water", skipped: [] }), "Undone: “Pump water” and everything under it are back.");
  assert.equal(rcmUndoneText({ name: "Low flow", skipped: ["“Impeller worn” didn't come back."] }),
    "Undone: “Low flow” and everything under it are back. “Impeller worn” didn't come back.");
});

test("which rows delete with everything under them, and by which id", () => {
  assert.deepEqual(RCM_DELETE_KIND, { fn: "function", std: "standard", fail: "functional_failure", mode: "failure_mode" });
  assert.equal(deletesWithCascade({ type: "fn", ref: { id: "f1" } }), true);
  assert.equal(deletesWithCascade({ type: "std", ref: { standard_id: "s1" } }), true);
  assert.equal(deletesWithCascade({ type: "std", ref: { legacy: true } }), false); // the old single text is cleared
  assert.equal(deletesWithCascade({ type: "cause", ref: {} }), false);
  assert.equal(deletesWithCascade(null), false);
  assert.equal(rcmDeleteId({ type: "std", ref: { id: "f1:s1", standard_id: "s1" } }), "s1");
  assert.equal(rcmDeleteId({ type: "mode", ref: { id: "m1" } }), "m1");
});

test("a position's row gains Delete… last", () => {
  assert.deepEqual(withPositionDelete([{ id: "add-fn" }]).map((a) => a.id), ["add-fn", "tree-delete"]);
  assert.equal(withPositionDelete([], { viewOnly: "View only." })[0].disabled, true);
});
