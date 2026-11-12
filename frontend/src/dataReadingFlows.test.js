// Run with: node --test src/
// Degradation and condition and life fitted from a saved dataset's reading
// (no column step): for the family sheets, the guessed reading gives the same
// fit request as the flow's own column guess did before.
import { test } from "node:test";
import assert from "node:assert/strict";
import { FAMILY_SHEETS as S } from "./dataStepFamilySheets.js";
import { columnFacts } from "./lifeData.js";
import { emptyReading, guessReading } from "./datasetReading.js";
import {
  degradationIssues, degradationMappingFromReading, guessDegradationColumns, guessMeasurementUnit, guessTimeUnit,
} from "./degradation.js";
import {
  guessLifetimeColumns, guessReadingColumns, jointIssues, jointMappingsFromReading, jointRequest,
} from "./joint.js";
import CASES from "./readingGuessCases.json" with { type: "json" };

const guess = (sheet) => guessReading(sheet.columns, columnFacts(sheet), sheet.n_rows);
const described = (sheet) => {
  const facts = columnFacts(sheet);
  return sheet.columns.map((name) => ({ name, ...facts[name] }));
};
// The measurements part's reading as the server guesses it (dataset_reading.for_dataset).
const partReading = (sheet) => {
  const g = guess(sheet);
  return { i: g.i, x: g.x || g.xl, m: g.m, unit: g.unit, m_unit: "", source: "guessed" };
};

test("the guesses here are the ones the server makes (readingGuessCases.json)", () => {
  for (const name of ["w19", "w03life", "w03reads", "w24life", "w24reads"]) {
    assert.deepEqual(guess(S[name]), CASES[name], name);
  }
});

test("degradation: one table's reading gives the same i, x, y and units as the Data step's guess", () => {
  const sheet = S.w19;
  const before = guessDegradationColumns(sheet.columns);
  const d = degradationMappingFromReading(guess(sheet));
  assert.deepEqual(d.mapping, before);
  assert.equal(d.unit, guessTimeUnit(before.x));
  assert.equal(d.measurementUnit, guessMeasurementUnit(before.y));
  assert.deepEqual([d.unit, d.measurementUnit], ["Kilometres", "mm"]);
  assert.equal(d.missing, null);
  assert.deepEqual(degradationIssues(sheet, d.mapping), []);
});

test("degradation: the measurements part's reading is used when the dataset has one; its units win", () => {
  const r = { ...emptyReading(), x: "life", c: "status",
              measurements: { i: "pad", x: "km", m: "thickness_mm", unit: "Miles", m_unit: "in" } };
  const d = degradationMappingFromReading(r);
  assert.deepEqual(d.mapping, { i: "pad", x: "km", y: "thickness_mm" });
  assert.deepEqual([d.unit, d.measurementUnit], ["Miles", "in"]);
  assert.equal(d.missing, null);
});

