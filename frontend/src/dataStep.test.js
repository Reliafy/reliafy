// Run with: node --test src/
// The Data step's one table (DataMapper): the first reading of the walkthrough
// sheets, the "Read as" line, issues by column, and the same fit request as
// before for the same mapping.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MAPPING, columnFacts, dataQuestions, dataStepIssues, dataStepNotes, dataStepProblems, guessUnitNames,
  keptChoices, mappingFields, readAsParts, roleGroups, rolesOf, setRole, startingMapping, statusSummary,
} from "./lifeData.js";
import { unitNoun } from "./datasetGuess.js";
import { SHEETS } from "./dataStepSheets.js";

const start = (name, saved = null) => {
  const csv = SHEETS[name];
  const facts = columnFacts(csv);
  const g = startingMapping(saved, csv.columns, facts, csv.n_rows);
  const idColumn = guessUnitNames(csv.columns, facts, csv.n_rows, g.mapping);
  return { csv, facts, ...g, idColumn };
};
const readAs = ({ csv, facts, mapping, unit, idColumn }, inspection = false) => readAsParts({
  mapping, facts, nRows: csv.n_rows, unit, idColumn, inspection,
  summary: inspection ? null : statusSummary(mapping, facts, csv.n_rows),
}).join(" · ");
const clean = (s) => dataStepIssues(s.mapping, s.facts, s.csv.n_rows, s.unit).length === 0
  && dataQuestions(s.mapping, s.facts, s.csv.columns, s.csv.n_rows).length === 0;

test("the seal sheet: Status is failed / running and Failure mode the mode, blanks on running rows fine", () => {
  const s = start("seals");
  assert.equal(s.mapping.x, "Hours");
  assert.equal(s.mapping.c, "Status");
  assert.deepEqual(s.mapping.c_map, { Running: 1, Failed: 0 });
  assert.equal(s.mapping.e, "Failure mode");
  assert.equal(s.unit, "Hours");
  assert.equal(s.idColumn, "Seal");
  assert.ok(clean(s), "nothing to settle");
  assert.equal(readAs(s), "80 seals · 37 failed (22 Wear, 15 Installation) · 43 still running · times in hours");
});

test("a saved reading that no longer reads cleanly gives way to a fresh guess", () => {
  // The screenshot's state: the mode column kept as the status, its meanings lost.
  const stale = { mapping: { x: "Hours", c: "Failure mode" }, options: {}, unit: "Hours", model_name: "Seal wear" };
  const s = start("seals", stale);
  assert.equal(s.from, null);
  assert.equal(s.mapping.c, "Status");
  assert.equal(s.mapping.e, "Failure mode");
  // A saved reading that does read cleanly is kept, and says where it came from.
  const good = {
    mapping: { x: "Hours", c: "Failure mode" }, options: { c_map: { Wear: 0, Installation: 1, "": 1 } },
    unit: "Hours", model_name: "Wear only",
  };
  const k = start("seals", good);
  assert.equal(k.from, "Wear only");
  assert.deepEqual(k.mapping.c_map, { Wear: 0, Installation: 1, "": 1 });
});

test("the walkthrough sheets read as their owners meant", () => {
  assert.equal(readAs(start("w01")), "34 seals · 19 failed · 15 still running · times in hours");
  assert.equal(readAs(start("w11")), "60 bearings · 35 failed · 25 still running · times in hours");
  assert.equal(readAs(start("w11coded")), "60 bearings · 35 failed · 25 still running · times in hours");
  assert.equal(readAs(start("w12wear")),
    "80 seals · 37 failed (22 Wear, 15 Installation) · 43 still running · times in hours");
  for (const name of ["w01", "w11", "w11coded", "w12wear", "w13"]) assert.ok(clean(start(name)), name);
});

test("W02: Failed (1=yes) is read 1 = failed, the Units column converts the day rows, the blank row is named on its column", () => {
  const s = start("w02");
  assert.equal(s.mapping.c, "Failed (1=yes)");
  assert.equal(s.mapping.c_invert, true);
  assert.equal(s.mapping.u, "Units");
  const issues = dataStepIssues(s.mapping, s.facts, s.csv.n_rows, s.unit);
  assert.deepEqual(issues.map((i) => i.col), ["Time in service", "Failed (1=yes)"]);
  assert.match(readAs(s), /times in hours · 4 rows converted from days · 1 = failed, 0 = still running/);
});

