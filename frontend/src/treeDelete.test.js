import test from "node:test";
import assert from "node:assert/strict";
import {
  DELETE_KIND, deleteButton, deleteLines, deleteTitle, deletedText, isDeleteKey, isUndoKey, undoneText,
} from "./treeDelete.js";

const propulsion = {
  kind: "position", name: "Propulsion", positions: 13, positions_inside: 12, locations: 0, locations_inside: 0,
  items_unfitted: 4, positions_on_unfitted_items: 0, items_placed: 0, stock_lines: 0, tasks: 9, work_packages: 0,
  open_work_orders: 3, functions: 2, failure_modes: 5,
};

test("a position's dialog counts what goes, in plain words", () => {
  assert.equal(deleteTitle(propulsion), "Delete “Propulsion” and everything inside it?");
  assert.deepEqual(deleteLines(propulsion), [
    "12 positions inside it",
    "4 fitted items kept, unfitted: they stay in Items",
    "9 scheduled tasks: no longer scheduled",
    "3 open work orders: cancelled",
    "2 functions and 5 failure modes (its RCM)",
  ]);
  assert.equal(deleteButton(propulsion), "Delete 13 positions");
  assert.equal(deletedText(propulsion), "Deleted Propulsion and 12 positions inside it.");
});

test("a leaf says just itself", () => {
  const leaf = { kind: "position", name: "Bearing", positions: 1, positions_inside: 0 };
  assert.equal(deleteTitle(leaf), "Delete “Bearing”?");
  assert.deepEqual(deleteLines(leaf), []);
  assert.equal(deleteButton(leaf), "Delete the position");
  assert.equal(deletedText(leaf), "Deleted Bearing.");
});

test("a location counts the places inside and the positions there", () => {
  const site = { kind: "location", name: "Site", locations: 3, locations_inside: 2, positions: 4, items_placed: 1,
    stock_lines: 2, items_unfitted: 1, positions_on_unfitted_items: 2 };
  assert.equal(deleteTitle(site), "Delete “Site” and everything inside it?");
  assert.deepEqual(deleteLines(site), [
    "2 locations inside it",
    "4 positions there, with everything inside them",
    "1 fitted item kept, unfitted: it stays in Items (with the 2 positions on it)",
    "1 item stored there kept, with no place now: it stays in Items",
    "Stock recorded there: kept",
  ]);
  assert.equal(deleteButton(site), "Delete 3 locations and 4 positions");
  assert.equal(deletedText(site), "Deleted Site, 2 locations and 4 positions in it.");
  assert.equal(deleteButton({ kind: "location", locations: 1, positions: 0 }), "Delete the location");
});

test("items are never deleted: there's no item kind", () => {
  assert.deepEqual(Object.values(DELETE_KIND), ["position", "location"]);
});

test("undo says what came back and what didn't", () => {
  assert.equal(undoneText({ name: "Propulsion", skipped: [] }), "Undone: Propulsion and everything inside it are back.");
  assert.match(undoneText({ name: "P", skipped: ["M1 wasn't refitted."] }), /back\. M1 wasn't refitted\.$/);
});

test("Delete and Backspace open it, not while typing or with a modifier", () => {
  const row = { closest: () => null };
  const input = { closest: () => ({}) };
  assert.equal(isDeleteKey({ key: "Delete", target: row }), true);
  assert.equal(isDeleteKey({ key: "Backspace", target: row }), true);
  assert.equal(isDeleteKey({ key: "Backspace", target: input }), false);
  assert.equal(isDeleteKey({ key: "Backspace", metaKey: true, target: row }), false);
  assert.equal(isDeleteKey({ key: "x", target: row }), false);
  assert.equal(isUndoKey({ key: "z", ctrlKey: true, target: row }), true);
  assert.equal(isUndoKey({ key: "Z", metaKey: true, target: row }), true);
  assert.equal(isUndoKey({ key: "z", metaKey: true, shiftKey: true, target: row }), false);
  assert.equal(isUndoKey({ key: "z", ctrlKey: true, target: input }), false);
});
