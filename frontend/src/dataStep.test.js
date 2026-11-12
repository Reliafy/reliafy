// Run with: node --test src/
// The Data step's selectors (ColumnMapper: x with its range xl to xr, c, n,
// tl, failure mode): the first reading of the walkthrough sheets, where each
// issue is shown, and the same fit request as before for the same mapping.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  EMPTY_MAPPING, columnFacts, dataQuestions, dataStepIssues, dataStepNotes, dataStepProblems, issueRow,
  keptChoices, mappingFields, setMappingField, startingMapping, statusCodesOnly, statusSummary,
} from "./lifeData.js";
import { SHEETS } from "./dataStepSheets.js";

const start = (name, saved = null) => {
  const csv = SHEETS[name];
  const facts = columnFacts(csv);
  return { csv, facts, ...startingMapping(saved, csv.columns, facts, csv.n_rows) };
};
const counts = ({ csv, facts, mapping }) => {
  const s = statusSummary(mapping, facts, csv.n_rows);
  return s && `${s.failed} failed, ${s.running} running`;
};
const clean = (s) => dataStepIssues(s.mapping, s.facts, s.csv.n_rows, s.unit).length === 0
  && dataQuestions(s.mapping, s.facts, s.csv.columns, s.csv.n_rows).length === 0;

test("the seal sheet: Status is failed / running and Failure mode the mode, blanks on running rows fine", () => {
  const s = start("seals");
  assert.equal(s.mapping.x, "Hours");
  assert.equal(s.mapping.c, "Status");
  assert.deepEqual(s.mapping.c_map, { Running: 1, Failed: 0 });
  assert.equal(s.mapping.e, "Failure mode");
  assert.equal(s.unit, "Hours");
  assert.ok(clean(s), "nothing to settle");
  assert.equal(counts(s), "37 failed, 43 running");
  // Status holds words, so c shows how each was read (Failed → 0, Running → 1), not the 1 = failed tick.
  assert.equal(statusCodesOnly(s.facts.Status.values), false);
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
  assert.equal(counts(start("w01")), "19 failed, 15 running");
  assert.equal(counts(start("w11")), "35 failed, 25 running");
  assert.equal(counts(start("w11coded")), "35 failed, 25 running");
  assert.equal(counts(start("w12wear")), "37 failed, 43 running");
  for (const name of ["w01", "w11", "w11coded", "w12wear", "w13"]) assert.ok(clean(start(name)), name);
});

test("W02: Failed (1=yes) is read 1 = failed, the Units column converts the day rows, each issue sits by its selector", () => {
  const s = start("w02");
  assert.equal(s.mapping.c, "Failed (1=yes)");
  assert.equal(s.mapping.c_invert, true);
  assert.equal(s.mapping.u, "Units");
  // A 0/1 column: c shows "0 = failed, 1 = running" with "my column uses 1 = failed" ticked.
  assert.equal(statusCodesOnly(s.facts["Failed (1=yes)"].values), true);
  const issues = dataStepIssues(s.mapping, s.facts, s.csv.n_rows, s.unit);
  assert.deepEqual(issues.map((i) => i.col), ["Time in service", "Failed (1=yes)"]);
  assert.deepEqual(issues.map((i) => issueRow(i, s.mapping)), ["x", "c"]);
  assert.match(issues[0].text, /^1 row has no value in “Time in service”/);
});

test("W13: inspection ranges, the status words and the late-entry column are all read", () => {
  const s = start("w13");
  assert.equal(s.mapping.xl, "Last good check (h)");
  assert.equal(s.mapping.xr, "Found failed at (h)");
  assert.equal(s.mapping.tl, "Entered at (h)");
  assert.equal(s.mapping.c, "Status");
  assert.equal(s.mapping.x, "");
  assert.equal(s.unit, "Hours");
  assert.ok(clean(s));
});

test("each issue is shown beside the selector it concerns; one about no column beside x", () => {
  const facts = columnFacts(SHEETS.seals);
  const none = dataStepIssues({ ...EMPTY_MAPPING }, facts, 80);
  assert.deepEqual(none, [{ col: null, text: "Pick x: the column with the value when each unit failed or was removed." }]);
  assert.equal(issueRow(none[0], EMPTY_MAPPING), "x");
  const m = { ...EMPTY_MAPPING, x: "Hours", c: "Failure mode" };
  const issues = dataStepIssues(m, facts, 80);
  assert.ok(issues.length >= 2 && issues.every((i) => issueRow(i, m) === "c"));
  assert.deepEqual(dataStepProblems(m, facts, 80), issues.map((i) => i.text));
  const e = { ...EMPTY_MAPPING, x: "Hours", c: "Status", c_map: { Failed: 0, Running: 1 }, e: "Failure mode", tl: "Hours" };
  assert.deepEqual(dataStepIssues(e, facts, 80).map((i) => issueRow(i, e)), ["e"]);
});

