// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MAPPING, columnFacts, guessMapping, statusMeaning, setStatusMeaning, encodeStatus,
  statusSummary, summaryParts, dataStepProblems, isSimplePaste, dataSplit,
  countProblem, columnRoles, assignRole, roleSummary, roleChoices, roleLabel,
} from "./lifeData.js";

// A CMMS export: id, hours, a text status, a site.
const PUMPS = {
  columns: ["Pump ID", "Operating Hours", "Status", "Site"],
  preview: [["P-100", 4667, "Failed", "South"]],
  n_rows: 21,
  n_unique: [21, 21, 2, 2],
  dtypes: ["str", "int64", "str", "str"],
  blanks: [0, 0, 0, 0],
  values: [null, null, { Failed: 15, Running: 6 }, { North: 10, South: 11 }],
};
const facts = columnFacts(PUMPS);

test("an upload with a text status: hours as the time, Status mapped Failed / Running", () => {
  const { mapping, unit } = guessMapping(PUMPS.columns, facts);
  assert.equal(mapping.x, "Operating Hours");
  assert.equal(mapping.c, "Status");
  assert.deepEqual(mapping.c_map, { Failed: 0, Running: 1 });
  assert.equal(mapping.c_invert, false);
  assert.equal(unit, "Hours");
  assert.deepEqual(dataStepProblems(mapping, facts, 21), []);
  assert.deepEqual(summaryParts(statusSummary(mapping, facts, 21)), ["15 failures", "6 still running"]);
});

test("a user's change to one value's meaning is kept with the others", () => {
  const { mapping } = guessMapping(PUMPS.columns, facts);
  const swapped = setStatusMeaning(mapping, facts.Status.values, "Running", 0);
  assert.deepEqual(swapped.c_map, { Failed: 0, Running: 0 });
  assert.deepEqual(statusSummary(swapped, facts, 21), { failed: 21, running: 0, left: 0, interval: 0 });
});

test("an unknown word is asked about in plain words, and blocks the fit", () => {
  const f = columnFacts({ ...PUMPS, values: [null, null, { Failed: 15, Running: 5, Pending: 1 }, null] });
  const { mapping } = guessMapping(PUMPS.columns, f);
  assert.equal(statusMeaning("Pending", mapping), null);
  const problems = dataStepProblems(mapping, f, 21);
  assert.deepEqual(problems, ["Say whether “Pending” means failed or still running."]);
  assert.equal(statusSummary(mapping, f, 21), null);
});

test("a text time column is refused before the fit, not with 'cannot contain NaN'", () => {
  const m = { ...EMPTY_MAPPING, x: "Pump ID" };
  const [p] = dataStepProblems(m, facts, 21);
  assert.match(p, /“Pump ID” holds text \(e\.g\. “P-100”\), not times/);
  const blank = columnFacts({ ...PUMPS, blanks: [0, 2, 1, 0] });
  const { mapping } = guessMapping(PUMPS.columns, blank);
  assert.deepEqual(dataStepProblems(mapping, blank, 21), [
    "2 rows have no time in “Operating Hours”. Fill them in or delete those rows, then load the file again.",
    "1 row has no value in “Status”. Fill in whether each unit failed or was still running.",
  ]);
});

test("a status column with many values can't be a status", () => {
  const m = { ...EMPTY_MAPPING, x: "Operating Hours", c: "Pump ID" };
  assert.match(dataStepProblems(m, facts, 21)[0], /“Pump ID” has 21 different values/);
});

test("0/1 codes are sent as c_invert, as before; words as c_map", () => {
  assert.deepEqual(encodeStatus([["0", 0], ["1", 1]]), { c_invert: false, c_map: null });
  assert.deepEqual(encodeStatus([["0", 1], ["1", 0]]), { c_invert: true, c_map: null });
  assert.deepEqual(encodeStatus([["1", 0], ["0", 1], ["-1", -1]]), { c_invert: true, c_map: null });
  assert.deepEqual(encodeStatus([["F", 0], ["S", 1]]), { c_invert: false, c_map: { F: 0, S: 1 } });
  assert.deepEqual(encodeStatus([["0", 0], ["1", 0]]), { c_invert: false, c_map: { 0: 0, 1: 0 } });
});