test("W13: inspection times, the status words and the late-entry column are all read", () => {
  const s = start("w13");
  assert.equal(s.mapping.xl, "Last good check (h)");
  assert.equal(s.mapping.xr, "Found failed at (h)");
  assert.equal(s.mapping.tl, "Entered at (h)");
  assert.equal(s.mapping.c, "Status");
  assert.equal(s.mapping.x, "");
  assert.match(readAs(s), /times in hours · 20 entered late$/);
});

test("issues name their column; one about no column has none", () => {
  const facts = columnFacts(SHEETS.seals);
  const none = dataStepIssues({ ...EMPTY_MAPPING }, facts, 80);
  assert.deepEqual(none, [{ col: null, text: "Pick the column that holds the time to failure or removal." }]);
  const m = { ...EMPTY_MAPPING, x: "Hours", c: "Failure mode" };
  const issues = dataStepIssues(m, facts, 80);
  assert.ok(issues.length >= 2 && issues.every((i) => i.col === "Failure mode"));
  assert.deepEqual(dataStepProblems(m, facts, 80), issues.map((i) => i.text));
});

test("each column has one role, set in its heading: a role moves, the id is words only", () => {
  const s = start("seals");
  let state = { mapping: s.mapping, covariates: [], idColumn: s.idColumn };
  assert.deepEqual(rolesOf(s.csv.columns, state.mapping, [], state.idColumn),
    { Seal: "id", Hours: "x", Status: "c", "Failure mode": "e" });
  // Failure mode as the status: Status loses it, and the meanings are guessed afresh.
  state = setRole(state, "Failure mode", "c", s.facts);
  assert.equal(state.mapping.c, "Failure mode");
  assert.equal(state.mapping.e, "");
  assert.deepEqual(rolesOf(s.csv.columns, state.mapping, [], state.idColumn).Status, "");
  // A covariate, then ignored.
  state = setRole(state, "Status", "cov", s.facts);
  assert.deepEqual(state.covariates, ["Status"]);
  state = setRole(state, "Status", "", s.facts);
  assert.deepEqual(state.covariates, []);
  // The id moves to another column, and the old one is ignored.
  state = setRole(state, "Hours", "id", s.facts);
  assert.equal(state.idColumn, "Hours");
  assert.equal(state.mapping.x, "");
  // Never sent: the request carries no id.
  assert.ok(!mappingFields(state.mapping).some(([k]) => k === "id"));
});

test("the role list keeps every role the old screen had, the usual ones first", () => {
  const g = roleGroups({ covariates: true, failureMode: true });
  assert.deepEqual(g.common, ["", "id", "x", "c", "e", "cov"]);
  assert.deepEqual(g.more, ["n", "xl", "xr", "tl", "tr", "u"]);
  assert.deepEqual(roleGroups({ timeVarying: "intervals" }).common, ["", "i", "xl", "xr", "c"]);
  assert.deepEqual(roleGroups({ timeVarying: "timeline", covariates: true }).common, ["", "i", "x", "c", "cov"]);
});

// What the fit request carried for each sheet before this screen (the old
// Data step's first reading, from dev's guessMapping). The new screen sends
// the same fields for the same mapping.
const BEFORE = {
  seals: [["x", "Hours"], ["c", "Status"], ["e", "Failure mode"], ["c_invert", "0"], ["c_map", '{"Running":1,"Failed":0}']],
  w01: [["x", "Run hours"], ["c", "Status"], ["c_invert", "0"], ["c_map", '{"Failed":0,"Running":1}']],
  w02: [["u_col", "Units"], ["x", "Time in service"], ["c", "Failed (1=yes)"], ["c_invert", "1"]],
  w11: [["x", "Run hours"], ["c", "Status"], ["c_invert", "0"], ["c_map", '{"Failed":0,"Removed, OK":1}']],
  w11coded: [["x", "Run hours"], ["c", "Status"], ["c_invert", "0"], ["c_map", '{"Failed":0,"Removed, OK":1}']],
  w12wear: [["x", "Hours"], ["c", "Status"], ["e", "Failure mode"], ["c_invert", "0"], ["c_map", '{"Running":1,"Failed":0}']],
  w13: [["c", "Status"], ["xl", "Last good check (h)"], ["xr", "Found failed at (h)"], ["c_invert", "0"],
    ["c_map", '{"Found failed":0,"OK at last check":1}']],
};

test("the same mapping sends the same fit request as before", () => {
  for (const [name, fields] of Object.entries(BEFORE)) {
    const s = start(name);
    const sent = mappingFields(s.mapping);
    if (name === "w02fixed") continue; // an intended change: see the W02 test
    if (name === "w13") {
      // The one intended change: the late-entry column is now guessed.
      assert.deepEqual(sent.filter(([k]) => k !== "tl"), fields, name);
      assert.deepEqual(sent.find(([k]) => k === "tl"), ["tl", "Entered at (h)"]);
    } else {
      assert.deepEqual(sent, fields, name);
    }
  }
});

