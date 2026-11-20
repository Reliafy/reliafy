import test from "node:test";
import assert from "node:assert/strict";
import { bestMatchIndex, filterOptions, matchRank, matchesQuery } from "./selectSearch.js";

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

test("the closest name comes first and is what Enter takes", () => {
  const rows = [
    { value: "b", label: "Supplier B", hint: "Normal · hours" }, // the "a" is in "Normal"
    { value: "x", label: "Pumps from Supplier A", hint: "Weibull · hours" },
    { value: "a", label: "Supplier A", hint: "Lognormal · hours" },
    { value: "a2", label: "Supplier A bearings", hint: "Weibull · hours" },
  ];
  const out = filterOptions(rows, "supplier a");
  assert.deepEqual(out.map((o) => o.value), ["a", "a2", "x", "b"]);
  assert.equal(out[bestMatchIndex(out, "supplier a")].value, "a");
  assert.equal(matchRank(rows[2], "  SUPPLIER   a "), 0);
  assert.equal(matchRank(rows[3], "supplier a"), 1);
  assert.equal(matchRank(rows[1], "supplier a"), 2);
  assert.equal(matchRank(rows[0], "supplier a"), 3);
});

test("ranking stays within a group, and Enter looks across groups", () => {
  const rows = [
    { heading: "Non-repairable models", _header: true },
    { value: "b", label: "Supplier B pumps" },
    { heading: "Repairable models", _header: true },
    { value: "a", label: "Supplier" },
  ];
  const out = filterOptions(rows, "supplier");
  assert.deepEqual(out.map((o) => o.value ?? o.heading), ["Non-repairable models", "b", "Repairable models", "a"]);
  assert.equal(out[bestMatchIndex(out, "supplier")].value, "a");
  assert.equal(bestMatchIndex([], "x"), -1);
});
