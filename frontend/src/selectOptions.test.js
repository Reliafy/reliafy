import test from "node:test";
import assert from "node:assert/strict";
import { createElement as h, Fragment } from "react";
import { longList, nativeSelected, optionsFromChildren, textOf } from "./selectOptions.js";

test("<option> children become rows with string values, like a native list", () => {
  const rows = optionsFromChildren([
    h("option", { key: 1, value: "" }, "— choose —"),
    h("option", { key: 2, value: 3 }, "Three ", "units"),
    false,
    null,
    h("option", { key: 3 }, "No value"),
    h("option", { key: 4, value: "x", disabled: true }, "Off"),
  ]);
  assert.deepEqual(rows, [
    { value: "", label: "— choose —" },
    { value: "3", label: "Three units" },
    { value: "No value", label: "No value" },
    { value: "x", label: "Off", disabled: true },
  ]);
});

test("an optgroup is a heading over its options; fragments and maps are walked", () => {
  const rows = optionsFromChildren([
    h(Fragment, { key: "f" }, ["a", "b"].map((v) => h("option", { key: v, value: v }, v.toUpperCase()))),
    h("optgroup", { key: "g", label: "Later", disabled: true }, h("option", { value: "c" }, "C")),
  ]);
  assert.deepEqual(rows, [
    { value: "a", label: "A" },
    { value: "b", label: "B" },
    { heading: "Later" },
    { value: "c", label: "C", disabled: true },
  ]);
});

test("the shown row: the match by string, else the first that isn't disabled", () => {
  const rows = [{ heading: "H" }, { value: "a", label: "A", disabled: true }, { value: "1", label: "One" }, { value: "2", label: "Two" }];
  assert.equal(nativeSelected(rows, 2).label, "Two");
  assert.equal(nativeSelected(rows, "a").label, "A");
  assert.equal(nativeSelected(rows, "nope").label, "One");
  assert.equal(nativeSelected(rows, undefined).label, "One");
  assert.equal(nativeSelected([], "x"), null);
});

test("text of nested labels, and long lists get the search box", () => {
  assert.equal(textOf(["P-", 101, h("b", null, " pump")]), "P-101 pump");
  assert.equal(longList(Array.from({ length: 15 }, (_, i) => ({ value: String(i) }))), false);
  assert.equal(longList(Array.from({ length: 16 }, (_, i) => ({ value: String(i) }))), true);
});