test("a 'failed' 0/1 column is inverted, and the summary follows", () => {
  const cols = {
    columns: ["unit", "hours", "failed"], preview: [], n_rows: 10,
    dtypes: ["str", "int64", "int64"], blanks: [0, 0, 0], values: [null, null, { 1: 7, 0: 3 }],
  };
  const f = columnFacts(cols);
  const { mapping } = guessMapping(cols.columns, f);
  assert.equal(mapping.c, "failed");
  assert.equal(mapping.c_invert, true);
  assert.deepEqual(summaryParts(statusSummary(mapping, f, 10)), ["7 failures", "3 still running"]);
});

test("everything still running is caught before the fit", () => {
  const m = { ...EMPTY_MAPPING, x: "Operating Hours", c: "Status", c_map: { Failed: 1, Running: 1 } };
  assert.deepEqual(dataStepProblems(m, facts, 21), [
    "No row is marked failed, so there is nothing to fit. Check what each status means.",
  ]);
});

test("no status column: every row is a failure; a count column defers to the file", () => {
  const m = { ...EMPTY_MAPPING, x: "Operating Hours" };
  assert.deepEqual(statusSummary(m, facts, 21), { failed: 21, running: 0, left: 0, interval: 0 });
  assert.equal(statusSummary({ ...m, n: "Site" }, facts, 21), null);
  assert.equal(statusSummary({ ...EMPTY_MAPPING, xl: "a", xr: "b" }, facts, 21), null);
});

test("the interval pair must come together", () => {
  const m = { ...EMPTY_MAPPING, xl: "Operating Hours" };
  assert.match(dataStepProblems(m, facts, 21)[0], /both the earliest and the latest/);
  assert.match(dataStepProblems(EMPTY_MAPPING, facts, 21)[0], /Pick the column that holds the time/);
});

test("simple pastes are recognised by their columns", () => {
  assert.equal(isSimplePaste(["time"]), true);
  assert.equal(isSimplePaste(["time", "censored"]), true);
  assert.equal(isSimplePaste(["hours", "censored"]), false);
});

test("columnFacts reads a dtype from the preview when the server sends none", () => {
  const f = columnFacts({ columns: ["a", "b"], preview: [[1, "x"], [2, "y"]] });
  assert.equal(f.a.dtype, "float64");
  assert.equal(f.b.dtype, "object");
  assert.equal(f.a.values, null);
});

test("the file split reads words through the map, weighted by a count", async () => {
  const file = { text: async () => "t,Status,n\n100,Failed,2\n200,running,3\n,Failed,9\n" };
  const m = { ...EMPTY_MAPPING, x: "t", c: "Status", n: "n", c_map: { Failed: 0, Running: 1 } };
  assert.deepEqual(await dataSplit(file, m), { failed: 2, running: 3, other: 0 });
  const codes = { text: async () => "t,c\n1,1\n2,0\n3,-1\n" };
  assert.deepEqual(await dataSplit(codes, { ...EMPTY_MAPPING, x: "t", c: "c", c_invert: true }), { failed: 1, running: 1, other: 1 });
  assert.equal(await dataSplit(file, { ...m, c_map: { Failed: 0 } }), null);
});

test("a failure-mode column without a status one: a blank mode is still running (#177)", () => {
  const f = columnFacts({ ...PUMPS, columns: [...PUMPS.columns, "Mode"], blanks: [0, 0, 0, 0, 6],
                          dtypes: [...PUMPS.dtypes, "str"], n_unique: [...PUMPS.n_unique, 3],
                          values: [...PUMPS.values, { seal: 9, bearing: 6 }] });
  const m = { ...EMPTY_MAPPING, x: "Operating Hours", e: "Mode" };
  assert.deepEqual(statusSummary(m, f, 21), { failed: 15, running: 6, left: 0, interval: 0 });
  assert.deepEqual(dataStepProblems(m, f, 21), []);
  assert.match(dataStepProblems({ ...m, tl: "Operating Hours" }, f, 21)[0], /one time per unit/);
});

// ---- #434: a home for every column, and no decimals as counts ------------------

// The first-run upload: a time, a usage figure with decimals, a cost, an id.
const RAW = {
  columns: ["col 1", "col 2", "cost", "serial"],
  preview: [[300, 544966.3125, 12.5, "A-1"], [410, 612000.5, 9, "A-2"]],
  n_rows: 4,
  n_unique: [4, 4, 4, 4],
  dtypes: ["int64", "float64", "float64", "str"],
  blanks: [0, 0, 0, 0],
  values: [null, null, null, null],
  whole: [true, false, false, null],
};
const rawFacts = columnFacts(RAW);

