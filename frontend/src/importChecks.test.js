// The Data step reads what a sheet's headers and values say (walkthrough, 12 Nov):
// a "Failed (1=yes)" flag is 1 = failed, and a "Units" column of hrs / days
// gives each row's unit. Run with: node --test src/importChecks.test.js
import { test } from "node:test";
import assert from "node:assert/strict";
import { censorInverted, flagHeaderMeaning, guessUnitColumn, timeUnitOf } from "./datasetGuess.js";
import {
  EMPTY_MAPPING, answerQuestion, columnFacts, dataQuestions, dataStepProblems, flagWords, guessMapping,
  flagsLookSwapped, mappingWords, statusSummary, summaryParts, unitColumnWords,
} from "./lifeData.js";
import { priorBlocked } from "./priorFit.js";

// /api/columns for the idler-bearing sheet: 26 bearings, 10 failed (1 = yes),
// 22 rows in hours and 4 in days.
const IDLERS = {
  columns: ["Idler No.", "Conveyor", "Time in service", "Units", "Failed (1=yes)", "Comment"],
  dtypes: ["object", "str", "float64", "str", "float64", "str"],
  blanks: [0, 0, 0, 0, 0, 9],
  values: [null, { "CV-07": 13, "CV-12": 13 }, null, { hrs: 22, days: 4 }, { 0: 16, 1: 10 },
    { "seized, belt damage": 4, "still running": 8, "noisy, changed out": 6 }],
  n_unique: [26, 2, 26, 2, 2, 3],
  n_rows: 26,
  preview: [["ID-4400", "CV-07", 11116, "hrs", 1, "seized, belt damage"]],
};
const facts = columnFacts(IDLERS);

test("headers that say what 1 means are read that way", () => {
  for (const n of ["Failed (1=yes)", "failed?", "failure (y/n)", "1 = failed", "Failed (yes=1)", "status (1=failed)",
    "Failed (0=no, 1=yes)", "is_failed", "Event"]) {
    assert.equal(flagHeaderMeaning(n), "failed", n);
    assert.equal(censorInverted(n), true, n);
  }
  for (const n of ["Running (1=yes)", "Still running? 1 = yes", "Failed (1=no)", "0 = failed", "censored", "c",
    "Suspended (Y/N)"]) {
    assert.equal(flagHeaderMeaning(n), "running", n);
    assert.equal(censorInverted(n), false, n);
  }
  // A header that doesn't say: the Data step asks.
  for (const n of ["Status", "flag", "outcome", "State"]) assert.equal(flagHeaderMeaning(n), null, n);
});

test("“Failed (1=yes)” is read as 10 failed, 16 still running, and says so", () => {
  const { mapping } = guessMapping(IDLERS.columns, facts);
  assert.equal(mapping.c, "Failed (1=yes)");
  assert.equal(mapping.c_invert, true);
  const s = statusSummary(mapping, facts, IDLERS.n_rows);
  assert.deepEqual(summaryParts(s), ["10 failures", "16 still running"]);
  assert.equal(flagWords(mapping, facts), "1 = failed, 0 = still running");
  // Most units still running, but the header says which way round: no "swap the flags?".
  assert.equal(flagsLookSwapped(mapping, s), null);
  assert.deepEqual(flagsLookSwapped({ ...mapping, c: "censored" }, s), { code: "0" });
  // The header says, so nothing is asked about the flag.
  assert.equal(dataQuestions(mapping, facts, IDLERS.columns, IDLERS.n_rows).filter((q) => q.id.startsWith("flags:")).length, 0);
});

test("a 0/1 column whose header doesn't say is asked about, with the counts both ways", () => {
  const cols = { ...IDLERS, columns: IDLERS.columns.map((c) => (c === "Failed (1=yes)" ? "Status" : c)) };
  const f = columnFacts(cols);
  const { mapping } = guessMapping(cols.columns, f);
  assert.equal(mapping.c, "Status");
  const [q] = dataQuestions(mapping, f, cols.columns, cols.n_rows).filter((x) => x.id === "flags:Status");
  assert.ok(q, "asks which way round");
  assert.equal(q.yes, "1 = failed: 10 failures, 16 still running");
  assert.equal(q.no, "0 = failed: 16 failures, 10 still running");
  const yes = answerQuestion(mapping, q, true, f);
  assert.equal(yes.mapping.c_invert, true);
  assert.deepEqual(summaryParts(statusSummary(yes.mapping, f, cols.n_rows)), ["10 failures", "16 still running"]);
  assert.equal(dataQuestions(yes.mapping, f, cols.columns, cols.n_rows, yes.answered).length, 0);
  const no = answerQuestion(mapping, q, false, f);
  assert.equal(no.mapping.c_invert, false);
});

test("a Units column of hrs / days is used to convert rows to the most common unit", () => {
  assert.equal(timeUnitOf("hrs"), "Hours");
  assert.equal(timeUnitOf("d"), "Days");
  assert.equal(timeUnitOf("cycles"), "");
  assert.equal(timeUnitOf("CV-07"), "");
  const { mapping, unit } = guessMapping(IDLERS.columns, facts);
  assert.equal(mapping.u, "Units");
  assert.equal(unit, "Hours");
  const w = unitColumnWords(mapping, facts, unit);
  assert.equal(w.converted, 4);
  assert.equal(w.note, "“Units” gives each row's unit (22 in hours, 4 in days): 4 rows are converted to hours before the fit.");
  assert.equal(unitColumnWords(mapping, facts, "Days").converted, 22);
  assert.deepEqual(dataStepProblems(mapping, facts, IDLERS.n_rows, unit), []);
  assert.ok(mappingWords(mapping, facts, unit).some((x) => x.label === "Unit of each row"));
  // A unit it can't convert to is a problem, with the counts.
  const [p] = dataStepProblems(mapping, facts, IDLERS.n_rows, "Cycles");
  assert.match(p, /22 in hours, 4 in days.*pick Hours, Days/);
  // A fit with a prior can't convert yet: it says so rather than fit hours and days as one.
  assert.match(priorBlocked(mapping), /each row's unit/);
});

test("a mixed unit column left unused is asked about, loudly", () => {
  const { mapping } = guessMapping(IDLERS.columns, facts);
  const off = { ...mapping, u: "" };
  const [q] = dataQuestions(off, facts, IDLERS.columns, IDLERS.n_rows);
  assert.equal(q.id, "unit:Units");
  assert.match(q.text, /22 in hours, 4 in days/);
  assert.equal(answerQuestion(off, q, true, facts).mapping.u, "Units");
  // One unit throughout isn't mixed.
  assert.equal(guessUnitColumn([{ name: "Units", dtype: "object", values: { hrs: 26 } }]), null);
  assert.equal(guessMapping(IDLERS.columns, columnFacts({ ...IDLERS, values: IDLERS.values.map((v, i) => (i === 3 ? { hrs: 26 } : v)) })).mapping.u, "");
  assert.equal(EMPTY_MAPPING.u, "");
});
