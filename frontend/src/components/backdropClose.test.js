// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { shouldCloseOnBackdrop } from "./backdropClose.js";

const overlay = {};
const dialog = {};

test("a press and a release both on the backdrop close it", () => {
  assert.equal(shouldCloseOnBackdrop({ downOnBackdrop: true, target: overlay, currentTarget: overlay, detail: 1 }), true);
});

// The reported bug: select text in a field, release the mouse out on the
// backdrop. The click lands on the backdrop (the nearest common ancestor) but
// the press began inside the dialog.
test("a press that began inside the dialog and ended on the backdrop doesn't close it", () => {
  assert.equal(shouldCloseOnBackdrop({ downOnBackdrop: false, target: overlay, currentTarget: overlay, detail: 1 }), false);
});

test("a click inside the dialog never closes it", () => {
  assert.equal(shouldCloseOnBackdrop({ downOnBackdrop: true, target: dialog, currentTarget: overlay, detail: 1 }), false);
});

test("the second click of a double-click doesn't close it", () => {
  assert.equal(shouldCloseOnBackdrop({ downOnBackdrop: true, target: overlay, currentTarget: overlay, detail: 2 }), false);
});
