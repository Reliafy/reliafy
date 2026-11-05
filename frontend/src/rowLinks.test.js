import { test } from "node:test";
import assert from "node:assert/strict";
import { rowOpen } from "./rowLinks.js";

test("a row click navigates; ctrl/cmd or middle click opens a new tab", () => {
  const went = [];
  const opened = [];
  globalThis.window = { open: (...a) => opened.push(a), getSelection: () => "" };
  const click = rowOpen((to) => went.push(to), "/systems/b/x");
  click({});
  assert.deepEqual(went, ["/systems/b/x"]);
  click({ metaKey: true });
  click({ ctrlKey: true });
  click({ button: 1 });
  assert.equal(went.length, 1);
  assert.equal(opened.length, 3);
  assert.equal(opened[0][0], "/systems/b/x");
  assert.equal(opened[0][1], "_blank");
});

test("a row click while selecting text doesn't open it", () => {
  const went = [];
  globalThis.window = { open: () => {}, getSelection: () => "Bearing life" };
  rowOpen((to) => went.push(to), "/models/m/1")({});
  assert.deepEqual(went, []);
  delete globalThis.window;
});