test("picking each column's role by hand rebuilds the same request", () => {
  for (const name of Object.keys(SHEETS)) {
    const s = start(name);
    const roles = rolesOf(s.csv.columns, s.mapping, [], s.idColumn);
    let state = { mapping: { ...EMPTY_MAPPING }, covariates: [], idColumn: "" };
    for (const col of s.csv.columns) if (roles[col]) state = setRole(state, col, roles[col], s.facts);
    assert.deepEqual(mappingFields(state.mapping), mappingFields(s.mapping), name);
    assert.equal(state.idColumn, s.idColumn, name);
  }
});

test("units are named from the column that names them", () => {
  assert.equal(unitNoun("Seal"), "seals");
  assert.equal(unitNoun("Seal ID"), "seals");
  assert.equal(unitNoun("Idler No."), "idlers");
  assert.equal(unitNoun("Pump tag"), "pumps");
  assert.equal(unitNoun("Battery"), "batteries");
  assert.equal(unitNoun("Serial number"), "units");
  assert.equal(unitNoun(""), "units");
  assert.equal(unitNoun("Seal", 1), "seal");
});

test("W02 fixed: the time column that names its unit wins, and the Units column (the other time's) is left alone", () => {
  const s = start("w02fixed");
  assert.equal(s.mapping.x, "Hours in service");
  assert.equal(s.mapping.u, "");
  assert.equal(s.unit, "Hours");
  assert.equal(dataQuestions(s.mapping, s.facts, s.csv.columns, s.csv.n_rows).length, 0);
  // The original sheet, with no unit in its time column's name, still converts by Units.
  assert.equal(start("w02").mapping.u, "Units");
});

test("a corrected copy of the same file keeps the choices made on the first", () => {
  const first = start("w02");
  const chosen = { mapping: { ...first.mapping, c_invert: false }, unit: "Hours", covariates: [], idColumn: "Idler No." };
  const kept = keptChoices(chosen, SHEETS.w02fixed.columns);
  assert.equal(kept.mapping.x, "Time in service");
  assert.equal(kept.mapping.c_invert, false);
  assert.equal(kept.idColumn, "Idler No.");
  // A file without a column the choices use starts afresh.
  assert.equal(keptChoices(chosen, SHEETS.seals.columns), null);
  assert.equal(keptChoices(null, SHEETS.w02.columns), null);
});

test("wholly blank rows are said to be skipped, and times of 0 or less are noted on the time column", () => {
  const s = start("seals");
  const parts = readAsParts({ mapping: s.mapping, facts: s.facts, nRows: 80, unit: "Hours",
    summary: statusSummary(s.mapping, s.facts, 80), idColumn: "Seal", blankRows: 1 });
  assert.equal(parts[parts.length - 1], "1 blank row skipped");
  const facts = columnFacts({ ...SHEETS.seals, nonpositive: [null, 2, null, null] });
  const notes = dataStepNotes(s.mapping, facts);
  assert.equal(notes.length, 1);
  assert.equal(notes[0].col, "Hours");
  assert.match(notes[0].text, /^2 rows have a time of 0 or less in “Hours”/);
  // A note, not a problem: Kaplan-Meier still fits them.
  assert.equal(dataStepIssues(s.mapping, facts, 80, "Hours").length, 0);
});

test("inspection data never offers every row is a failure", () => {
  const csv = SHEETS.w13;
  const facts = columnFacts(csv);
  const m = { ...EMPTY_MAPPING, xl: "Last good check (h)", xr: "Found failed at (h)" };
  const q = dataQuestions(m, facts, csv.columns, csv.n_rows).find((x) => x.id === "status:Status");
  assert.equal(q.no, "No: a blank “Found failed at (h)” is a unit still running");
});

test("a saved reading of rows whose covariates change over time keeps its item column", () => {
  const cols = ["pump", "start_h", "stop_h", "censored", "load_pct"];
  const saved = { mapping: { i: "pump", xl: "start_h", xr: "stop_h", c: "censored" }, options: {}, unit: "Hours" };
  const facts = columnFacts({ columns: cols, dtypes: ["str", "int64", "int64", "int64", "int64"],
    blanks: [0, 0, 0, 0, 0], values: [null, null, null, { 0: 25, 1: 71 }, null], n_rows: 96 });
  const kept = startingMapping(saved, cols, facts, 96);
  assert.equal(kept.mapping.i, "pump");
  assert.ok(kept.from);
});
