import { test } from "node:test";
import assert from "node:assert/strict";
import { canSplit, limitWords, proposeSplit, splitLines, standardsShown, unbreachedWords } from "./rcmStandards.js";
import { COLUMN, rowText } from "./rcmWorksheet.js";
import { EXPORT_HEADER, positionRcmRows } from "./rcmImport.js";

test("a function shows its list, or its one text as the first item", () => {
  assert.deepEqual(standardsShown({ standard: "pH 7.2-7.8", standards: [] }), [{ id: null, text: "pH 7.2-7.8", order: 1, legacy: true, failures: 0 }]);
  assert.deepEqual(standardsShown({ standard: "  ", standards: [] }), []);
  const listed = standardsShown({ standard: "pH 7.2-7.8; TA 80-120", standards: [{ id: "s1", text: "pH 7.2-7.8", failures: 1 }, { id: "s2", text: "TA 80-120", failures: 0 }] });
  assert.deepEqual(listed.map((st) => [st.id, st.legacy]), [["s1", false], ["s2", false]]);
});

test("the split helper is offered for a single text that reads as several, and proposes its lines", () => {
  assert.equal(canSplit({ standard: "pH 7.2-7.8; TA 80-120", standards: [] }), true);
  assert.equal(canSplit({ standard: "pH 7.2-7.8", standards: [] }), false);
  assert.equal(canSplit({ standard: "a; b", standards: [{ id: "s1", text: "a" }] }), false);
  assert.deepEqual(proposeSplit("pH 7.4-7.6 (7.2-7.8 limits); total alkalinity 80-120 ppm;\nLSI -0.3 to +0.3; "),
    ["pH 7.4-7.6 (7.2-7.8 limits)", "total alkalinity 80-120 ppm", "LSI -0.3 to +0.3"]);
  assert.deepEqual(splitLines([{ text: "FC 1-3 ppm" }, { text: "given the pump runs", kind: "when" }, { text: "CC < 0.5 ppm" }, { text: "old", drop: true }, { text: " " }]),
    [{ text: "FC 1-3 ppm", when: "given the pump runs" }, { text: "CC < 0.5 ppm" }]);
  assert.equal(splitLines([{ text: "x", drop: true }]), null);
  assert.deepEqual(splitLines([{ text: "lonely", kind: "when" }]), null); // a condition with nothing before it
});

test("the limit in words, and the hint for standards with no failure", () => {
  assert.equal(limitWords({ parameter: "TA", comparator: "between", value: "80-120", unit: "ppm", when: "in summer", source: "E25 manual" }), "TA between 80-120 ppm · in summer · E25 manual");
  assert.equal(limitWords({ when: "the pool is in use" }), "when the pool is in use");
  assert.equal(limitWords({ when: "while the filter pump runs" }), "while the filter pump runs");
  assert.equal(limitWords({ text: "pH 7.2-7.8" }), "");
  assert.equal(unbreachedWords({ standards: [{ id: "a" }, { id: "b" }], standards_without_failure: 2 }), "2 standards have no functional failure yet.");
  assert.equal(unbreachedWords({ standards: [{ id: "a" }], standards_without_failure: 1 }), "1 standard has no functional failure yet.");
  assert.equal(unbreachedWords({ standards: [], standards_without_failure: 0 }), "");
});

test("the standard cell is edited in place only while the function has its one text; the search reaches the list", () => {
  assert.equal(COLUMN.standard.can({ type: "fn", ref: { standard: "x", standards: [] } }), true);
  assert.equal(COLUMN.standard.can({ type: "fn", ref: { standard: "x; y", standards: [{ id: "s1", text: "x" }, { id: "s2", text: "y" }] } }), false);
  assert.match(rowText({ ref: { text: "Keep", standard: "pH 7.2-7.8; TA", standards: [{ id: "s", text: "TA", parameter: "alkalinity", source: "E25 manual" }] } }), /alkalinity e25 manual/);
});

test("the CSV writes a function's standards as rows, and each failure's breach", () => {
  const rows = positionRcmRows({ positions: [{ id: "p", name: "Pool", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Keep the water balanced", standard: "pH 7.2-7.8; TA 80-120", standard_basis: "## Sums", standards: [{ id: "s1", text: "pH 7.2-7.8" }, { id: "s2", text: "TA 80-120" }], failures: [
      { id: "x1", text: "pH above 7.8", standard: { id: "s1", text: "pH 7.2-7.8" }, modes: [{ id: "m1", text: "Acid under-dosed", decision: null }] },
      { id: "x2", text: "Water unusable", standard: null, modes: [] },
    ] },
    { id: "g", text: "Contain the water", standard: "No leak", standards: [], failures: [{ id: "x3", text: "Leaks", standard: null, modes: [] }] },
  ] }] });
  const col = EXPORT_HEADER.indexOf("Performance standard");
  assert.deepEqual(rows.slice(1).map((r) => [r[1], r[col], r[4], r[6]]), [
    ["Keep the water balanced", "pH 7.2-7.8", "", ""],
    ["Keep the water balanced", "TA 80-120", "", ""],
    ["Keep the water balanced", "pH 7.2-7.8", "pH above 7.8", "Acid under-dosed"],
    ["Keep the water balanced", "", "Water unusable", ""],
    ["Contain the water", "No leak", "Leaks", ""],
  ]);
  assert.equal(rows[1][3], "## Sums"); // the working on the function's first row only
  assert.equal(rows[3][3], "");
});
