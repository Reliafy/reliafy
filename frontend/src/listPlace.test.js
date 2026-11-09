import { test } from "node:test";
import assert from "node:assert/strict";
import { listPlace } from "./listPlace.js";

const view = { width: 1440, height: 900 };

test("under the input, at least 22rem wide", () => {
  const p = listPlace({ left: 300, top: 200, bottom: 232, width: 240 }, view);
  assert.equal(p.top, 236);
  assert.equal(p.bottom, undefined);
  assert.equal(p.left, 300);
  assert.equal(p.width, 352);
  assert.equal(p.maxHeight, 288);
});

test("above it near the foot of the screen", () => {
  const p = listPlace({ left: 300, top: 800, bottom: 832, width: 400 }, view);
  assert.equal(p.top, undefined);
  assert.equal(p.bottom, 104);
  assert.equal(p.width, 400);
  assert.equal(p.maxHeight, 288);
});

test("kept on a phone's screen", () => {
  const p = listPlace({ left: 250, top: 300, bottom: 332, width: 140 }, { width: 400, height: 860 });
  assert.equal(p.width, 352);
  assert.equal(p.left, 40);
  const narrow = listPlace({ left: 10, top: 300, bottom: 332, width: 140 }, { width: 320, height: 860 });
  assert.equal(narrow.width, 304);
  assert.equal(narrow.left, 8);
});
