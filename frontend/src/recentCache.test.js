import { test } from "node:test";
import assert from "node:assert/strict";
import { createRecent } from "./recentCache.js";

test("keeps what was set, up to its size, dropping the oldest first", () => {
  const c = createRecent(2);
  c.set("a", 1);
  c.set("b", 2);
  assert.equal(c.get("a"), 1);
  c.set("c", 3); // "b" is now the oldest used
  assert.equal(c.has("b"), false);
  assert.equal(c.get("a"), 1);
  assert.equal(c.get("c"), 3);
  assert.equal(c.size, 2);
});

test("setting a key again replaces it and counts as using it", () => {
  const c = createRecent(2);
  c.set("a", 1);
  c.set("b", 2);
  c.set("a", 10);
  c.set("c", 3);
  assert.equal(c.get("a"), 10);
  assert.equal(c.has("b"), false);
});

test("a key never set is undefined; clear empties it", () => {
  const c = createRecent(3);
  assert.equal(c.get("x"), undefined);
  c.set("x", 0);
  assert.equal(c.get("x"), 0); // a falsy value is still kept
  c.clear();
  assert.equal(c.size, 0);
  assert.equal(c.has("x"), false);
});
