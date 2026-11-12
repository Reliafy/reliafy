// Run with: node --test src/
// The repairable and accelerated-life fits from a saved dataset's reading
// (#dataset-reading): the mapping each flow derives from the reading sends
// the same fit request as the flow's own column guess did before
// (dataStepFamily.test.js holds those requests).
import { test } from "node:test";
import assert from "node:assert/strict";
import { FAMILY_SHEETS as S } from "./dataStepFamilySheets.js";
import CASES from "./readingGuessCases.json" with { type: "json" };
import { columnFacts } from "./lifeData.js";
import { emptyReading, guessReading } from "./datasetReading.js";
import {
  guessRecurrentMapping, readingWithRecurrentMapping, recurrentFields, recurrentIssues, recurrentMappingFromReading,
  recurrentWithCovariates,
} from "./recurrentMapping.js";
import {
  altDataIssues, altFields, altMapping, altMappingFromReading, altStressFromReading, altStressIssues, altStressPool,
  guessAltColumns, suggestLifeModel, suggestLifeModelFromReading,
} from "./altGuess.js";
import { codedStatus, codedStatusNote, unitColumnProblem } from "./readingCodes.js";
import { guessUnit } from "./datasetGuess.js";

const read = (name) => {
  const sheet = S[name];
  const facts = columnFacts(sheet);
  return { sheet, facts, guessed: guessReading(sheet.columns, facts, sheet.n_rows) };
};

test("repairable from the reading: the same request as the flow's own guess (w15, w16, w17)", () => {
  const before = {
    w15: [["i", "truck"], ["x", "pump_failure_hours"], ["tr", "observed_to_hours"]],
    w16: [["i", "compressor"], ["x", "failure_hours"], ["tr", "records_end_hours"]],
    w17: [["i", "unit"], ["x", "failure_hours"], ["tr", "trial_end_hours"], ["mode", "failure_mode"]],
  };
  for (const [name, fields] of Object.entries(before)) {
    const { sheet, facts, guessed } = read(name);
    for (const [how, r] of [["guessed", guessed], ["expected", { ...emptyReading(), ...CASES[name] }]]) {
      const d = recurrentMappingFromReading(r, facts, sheet.n_rows);
      assert.equal(d.missing, null, `${name} ${how}`);
      assert.deepEqual(recurrentFields(d.mapping), fields, `${name} ${how}`);
      assert.deepEqual(recurrentIssues(d.mapping), [], `${name} ${how}`);
      // The unit sent is the one the old flow guessed.
      const g = guessRecurrentMapping(sheet.columns, { dtypes: sheet.dtypes, preview: sheet.preview });
      assert.equal(d.unit, guessUnit(g.x) || guessUnit(g.tr), `${name} ${how} unit`);
    }
  }
});

test("repairable: the reading's covariates go only to the covariate models", () => {
  const { sheet, facts, guessed } = read("w17");
  const d = recurrentMappingFromReading(guessed, facts, sheet.n_rows);
  assert.equal(d.mapping.z, undefined);
  assert.deepEqual(recurrentFields(recurrentWithCovariates(d.mapping, guessed)).slice(-1), [["z", "site"]]);
  assert.deepEqual(recurrentWithCovariates(d.mapping, { ...guessed, z: [] }), d.mapping);
});

test("repairable: no i in the reading says so plainly instead of fitting", () => {
  const { sheet, facts, guessed } = read("w16");
  const d = recurrentMappingFromReading({ ...guessed, i: "" }, facts, sheet.n_rows);
  assert.match(d.missing, /needs i: the column that says which system/);
  assert.equal(d.mapping.i, "");
  // A per-row unit column can't be read by this fit either.
  assert.match(recurrentMappingFromReading({ ...guessed, u: "unit_col" }, facts, sheet.n_rows).missing, /one unit/);
  assert.equal(unitColumnProblem(guessed), null);
});

