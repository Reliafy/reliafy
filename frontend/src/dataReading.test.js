// Run with: node --test src/
// How a file is first read on the Data step: inspection data with survivors,
// and the places where the reading is a guess and is asked, not stated.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MAPPING, columnFacts, guessMapping, statusSummary, summaryParts, dataQuestions, answerQuestion,
  mappingWords, dataStepProblems,
} from "./lifeData.js";
import { guessIntervalPair, guessLifeColumns } from "./datasetGuess.js";

// Valves inspected every 200 hours: found failed between two inspections, or
// still fine at the last one (a blank "found failed").
const VALVES = {
  columns: ["valve", "last_ok_hours", "found_failed_hours"],
  preview: [["V01", 400, 600], ["V03", 1000, null]],
  n_rows: 40, n_unique: [40, 6, 5],
  dtypes: ["str", "int64", "float64"], blanks: [0, 0, 15], values: [null, { 0: 2, 200: 6 }, null],
};
const CODED = {
  columns: [...VALVES.columns, "censor_code"],
  preview: [["V01", 400, 600, 2], ["V03", 1000, 1000, 1]],
  n_rows: 40, n_unique: [40, 6, 5, 2],
  dtypes: ["str", "int64", "int64", "int64"], blanks: [0, 0, 0, 0],
  values: [null, null, null, { 2: 25, 1: 15 }],
};
const WORDS = {
  ...CODED, columns: [...VALVES.columns, "status"], dtypes: ["str", "int64", "int64", "str"],
  values: [null, null, null, { F: 25, S: 15 }],
};
// The failure-mode sample: no status column, a blank mode on the units still running.
const MODES = {
  columns: ["pump", "hours", "failure_mode", "site", "duty_pct"],
  preview: [["P-1", 1200, "bearing wear", "North", 60]],
  n_rows: 72, n_unique: [72, 70, 3, 2, 5],
  dtypes: ["str", "int64", "str", "str", "int64"], blanks: [0, 0, 22, 0, 0],
  values: [null, null, { "bearing wear": 29, "seal leak": 14, "impeller erosion": 7 }, { North: 36, South: 36 }, null],
};

test("two inspection times are read as an interval, not as one exact time", () => {
  const facts = columnFacts(VALVES);
  assert.deepEqual(guessIntervalPair(VALVES.columns.map((name) => ({ name, ...facts[name] }))),
                   { xl: "last_ok_hours", xr: "found_failed_hours" });
  const { mapping, unit } = guessMapping(VALVES.columns, facts);
  assert.equal(mapping.x, "");
  assert.equal(mapping.xl, "last_ok_hours");
  assert.equal(mapping.xr, "found_failed_hours");
  assert.equal(unit, "Hours");
  // A blank latest time is a unit still running, not a problem.
  assert.deepEqual(dataStepProblems(mapping, facts, 40), []);
  // xl / xr, lower / upper, shortest / longest read the same way.
  for (const [a, b] of [["xl", "xr"], ["lower", "upper"], ["shortest", "longest"], ["Earliest (h)", "Latest (h)"]]) {
    const cols = [{ name: a, dtype: "float64" }, { name: b, dtype: "float64" }];
    assert.deepEqual(guessIntervalPair(cols), { xl: a, xr: b }, a);
  }
  // Two usage measures aren't an interval; nor is a start and stop of rows per item.
  assert.equal(guessIntervalPair([{ name: "hours", dtype: "int64" }, { name: "cycles", dtype: "int64" }]), null);
  assert.equal(guessIntervalPair([{ name: "start_h", dtype: "int64" }, { name: "stop_h", dtype: "int64" }]), null);
});

test("a numeric censor-code column is the status, though its name says 'code'", () => {
  const facts = columnFacts(CODED);
  const { mapping } = guessMapping(CODED.columns, facts);
  assert.equal(mapping.c, "censor_code");
  assert.equal(mapping.xl, "last_ok_hours");
  assert.equal(mapping.c_invert, false);
  assert.equal(mapping.c_map, null);
  // A failure code of other numbers, or of words, still isn't one.
  const pick = (col) => guessLifeColumns([{ name: "hours", dtype: "int64", values: null }, col]).c;
  assert.equal(pick({ name: "failure_code", dtype: "int64", values: { 0: 3, 1: 2 } }), "");
  assert.equal(pick({ name: "censor_code", dtype: "int64", values: { 3: 3, 7: 2 } }), "");
});

