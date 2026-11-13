import test from "node:test";
import assert from "node:assert/strict";
import { filterOptions, matchesQuery } from "./selectSearch.js";

const items = [
  { value: "", label: "— choose —" },
  { heading: "Yours", _header: true },
  { value: "a", label: "Impeller removals", hint: "Weibull · hours" },
  { value: "b", label: "Relief valve bench tests", hint: "Exponential · months" },
  { heading: "Samples", _header: true },
  { value: "c", label: "Bearings", hint: "Weibull · hours" },
];

test("every word typed must appear, in any order and case", () => {
  assert.equal(matchesQuery(items[2], "weibull IMPELLER"), true);
  assert.equal(matchesQuery(items[2], "weibull valve"), false);
  assert.equal(matchesQuery(items[2], ""), true);
});

test("nothing typed keeps every row", () => {
  assert.equal(filterOptions(items, "  ").length, items.length);
});

test("a heading stays only above a match; the empty choice drops out", () => {
  assert.deepEqual(filterOptions(items, "valve").map((o) => o.value ?? o.heading), ["Yours", "b"]);
  assert.deepEqual(filterOptions(items, "weibull").map((o) => o.value ?? o.heading), ["Yours", "a", "Samples", "c"]);
  assert.deepEqual(filterOptions(items, "nothing like it"), []);
});