test("a column of decimals can't be a count, and the reason shows before the fit", () => {
  assert.equal(countProblem(rawFacts["col 1"]), null);
  assert.equal(countProblem(rawFacts["col 2"]), "decimals");
  assert.equal(countProblem(rawFacts.serial), "text");
  assert.equal(rawFacts["col 2"].decimal, 544966.3125);
  const problems = dataStepProblems({ ...EMPTY_MAPPING, x: "col 1", n: "col 2" }, rawFacts, 4);
  assert.equal(problems.length, 1);
  assert.match(problems[0], /“col 2” holds decimals \(e\.g\. “544966\.3125”\), so it can't be a count/);
  // A whole-number count is fine; without the server's word, a decimal in the preview tells.
  assert.deepEqual(dataStepProblems({ ...EMPTY_MAPPING, x: "col 2", n: "col 1" }, rawFacts, 4), []);
  const older = columnFacts({ ...RAW, whole: undefined });
  assert.equal(countProblem(older["col 2"]), "decimals");
  assert.equal(countProblem(older["col 1"]), null);
});

test("the guess never maps a decimal column as the count", () => {
  const f = columnFacts({ ...RAW, columns: ["hours", "count"], preview: [[1, 1.5]], dtypes: ["int64", "float64"],
                          whole: [true, false], blanks: [0, 0], values: [null, null], n_unique: [4, 4] });
  assert.equal(guessMapping(["hours", "count"], f).mapping.n, "");
});

test("every column has a role, and ignoring one frees it", () => {
  const mapping = { ...EMPTY_MAPPING, x: "col 1" };
  assert.deepEqual(columnRoles(RAW.columns, mapping, ["cost"]), { "col 1": "x", "col 2": "", cost: "cov", serial: "" });
  // Give col 2 the time: col 1 is ignored now (one column per role).
  let next = assignRole(mapping, ["cost"], "col 2", "x", rawFacts);
  assert.equal(next.mapping.x, "col 2");
  assert.deepEqual(columnRoles(RAW.columns, next.mapping, next.covariates), { "col 1": "", "col 2": "x", cost: "cov", serial: "" });
  // A covariate ignored, then a mapped column made a covariate.
  next = assignRole(next.mapping, next.covariates, "cost", "", rawFacts);
  assert.deepEqual(next.covariates, []);
  next = assignRole(next.mapping, next.covariates, "col 2", "cov", rawFacts);
  assert.equal(next.mapping.x, "");
  assert.deepEqual(next.covariates, ["col 2"]);
  // The interval pair and the single time exclude each other, as in the fields.
  next = assignRole({ ...EMPTY_MAPPING, x: "col 1" }, [], "col 2", "xl", rawFacts);
  assert.equal(next.mapping.x, "");
  assert.equal(next.mapping.xl, "col 2");
});

test("a status column picked as a role gets its guessed meanings", () => {
  const next = assignRole({ ...EMPTY_MAPPING, x: "Operating Hours" }, [], "Status", "c", facts);
  assert.deepEqual(next.mapping.c_map, { Failed: 0, Running: 1 });
  const cleared = assignRole(next.mapping, [], "Status", "", facts);
  assert.equal(cleared.mapping.c, "");
  assert.equal(cleared.mapping.c_map, null);
});

test("the summary says what's used and what's ignored", () => {
  const roles = columnRoles(RAW.columns, { ...EMPTY_MAPPING, x: "col 1" }, []);
  assert.deepEqual(roleSummary(roles), { used: [{ col: "col 1", role: "x" }], ignored: ["col 2", "cost", "serial"] });
  assert.equal(roleLabel("x"), "Time to failure");
  assert.equal(roleLabel("xl", "intervals"), "Start of the row");
});

test("covariates are offered only where the model takes them; Ignore always", () => {
  assert.deepEqual(roleChoices(), ["x", "c", "n", "xl", "xr", "tl", "tr", ""]);
  assert.deepEqual(roleChoices({ covariates: true, failureMode: true }),
                   ["x", "c", "n", "xl", "xr", "tl", "tr", "e", "cov", ""]);
  assert.deepEqual(roleChoices({ timeVarying: "intervals", covariates: true }), ["i", "xl", "xr", "c", "cov", ""]);
  for (const opts of [{}, { covariates: true }, { timeVarying: "timeline" }]) {
    assert.equal(roleChoices(opts).at(-1), "");
  }
});