test("a status of words beside inspection times keeps its meanings", () => {
  const facts = columnFacts(WORDS);
  const { mapping } = guessMapping(WORDS.columns, facts);
  assert.equal(mapping.c, "status");
  assert.deepEqual(mapping.c_map, { F: 0, S: 1 });
  assert.equal(mapping.xr, "found_failed_hours");
});

test("the count line for inspection data comes from the server's reading", () => {
  // The value counts can't say it (it is row by row), so there is no guess...
  const facts = columnFacts(VALVES);
  const { mapping } = guessMapping(VALVES.columns, facts);
  assert.equal(statusSummary(mapping, facts, 40), null);
  // ...and the reading is worded for inspections.
  assert.deepEqual(summaryParts({ failed: 0, running: 15, left: 2, interval: 23 }, { inspection: true }),
                   ["23 failed between inspections", "2 found failed at the first inspection", "15 still running"]);
  assert.deepEqual(summaryParts({ failed: 15, running: 0, left: 2, interval: 23 }, { inspection: true }),
                   ["15 failed at a known time", "23 failed between inspections", "2 found failed at the first inspection"]);
  // Plain times keep their wording.
  assert.deepEqual(summaryParts({ failed: 15, running: 6, left: 0, interval: 0 }), ["15 failures", "6 still running"]);
});

test("a blank failure mode is asked about, not counted as a failure", () => {
  const facts = columnFacts(MODES);
  const { mapping } = guessMapping(MODES.columns, facts);
  assert.equal(mapping.e, "");
  const [q, ...rest] = dataQuestions(mapping, facts, MODES.columns, 72);
  assert.equal(rest.length, 0);
  assert.equal(q.id, "mode:failure_mode");
  assert.match(q.text, /22 rows have no “failure_mode”/);
  assert.match(q.text, /still running/);
  // Yes: the modes are fitted, and the count follows (50 failed, 22 running).
  const yes = answerQuestion(mapping, q, true, facts);
  assert.equal(yes.mapping.e, "failure_mode");
  assert.deepEqual(dataQuestions(yes.mapping, facts, MODES.columns, 72, yes.answered), []);
  assert.deepEqual(summaryParts(statusSummary(yes.mapping, facts, 72)), ["50 failures", "22 still running"]);
  // No: every row is a failure, by the user's word.
  const no = answerQuestion(mapping, q, false, facts);
  assert.equal(no.mapping.e, "");
  assert.deepEqual(dataQuestions(no.mapping, facts, MODES.columns, 72, no.answered), []);
});

test("a column named like a status that can't be read is asked about", () => {
  const cols = {
    columns: ["hours", "state"], preview: [[100, "amber"]], n_rows: 12, n_unique: [12, 3],
    dtypes: ["int64", "str"], blanks: [0, 0], values: [null, { amber: 4, green: 4, review: 4 }],
  };
  const facts = columnFacts(cols);
  const { mapping } = guessMapping(cols.columns, facts);
  assert.equal(mapping.c, "");
  const [q] = dataQuestions(mapping, facts, cols.columns, 12);
  assert.equal(q.id, "status:state");
  assert.match(q.text, /“state”/);
  const yes = answerQuestion(mapping, q, true, facts);
  assert.equal(yes.mapping.c, "state");
  // Its values then need a meaning each: the Data step asks, as before.
  assert.match(dataStepProblems(yes.mapping, facts, 12)[0], /Say whether/);
});

test("nothing is asked when the reading isn't in doubt", () => {
  const plain = { columns: ["hours", "censored"], preview: [[100, 0]], n_rows: 10, n_unique: [10, 2],
                  dtypes: ["int64", "int64"], blanks: [0, 0], values: [null, { 0: 7, 1: 3 }] };
  const facts = columnFacts(plain);
  assert.deepEqual(dataQuestions(guessMapping(plain.columns, facts).mapping, facts, plain.columns, 10), []);
  // A failure mode on every row: every row did fail.
  const full = columnFacts({ ...MODES, blanks: [0, 0, 0, 0, 0] });
  assert.deepEqual(dataQuestions({ ...EMPTY_MAPPING, x: "hours" }, full, MODES.columns, 72), []);
});

test("inspection times with no status read back with what a blank means", () => {
  const words = mappingWords({ ...EMPTY_MAPPING, xl: "last_ok_hours", xr: "found_failed_hours" }, columnFacts(VALVES), "Hours");
  assert.deepEqual(words, [
    { label: "Time", value: "between “last_ok_hours” and “found_failed_hours” (Hours)" },
    { label: "Status", value: "none: a blank “found_failed_hours” is a unit still running" },
  ]);
});
