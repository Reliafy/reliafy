// Run with: node --test src/
// The 12 Nov life-data walkthroughs: status phrases, a failure-mode column, a
// blank status meaning, the mapping a dataset was last fitted with, late entry.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MAPPING, columnFacts, guessMapping, lateEntryWords, savedMapping, setStatusMeaning, statusSummary,
  statusValuesWithBlank, dataStepProblems,
} from "./lifeData.js";
import { guessStatusMeaning } from "./datasetGuess.js";
import { meanLifeAnswer } from "./meanLife.js";
import { answerParts } from "./modelFrame.js";

test("status phrases are read by their words: Removed, OK runs; Found failed failed; not failed is asked", () => {
  assert.equal(guessStatusMeaning("Removed, OK", "Status"), 1);
  assert.equal(guessStatusMeaning("OK at last check", "Status"), 1);
  assert.equal(guessStatusMeaning("Found failed", "Status"), 0);
  assert.equal(guessStatusMeaning("Not failed", "Status"), null);
  assert.equal(guessStatusMeaning("Failed, OK", "Status"), null);
});

// W11's sheet: Supplier, Run hours, Status (Failed / Removed, OK).
const BEARINGS = {
  columns: ["Bearing", "Supplier", "Run hours", "Status"], n_rows: 60,
  preview: [["A-01", "Supplier A", 6250, "Removed, OK"]], n_unique: [60, 2, 58, 2],
  dtypes: ["str", "str", "int64", "str"], blanks: [0, 0, 0, 0],
  values: [null, { "Supplier A": 30, "Supplier B": 30 }, null, { Failed: 35, "Removed, OK": 25 }],
};

test("a text status column with Removed, OK is read as 35 failed, 25 still running with no mapping asked", () => {
  const facts = columnFacts(BEARINGS);
  const { mapping } = guessMapping(BEARINGS.columns, facts);
  assert.equal(mapping.c, "Status");
  assert.deepEqual(statusSummary(mapping, facts, 60), { failed: 35, running: 25, left: 0, interval: 0 });
});

// W12's sheet: Hours, Status, Failure mode (blank for the seals still running).
const SEALS = {
  columns: ["Seal", "Hours", "Status", "Failure mode"], n_rows: 80,
  preview: [["PS-001", 7300, "Failed", "Installation"]], n_unique: [80, 70, 2, 2],
  dtypes: ["str", "int64", "str", "str"], blanks: [0, 0, 0, 43],
  values: [null, null, { Failed: 37, Running: 43 }, { Wear: 22, Installation: 15 }],
};

test("a column named Failure mode beside a status column is the failure mode", () => {
  const facts = columnFacts(SEALS);
  const { mapping } = guessMapping(SEALS.columns, facts);
  assert.equal(mapping.c, "Status");
  assert.equal(mapping.e, "Failure mode");
});

test("a blank status cell can be given a meaning: the mode column as the status", () => {
  const facts = columnFacts(SEALS);
  let m = { ...EMPTY_MAPPING, x: "Hours", c: "Failure mode" };
  const values = statusValuesWithBlank(facts["Failure mode"].values, facts["Failure mode"].blanks);
  assert.match(dataStepProblems(m, facts, 80).join(" "), /Say what a blank means/);
  m = setStatusMeaning(m, values, "Wear", 0);
  m = setStatusMeaning(m, values, "Installation", 1);
  m = setStatusMeaning(m, values, "", 1);
  assert.deepEqual(m.c_map, { Wear: 0, Installation: 1, "": 1 });
  assert.deepEqual(statusSummary(m, facts, 80), { failed: 22, running: 58, left: 0, interval: 0 });
  assert.equal(dataStepProblems(m, facts, 80).length, 0);
});

test("a dataset's last mapping is reused when its columns are all there", () => {
  const cols = ["Unit", "Entered at (h)", "Last good check (h)", "Found failed at (h)", "Status"];
  const saved = {
    mapping: { xl: "Last good check (h)", xr: "Found failed at (h)", c: "Status", tl: "Entered at (h)" },
    options: { c_map: { "Found failed": 2, "OK at last check": 1 } }, unit: "Hours", model_name: "Valves",
  };
  const kept = savedMapping(saved, cols);
  assert.equal(kept.mapping.tl, "Entered at (h)");
  assert.deepEqual(kept.mapping.c_map, { "Found failed": 2, "OK at last check": 1 });
  assert.equal(kept.unit, "Hours");
  assert.equal(kept.from, "Valves");
  // A column gone: a fresh guess instead.
  assert.equal(savedMapping(saved, cols.filter((c) => c !== "Entered at (h)")), null);
  assert.equal(savedMapping(null, cols), null);
});

test("late entry is said in words, counted from the column's values", () => {
  const facts = { "Entered at (h)": { values: { 0: 40, 1000: 6, 1500: 7, 2000: 7 } } };
  assert.equal(lateEntryWords("Entered at (h)", facts), "20 units entered late (observed from “Entered at (h)”): accounted for");
  assert.match(lateEntryWords("Entered", {}), /late entry from “Entered”/);
});

test("a mean from three failures is flagged as an extrapolation", () => {
  const result = { kind: "distribution", distribution_id: "weibull", params: [{ name: "beta", value: 1.31 }],
                   split: { failed: 3, running: 37, other: 0 }, unit: "Hours", n: 40,
                   life: { confidence: 0.9, b_lives: [{ label: "B10", value: 4960, lower: 2800 }], mttf: { value: 25400 } } };
  const a = meanLifeAnswer(result, { value: 25400 });
  assert.equal(a.fewFailures, 3);
  assert.match(a.caveat, /Only 3 failures/);
  assert.ok(answerParts(result).some((p) => /mean 25,400 Hours \(from 3 failures: extrapolated\)/i.test(p)));
  // Enough failures: no caveat.
  assert.equal(meanLifeAnswer({ ...result, split: { failed: 12, running: 3, other: 0 } }, { value: 25400 }).caveat, null);
});

test("a B-life from inspection data reads as its interval; one with no bound says so", () => {
  const between = { kind: "nonparametric", distribution: "Turnbull", unit: "Hours", n: 60,
                    life: { confidence: 0.9, b_lives: [{ label: "B10", value: null, lower: null, between: [1500, 2000] }] } };
  assert.ok(answerParts(between).some((p) => /B10 1,500–2,000 Hours \(between inspections\)/i.test(p)));
  const mpp = { kind: "distribution", distribution_id: "weibull", unit: "Hours", n: 30, params: [],
                life: { confidence: 0.9, bounds_note: "No confidence bounds: only a maximum-likelihood fit has them.",
                        b_lives: [{ label: "B10", value: 3030, lower: null }] } };
  assert.ok(answerParts(mpp).some((p) => /B10 3,030 Hours \(no bound with this fit\)/i.test(p)));
});
