// Run with: node --test src/
// Every dialog holds the keyboard: Tab and Shift+Tab go round its own
// controls, never out to the page behind it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { trapTab } from "./focusTrap.js";

function el(name) {
  return { name, offsetParent: {}, focus() { globalThis.document.activeElement = this; } };
}
function dialog(controls) {
  return {
    querySelectorAll: () => controls,
    contains: (x) => controls.includes(x),
  };
}
function key(shiftKey = false, defaultPrevented = false) {
  return { key: "Tab", shiftKey, defaultPrevented, prevented: false, preventDefault() { this.prevented = true; } };
}

test("Tab on the last control goes round to the first", () => {
  const [a, b, c] = [el("a"), el("b"), el("c")];
  globalThis.document = { activeElement: c };
  const e = key();
  trapTab(e, dialog([a, b, c]));
  assert.equal(e.prevented, true);
  assert.equal(document.activeElement, a);
});

test("Shift+Tab on the first control goes round to the last", () => {
  const [a, b, c] = [el("a"), el("b"), el("c")];
  globalThis.document = { activeElement: a };
  const e = key(true);
  trapTab(e, dialog([a, b, c]));
  assert.equal(document.activeElement, c);
});

test("Tab between controls is left to the browser", () => {
  const [a, b, c] = [el("a"), el("b"), el("c")];
  globalThis.document = { activeElement: a };
  const e = key();
  trapTab(e, dialog([a, b, c]));
  assert.equal(e.prevented, false);
  assert.equal(document.activeElement, a);
});

test("focus outside the dialog is brought back in", () => {
  const [a, b] = [el("a"), el("b")];
  globalThis.document = { activeElement: el("page") };
  trapTab(key(), dialog([a, b]));
  assert.equal(document.activeElement, a);
});

test("a Tab a dropdown already used is left alone", () => {
  const [a, b] = [el("a"), el("b")];
  globalThis.document = { activeElement: b };
  const e = key(false, true);
  trapTab(e, dialog([a, b]));
  assert.equal(document.activeElement, b);
});

test("the shared Modal traps focus for every dialog, with no opt-in", () => {
  const src = readFileSync(fileURLToPath(new URL("./Modal.jsx", import.meta.url)), "utf8");
  assert.doesNotMatch(src, /trapFocus/);
  assert.match(src, /onKeyDown=\{\(e\) => \{ if \(openModals\[openModals\.length - 1\] === token\.current\) trapTab\(e, box\.current\); \}\}/);
  assert.match(src, /useDialogFocus\(box\)/);
});
