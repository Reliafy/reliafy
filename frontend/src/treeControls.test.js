import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_LEVEL, changedFromUsual, levelShown, menuMove, showingOnly } from "./treeControls.js";

test("the level shown: the usual one until one's chosen; null after rows are opened one by one", () => {
  assert.equal(levelShown({}, "positions"), DEFAULT_LEVEL);
  assert.equal(levelShown({ positions: 4 }, "positions"), 4);
  assert.equal(levelShown({ positions: 4 }, "locations"), DEFAULT_LEVEL);
  assert.equal(levelShown({ positions: null }, "positions"), null);
  assert.equal(levelShown({ positions: 0 }, "positions"), 0);
});

test("what's changed from the usual view", () => {
  assert.deepEqual(changedFromUsual({ mode: "positions", level: 2, chips: [] }), []);
  // A level picked by hand (null) isn't one the menu can name: not counted.
  assert.deepEqual(changedFromUsual({ mode: "positions", level: null }), []);
  assert.deepEqual(changedFromUsual({ mode: "positions", level: Infinity }).map((c) => c.id), ["level"]);
  assert.deepEqual(changedFromUsual({ mode: "positions", level: 0 }).map((c) => c.id), ["level"]);
  assert.deepEqual(changedFromUsual({
    mode: "locations", level: 1, chips: [{ id: "overdue", label: "Overdue" }, { id: "alarm", label: "Alarm" }],
  }).map((c) => c.id), ["arrange", "level", "chip:overdue", "chip:alarm"]);
  // A pinned branch isn't the usual view: it counts, first.
  assert.deepEqual(changedFromUsual({ mode: "positions", level: 2, pinned: true }).map((c) => c.id), ["pin"]);
  assert.deepEqual(changedFromUsual({ mode: "locations", level: 3, pinned: true }).map((c) => c.id), ["pin", "arrange", "level"]);
  // Not offered, not counted: the RCM tab has no Arrange by; Flat has no levels.
  assert.deepEqual(changedFromUsual({ mode: "locations", arrange: false, level: 3, levels: false }), []);
});

test("the words beside the count line", () => {
  assert.equal(showingOnly([]), "");
  assert.equal(showingOnly(["Overdue"]), "Showing only Overdue");
  assert.equal(showingOnly(["Overdue", "Alarm"]), "Showing only Overdue and Alarm");
  assert.equal(showingOnly(["Overdue", "Open work", "Alarm"]), "Showing only Overdue, Open work and Alarm");
});

test("the arrow keys in the menu: rows of radios, and items alone", () => {
  const rows = [["pos", "loc", "items", "flat"], ["l1", "l2", "l3", "l4", "all"], ["close"], ["overdue"], ["alarm"], ["done"]];
  const checked = (id) => id === "loc" || id === "l2";
  assert.equal(menuMove(rows, "pos", "ArrowRight", checked), "loc");
  assert.equal(menuMove(rows, "flat", "ArrowRight", checked), "pos"); // round the row
  assert.equal(menuMove(rows, "pos", "ArrowLeft", checked), "flat");
  assert.equal(menuMove(rows, "pos", "ArrowDown", checked), "l2"); // the row's checked one
  assert.equal(menuMove(rows, "l4", "ArrowUp", checked), "loc");
  assert.equal(menuMove(rows, "close", "ArrowDown", checked), "overdue");
  assert.equal(menuMove(rows, "done", "ArrowDown", checked), "loc"); // round the menu
  assert.equal(menuMove(rows, "pos", "ArrowUp", checked), "done");
  assert.equal(menuMove(rows, "close", "ArrowRight", checked), "close"); // alone in its row
  assert.equal(menuMove(rows, "l3", "Home", checked), "pos");
  assert.equal(menuMove(rows, "l3", "End", checked), "done");
  assert.equal(menuMove(rows, null, "ArrowDown", checked), "loc");
  assert.equal(menuMove(rows, "l3", "Enter", checked), null);
  assert.equal(menuMove([], "x", "ArrowDown"), null);
  // No row checked: its first.
  assert.equal(menuMove(rows, "pos", "ArrowDown"), "l1");
});