test("repairable: a dataset saved before readings starts from its last repairable model's columns", () => {
  const { sheet, facts, guessed } = read("w17");
  const kept = { mapping: { i: "unit", x: "failure_hours", c: "", n: "", tl: "", tr: "", mode: "", z: ["site"] }, unit: "Hours" };
  const r = readingWithRecurrentMapping(guessed, kept, facts, sheet.n_rows);
  assert.equal(r.tr, "");
  assert.equal(r.e, "");
  assert.deepEqual(r.z, ["site"]);
  assert.deepEqual([...r.not_used].sort(), ["failure_mode", "trial_end_hours"]);
  const d = recurrentMappingFromReading(r, facts, sheet.n_rows);
  assert.deepEqual(recurrentFields(d.mapping), [["i", "unit"], ["x", "failure_hours"]]);
  assert.equal(readingWithRecurrentMapping(guessed, null), guessed);
});

test("accelerated life from the reading: the same request as the flow's own guess (w18)", () => {
  const { sheet, facts, guessed } = read("w18");
  // The old flow posted { x, c } and s1 with its unit.
  const before = [["x", "hours"], ["c", "censored"], ["s1", "temp_K"], ["s1_unit", "K"]];
  const g = guessAltColumns(sheet, { nStress: 1, lifeModel: "arrhenius" });
  assert.deepEqual(altFields(altMapping({ x: g.x, c: g.c }), g.stress), before);
  for (const [how, r] of [["guessed", guessed], ["expected", { ...emptyReading(), ...CASES.w18 }]]) {
    const d = altMappingFromReading(r, facts, sheet.n_rows);
    assert.equal(d.missing, null, how);
    // The reading's c is "status" (words); this fit reads 0/1 codes, so the
    // "censored" column, which says the same row for row, stands in.
    assert.deepEqual(d.status, { c: "censored", from: "status", problem: null }, how);
    assert.match(codedStatusNote(d.status), /uses “censored” for c/);
    const stress = altStressFromReading(sheet, r, { nStress: 1, lifeModel: "arrhenius", c: d.status.c });
    assert.deepEqual(altFields(altMapping(d.map), stress), before, how);
    assert.deepEqual(altDataIssues(d.map), [], how);
    assert.deepEqual(altStressIssues(stress, 1, "arrhenius", d.map), [], how);
    assert.equal(d.unit, g.unit, how);
    assert.equal(suggestLifeModelFromReading(sheet, r, d.status.c), suggestLifeModel(sheet), how);
  }
});

test("accelerated life: stresses offered from Z, else the numeric columns with no role", () => {
  const { sheet, facts, guessed } = read("w18");
  assert.deepEqual(altStressPool(sheet, guessed, "censored"), ["temp_C", "temp_K"]);
  assert.deepEqual(altStressPool(sheet, { ...guessed, z: [] }, "censored"), ["temp_C", "temp_K"]);
  // Two stresses: both temperatures are one stress, so the second slot takes the other column.
  const two = altStressFromReading(sheet, guessed, { nStress: 2, lifeModel: "arrhenius", c: "censored" });
  assert.equal(two[0].col, "temp_K");
  // No x: said plainly.
  assert.match(altMappingFromReading({ ...guessed, x: "" }, facts, sheet.n_rows).missing, /no x/);
});

test("a status in words or 1 = failed, with no 0/1 column saying the same, stops the fit with the fix", () => {
  const { sheet, facts, guessed } = read("w18");
  const noTwin = { ...guessed, not_used: [] };
  const s = codedStatus(noTwin, facts, sheet.n_rows);
  assert.equal(s.c, "status");
  assert.match(s.problem, /holds words\. Change the reading/);
  // A 0/1 column whose counts don't match the words isn't used in their place.
  const odd = { ...facts, censored: { ...facts.censored, values: { 0: 30, 1: 30 } } };
  assert.match(codedStatus(guessed, odd, sheet.n_rows).problem, /holds words/);
  // 1 = failed: flipped counts would have to match.
  const inv = { ...guessed, c: "censored", c_map: null, c_invert: true, not_used: [] };
  assert.match(codedStatus(inv, facts, sheet.n_rows).problem, /uses 1 for a failure/);
  // Codes as they are: nothing to say.
  assert.deepEqual(codedStatus({ ...guessed, c: "censored", c_map: null }, facts, sheet.n_rows),
    { c: "censored", from: null, problem: null });
  assert.equal(codedStatusNote({ c: "censored", from: null }), null);
});
