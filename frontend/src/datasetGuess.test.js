// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  censorInverted, guessSplit, guessCompareColumns, dtypeLabel, nameSaysDistribution, parsePreview, fileStem,
} from "./datasetGuess.js";

const PUMP = [
  { name: "unit", dtype: "str" },
  { name: "hours", dtype: "int64" },
  { name: "failed", dtype: "int64" },
  { name: "site", dtype: "str" },
];
const PUMP_DISTINCT = { unit: 10, hours: 10, failed: 2, site: 2 };

test("a 'failed'-style censor column is 1 = failed, so it is inverted", () => {
  for (const n of ["failed", "Failed", "failure", "event", "status", "is_failed", "fail_flag", "dead"]) {
    assert.equal(censorInverted(n), true, n);
  }
  for (const n of ["censored", "c", "censor", "suspended", "running", "hours", ""]) {
    assert.equal(censorInverted(n), false, n);
  }
});

test("compare picks the failed column and ticks invert", () => {
  const g = guessCompareColumns(PUMP, { distinct: PUMP_DISTINCT });
  assert.equal(g.time, "hours");
  assert.equal(g.censor, "failed");
  assert.equal(g.invert, true);
  assert.equal(g.unit, "hours");
});

test("a 'censored' column is not inverted", () => {
  const cols = [{ name: "months", dtype: "int64" }, { name: "censored", dtype: "int64" }];
  const g = guessCompareColumns(cols, { distinct: { months: 20, censored: 2 } });
  assert.equal(g.censor, "censored");
  assert.equal(g.invert, false);
});

test("split by the text column with the fewest values, not one per unit", () => {
  assert.equal(guessCompareColumns(PUMP, { distinct: PUMP_DISTINCT }).group, "site");
  const cols = [...PUMP, { name: "supplier", dtype: "str" }];
  assert.equal(guessSplit(cols, { distinct: { ...PUMP_DISTINCT, supplier: 3 }, exclude: ["hours", "failed"] }), "site");
  // More than 8 values is no grouping; fall back to the first text column.
  assert.equal(guessSplit(PUMP, { distinct: { unit: 10, site: 12 }, exclude: ["hours", "failed"] }), "unit");
});

test("an explicit split wins", () => {
  assert.equal(guessCompareColumns(PUMP, { distinct: PUMP_DISTINCT, splitBy: "unit" }).group, "unit");
  // A column that isn't there is ignored.
  assert.equal(guessSplit(PUMP, { distinct: PUMP_DISTINCT, splitBy: "nope" }), "site");
});

test("with no text column, a numeric column with a few values", () => {
  const seal = [
    { name: "hours", dtype: "int64" },
    { name: "censored", dtype: "int64" },
    { name: "temp_C", dtype: "int64" },
    { name: "load", dtype: "float64" },
  ];
  const g = guessCompareColumns(seal, { distinct: { hours: 30, censored: 2, temp_C: 3, load: 2 } });
  assert.equal(g.group, "load");
});

test("dtypes in plain words", () => {
  assert.equal(dtypeLabel("int64"), "integer");
  assert.equal(dtypeLabel("float64"), "number");
  assert.equal(dtypeLabel("object"), "text");
  assert.equal(dtypeLabel("str"), "text");
  assert.equal(dtypeLabel("bool"), "yes/no");
  assert.equal(dtypeLabel("datetime64[ns]"), "date");
});

test("a distribution chip only when the name doesn't say it", () => {
  assert.equal(nameSaysDistribution("Bearing life — Weibull", "Weibull"), true);
  assert.equal(nameSaysDistribution("Bearing life — Lognormal", "Lognormal (μ, σ)"), true);
  assert.equal(nameSaysDistribution("Pump fit", "Weibull"), false);
  assert.equal(nameSaysDistribution("Seal PH", "Weibull PH"), false);
  assert.equal(nameSaysDistribution("x", ""), false);
});

test("an uploaded file's default name drops its extension", () => {
  assert.equal(fileStem("pump_test.csv"), "pump_test");
  assert.equal(fileStem("Fleet.XLSX"), "Fleet");
  assert.equal(fileStem("notes.v2"), "notes.v2");
  assert.equal(fileStem(""), "");
});

test("the preview reads a header, or names the columns when there is none", () => {
  const p = parsePreview("hours\tfailed\n1240\t1\n980\t0\n");
  assert.deepEqual(p.columns, ["hours", "failed"]);
  assert.equal(p.nRows, 2);
  const n = parsePreview("1240,1\n980,0", { noHeader: true });
  assert.deepEqual(n.columns, ["col 1", "col 2"]);
  assert.equal(n.nRows, 2);
  assert.deepEqual(n.preview[0], ["1240", "1"]);
  assert.equal(parsePreview("hours"), null);
});