test("degradation: what the reading lacks is said plainly", () => {
  const none = degradationMappingFromReading({ ...emptyReading(), x: "hours", c: "status" });
  assert.match(none.missing, /needs i \(which item each reading belongs to\) and m \(the measured value\)/);
  assert.match(none.missing, /change the reading to pick them/);
  const part = degradationMappingFromReading({ ...emptyReading(), measurements: { i: "pad", x: "", m: "wear" } });
  assert.match(part.missing, /needs x \(when each reading was taken\)\. The dataset's measurements are read without it/);
});

// What the joint page sent before, for a sheet pair: its own guesses.
function jointBefore(lifeSheet, readSheet) {
  const g = guessLifetimeColumns(described(lifeSheet));
  const map = { id: g.id, x: g.x, xl: "", xr: "", c: g.c, tl: "" };
  const rmap = guessReadingColumns(described(readSheet));
  const covs = g.covariates.map((c) => ({ name: c, risk: false, path: false }));
  return { request: jointRequest(map, rmap, g.invert, covs), unit: g.unit, marker: rmap.value, markerUnit: "" };
}
function jointAfter(lifeSheet, readSheet) {
  const reading = { ...guess(lifeSheet), measurements: partReading(readSheet) };
  const d = jointMappingsFromReading(reading, { lifeFacts: columnFacts(lifeSheet) });
  const covs = d.covariates.map((c) => ({ name: c, risk: false, path: false }));
  return {
    request: jointRequest(d.map, d.rmap, d.invert, covs), unit: d.unit, marker: d.rmap.value, markerUnit: d.markerUnit,
    issues: jointIssues(d.map, d.rmap), statusIssue: d.statusIssue,
  };
}

test("condition and life: W03's reading sends the same request as the page's own guesses", () => {
  const before = jointBefore(S.w03life, S.w03reads);
  const { issues, statusIssue, ...after } = jointAfter(S.w03life, S.w03reads);
  assert.deepEqual(after, before);
  assert.deepEqual(after.request, {
    mapping: { id: "pump", x: "age_days", c: "running" },
    readings_mapping: { id: "pump", age: "age_days", value: "vibration_mm_s" },
    c_invert: false,
    covariates: [],
  });
  assert.deepEqual(issues, []);
  assert.equal(statusIssue, null);
});

test("condition and life: W24's life data is read with no i (bearing is unique per row), so i is asked for", () => {
  // The guessed reading leaves "bearing" out (an id on every row, not an item column);
  // the page's old guess took it as the id. Everything else is the same.
  const before = jointBefore(S.w24life, S.w24reads);
  const { issues, statusIssue, ...after } = jointAfter(S.w24life, S.w24reads);
  assert.deepEqual(after.request.readings_mapping, before.request.readings_mapping);
  assert.deepEqual(after.request.readings_mapping, { id: "bearing", age: "age_days", value: "vibration_mm_s" });
  assert.deepEqual(after.request.mapping, { x: "age_days", c: "running" });
  assert.deepEqual({ ...before.request.mapping, id: undefined }, { ...after.request.mapping, id: undefined });
  assert.deepEqual([after.unit, after.marker, after.markerUnit, after.request.c_invert],
    [before.unit, before.marker, before.markerUnit, before.request.c_invert]);
  assert.deepEqual(issues.map((i) => `${i.table}:${i.row}`), ["life:i"]);
  // With i given (Change), the request is the old one.
  const reading = { ...guess(S.w24life), i: "bearing", measurements: partReading(S.w24reads) };
  const d = jointMappingsFromReading(reading, { lifeFacts: columnFacts(S.w24life) });
  assert.deepEqual(jointRequest(d.map, d.rmap, d.invert, []), before.request);
});

test("condition and life: one table holding both reads its readings from the main reading", () => {
  const r = { ...emptyReading(), i: "unit", x: "age", c: "failed", m: "wear", m_unit: "mm", unit: "Hours" };
  const d = jointMappingsFromReading(r, { combined: true });
  assert.deepEqual(d.rmap, { id: "unit", age: "age", value: "wear" });
  assert.equal(d.markerUnit, "mm");
  // No measurements part and not combined: the readings mapping is empty, said by jointIssues.
  const lone = jointMappingsFromReading(r);
  assert.deepEqual(jointIssues(lone.map, lone.rmap).map((i) => `${i.table}:${i.row}`), ["reads:i", "reads:x", "reads:m"]);
});

test("condition and life: status words become c_invert when they are 0/1 codes, else a plain issue", () => {
  const base = { ...emptyReading(), i: "u", x: "t", c: "flag" };
  assert.equal(jointMappingsFromReading({ ...base, c_invert: true }).invert, true);
  assert.equal(jointMappingsFromReading({ ...base, c_map: { 1: 0, 0: 1 } }).invert, true);
  assert.equal(jointMappingsFromReading({ ...base, c_map: { 0: 0, 1: 1 } }).invert, false);
  const words = jointMappingsFromReading({ ...base, c: "Status", c_map: { Failed: 0, Running: 1 } });
  assert.match(words.statusIssue, /“Status”.*in words \(Failed, Running\).*0\/1 codes/);
  // The range in place of x; never both sent.
  const range = jointMappingsFromReading({ ...base, x: "", xl: "a", xr: "b" });
  assert.deepEqual(jointRequest(range.map, range.rmap, false, []).mapping, { id: "u", xl: "a", xr: "b", c: "flag" });
  // Covariates: Z's numeric columns only.
  const facts = { load: { dtype: "float64" }, site: { dtype: "str" } };
  assert.deepEqual(jointMappingsFromReading({ ...base, z: ["load", "site"] }, { lifeFacts: facts }).covariates, ["load"]);
});
