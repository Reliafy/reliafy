import { test } from "node:test";
import assert from "node:assert/strict";
import { deletedBanner, itemDeleteButton, itemDeleteLines } from "./itemDelete.js";

test("what goes with an item, in plain words", () => {
  assert.deepEqual(itemDeleteLines({ tree: null, tasks: 0 }), []);
  assert.deepEqual(itemDeleteLines({ tree: null, tasks: 1 }), ["1 task of its own, retired with it."]);
  assert.deepEqual(itemDeleteLines({ tree: { name: "UAV · Q-7", positions: 12, tasks: 3, open_work_orders: 1 }, tasks: 0 }),
                   ["Its tree, UAV · Q-7, with the 12 positions and 3 tasks in it.", "1 open work order on the tree, cancelled."]);
  assert.deepEqual(itemDeleteLines({ tree: { name: "T", positions: 0, tasks: 0, open_work_orders: 0 } }), ["Its tree, T."]);
  assert.equal(itemDeleteButton({ tree: { name: "T" } }), "Delete the item and its tree");
  assert.equal(itemDeleteButton({ tree: null }), "Delete the item");
});

test("the deleted item's banner", () => {
  assert.equal(deletedBanner({ retired: false }), "");
  assert.equal(deletedBanner({ name: "Motor", retired: true, retired_on: "2026-11-20" }, () => "20 Nov 2026"),
               "Motor was deleted on 20 Nov 2026. It isn't in your lists and can't be fitted; its history is kept.");
});