test("the words never assume time: a column of volts is a value like any other", () => {
  const csv = {
    columns: ["Insulator", "Breakdown (kV)", "Broke down"], n_rows: 20, preview: [["IN-01", 41.5, "Yes"]],
    n_unique: [20, 20, 2], dtypes: ["str", "float64", "str"], blanks: [0, 0, 0],
    values: [null, null, { Yes: 14, No: 6 }], whole: [null, false, null],
  };
  const facts = columnFacts(csv);
  const m = { ...EMPTY_MAPPING, x: "Insulator" };
  assert.match(dataStepProblems(m, facts, 20)[0], /not numbers\. Pick the column with the values/);
  for (const t of [...dataStepProblems({ ...EMPTY_MAPPING }, facts, 20), ...dataStepProblems(m, facts, 20)]) {
    assert.doesNotMatch(t, /\btimes?\b/, t);
  }
  const v = { ...EMPTY_MAPPING, x: "Breakdown (kV)" };
  assert.deepEqual(dataStepProblems(v, facts, 20), []);
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

test("picking each selector by hand rebuilds the same request", () => {
  for (const name of Object.keys(SHEETS)) {
    const s = start(name);
    let m = { ...EMPTY_MAPPING };
    for (const f of ["x", "xl", "xr", "c", "n", "tl", "e"]) if (s.mapping[f]) m = setMappingField(m, f, s.mapping[f], s.facts);
    // The per-row unit column is set from its question ("Convert them?").
    if (s.mapping.u) m = { ...m, u: s.mapping.u };
    assert.deepEqual(mappingFields(m), mappingFields(s.mapping), name);
  }
});

test("x and a range together: x where filled, the range where x is blank, all sent", () => {
  const csv = SHEETS.mixed;
  const facts = columnFacts(csv);
  const g = startingMapping(null, csv.columns, facts, csv.n_rows);
  // The guess reads the range; picking x keeps it.
  assert.equal(g.mapping.xl, "Last good (cycles)");
  assert.equal(g.mapping.xr, "Found failed (cycles)");
  const m = setMappingField(g.mapping, "x", "Cycles", facts);
  assert.equal(m.xl, "Last good (cycles)");
  // Blanks in x are the range rows, not a problem.
  assert.deepEqual(dataStepIssues(m, facts, csv.n_rows, "Cycles"), []);
  const sent = mappingFields(m);
  assert.deepEqual(sent.filter(([k]) => ["x", "xl", "xr"].includes(k)),
    [["x", "Cycles"], ["xl", "Last good (cycles)"], ["xr", "Found failed (cycles)"]]);
  // Only one of the pair is a problem beside x.
  const half = { ...m, xr: "" };
  const issues = dataStepIssues(half, facts, csv.n_rows);
  assert.equal(issues[0].text, "Pick both xl and xr for the range, or neither.");
  assert.equal(issueRow(issues[0], half), "x");
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
  const chosen = { mapping: { ...first.mapping, c_invert: false }, unit: "Hours", covariates: [] };
  const kept = keptChoices(chosen, SHEETS.w02fixed.columns);
  assert.equal(kept.mapping.x, "Time in service");
  assert.equal(kept.mapping.c_invert, false);
  // A file without a column the choices use starts afresh.
  assert.equal(keptChoices(chosen, SHEETS.seals.columns), null);
  assert.equal(keptChoices(null, SHEETS.w02.columns), null);
});

test("values of 0 or less are noted beside x, without stopping the fit", () => {
  const s = start("seals");
  const facts = columnFacts({ ...SHEETS.seals, nonpositive: [null, 2, null, null] });
  const notes = dataStepNotes(s.mapping, facts);
  assert.equal(notes.length, 1);
  assert.equal(issueRow(notes[0], s.mapping), "x");
  assert.match(notes[0].text, /^2 rows have a value of 0 or less in “Hours”/);
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

test("tl and tr: the observation window is sent as the earlier screens sent it, beside its own selector", () => {
  const s = start("window");
  assert.equal(s.mapping.tl, "Entered at (h)");
  // tr is picked by hand; a blank tr on a row is no limit, so its blanks are fine.
  const m = setMappingField(s.mapping, "tr", "Observed until (h)", s.facts);
  assert.deepEqual(dataStepIssues(m, s.facts, s.csv.n_rows, "Hours"), []);
  assert.deepEqual(mappingFields(m), [
    ["x", "Hours"], ["c", "Status"], ["tl", "Entered at (h)"], ["tr", "Observed until (h)"],
    ["c_invert", "0"], ["c_map", '{"Failed":0,"Running":1}'],
  ]);
  // A text column as tr is a problem beside tr.
  const bad = { ...m, tr: "Pump" };
  const issues = dataStepIssues(bad, s.facts, s.csv.n_rows, "Hours");
  assert.equal(issues.length, 1);
  assert.equal(issueRow(issues[0], bad), "tr");
});
