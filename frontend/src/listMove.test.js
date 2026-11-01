import { test } from "node:test";
import assert from "node:assert/strict";
import { moveItem } from "./listMove.js";

test("moveItem moves one item and keeps the rest in order", () => {
  assert.deepEqual(moveItem(["a", "b", "c", "d"], 0, 2), ["b", "c", "a", "d"]);
  assert.deepEqual(moveItem(["a", "b", "c", "d"], 3, 0), ["d", "a", "b", "c"]);
  assert.deepEqual(moveItem(["a", "b"], 1, 0), ["b", "a"]);
});

test("moveItem says null when nothing moves", () => {
  assert.equal(moveItem(["a", "b"], 1, 1), null);
  assert.equal(moveItem(["a", "b"], -1, 0), null);
  assert.equal(moveItem(["a", "b"], 0, 2), null);
});
