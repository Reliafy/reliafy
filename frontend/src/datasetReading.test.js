// Run with: node --test src/
// A dataset's modelling reading (datasetReading.js): the first guess (shared
// with the server: readingGuessCases.json), Z and its guard, x and c required,
// the split column, older datasets, and the same fit request as the Data step
// made for the same columns.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SHEETS } from "./dataStepSheets.js";
import { FAMILY_SHEETS } from "./dataStepFamilySheets.js";
import { columnFacts, mappingFields, startingMapping } from "./lifeData.js";
import {
  datasetReading, emptyReading, fitFromReading, guessReading, itemRows, missingFor, notUsedReason, readingIssues,
  readingParts, readingPayload, readingText, setRole, toggleZ, withoutColumn, zLine,
} from "./datasetReading.js";

const CASES = JSON.parse(readFileSync(new URL("./readingGuessCases.json", import.meta.url), "utf8"));
const guess = (sheet) => guessReading(sheet.columns, columnFacts(sheet), sheet.n_rows);

// A sheet shaped like a plant's life records (an id, a tag, a class, a status
// in words, an age with its unit in the header, a failure mode, remarks, a
// commissioning date, a site and a duty), as /api/columns describes it.
const PLANT = {
  columns: ["ID", "Equipment Tag", "Equipment Class / Family", "Life Record Status (Failed / Right-censored)",
    "Cumulative Operating Age at Failure or End (h)", "Failure Mode", "Remarks", "Commissioning date", "Site",
    "Duty", "Load (kN)", "Plant"],
  n_rows: 40,
  preview: [["R001", "U1-BFP-01", "Boiler feed pump", "Right-censored", 11440, null, "Ran clean all season", "2019-03-01",
    "North", "Base", 12.5, "Unit 1"]],
  dtypes: ["str", "str", "str", "str", "int64", "str", "str", "str", "str", "str", "float64", "str"],
  n_unique: [40, 40, 3, 2, 40, 4, 35, 9, 2, 2, 31, 1],
  blanks: [0, 0, 0, 0, 0, 26, 0, 0, 0, 0, 0, 0],
  values: [null, null, { "Boiler feed pump": 20, "Coal mill": 12, Transformer: 8 },
    { "Right-censored": 26, Failed: 14 }, null, { "Mechanical seal leak": 6, Bearing: 4, Winding: 2, Liner: 2 },
    null, { "2019-03-01": 10 }, { North: 22, South: 18 }, { Base: 30, Peak: 10 }, null, { "Unit 1": 40 }],
  whole: [null, null, null, null, true, null, null, null, null, null, false, null],
};

test("the first reading of every walkthrough sheet is the one the server guesses too", () => {
  for (const [name, sheet] of Object.entries({ ...SHEETS, ...FAMILY_SHEETS })) {
    assert.deepEqual(guess(sheet), CASES[name], name);
  }
});

test("Z is every column not used as something else, less ids, dates, free text and one-value columns", () => {
  const r = guess(PLANT);
  assert.equal(r.x, "Cumulative Operating Age at Failure or End (h)");
  assert.equal(r.unit, "Hours");
  assert.equal(r.c, "Life Record Status (Failed / Right-censored)");
  assert.deepEqual(r.c_map, { "Right-censored": 1, Failed: 0 });
  assert.equal(r.e, "Failure Mode");
  assert.equal(r.i, "Equipment Tag");
  assert.deepEqual(r.z, ["Equipment Class / Family", "Site", "Duty", "Load (kN)"]);
  assert.deepEqual(r.not_used, ["ID", "Remarks", "Commissioning date", "Plant"]);
  assert.equal(zLine(r), "Z: Equipment Class / Family, Site, Duty, Load (kN) (4 covariates) · not used: ID, Remarks, "
    + "Commissioning date, Plant");
  const f = columnFacts(PLANT);
  assert.equal(notUsedReason("Remarks", f.Remarks, 40), "free text");
  assert.equal(notUsedReason("Commissioning date", f["Commissioning date"], 40), "a date");
  assert.equal(notUsedReason("ID", f.ID, 40), "an id");
  assert.equal(notUsedReason("Plant", f.Plant, 40), "one value");
  assert.equal(notUsedReason("Site", f.Site, 40), null);
  // One tap includes a guarded column, and leaves a covariate out.
  const inc = toggleZ(r, "Remarks");
  assert.ok(inc.z.includes("Remarks") && !inc.not_used.includes("Remarks"));
  assert.ok(toggleZ(inc, "Remarks").not_used.includes("Remarks"));
});

test("a column given a role leaves Z, and comes back by the guard when it's freed", () => {
  const f = columnFacts(PLANT);
  const r = guess(PLANT);
  const s = setRole(r, "s", "Duty", f, 40);
  assert.equal(s.s, "Duty");
  assert.ok(!s.z.includes("Duty"));
  const back = setRole(s, "s", "", f, 40);
  assert.ok(back.z.includes("Duty"));
  // A column moved to another role leaves its first one.
  const moved = setRole(r, "n", "Load (kN)", f, 40);
  assert.equal(moved.n, "Load (kN)");
  const tagAsX = setRole(r, "tl", "Equipment Tag", f, 40);
  assert.equal(tagAsX.i, "");
  assert.equal(readingText({ ...s, z: ["Site"] }),
    "x = Cumulative Operating Age at Failure or End (h) (hours) · c = Life Record Status (Failed / Right-censored) · "
    + "i = Equipment Tag · failure mode = Failure Mode · s = Duty · Z: Site");
});

test("x and c are required, each said beside its selector", () => {
  const f = columnFacts(PLANT);
  const none = { ...emptyReading() };
  assert.deepEqual(readingIssues(none, f, 40).map((i) => i.row), ["x"]);
  const noC = { ...guess(PLANT), c: "", c_map: null };
  const issues = readingIssues(noC, f, 40);
  assert.deepEqual(issues.map((i) => i.row), ["c"]);
  assert.match(issues[0].text, /every row failed/);
  // "Every row failed", said on purpose, is an answer; so is a range or a table of readings.
  assert.deepEqual(readingIssues({ ...noC, all_failed: true }, f, 40), []);
  const w19 = guess(FAMILY_SHEETS.w19);
  assert.equal(w19.m, "thickness_mm");
  assert.deepEqual(readingIssues(w19, columnFacts(FAMILY_SHEETS.w19), FAMILY_SHEETS.w19.n_rows)
    .filter((i) => i.row === "c"), []);
  assert.equal(readingIssues(guess(SHEETS.w13), columnFacts(SHEETS.w13), SHEETS.w13.n_rows).length, 0);
});

test("a split: the dataset column has no role in any part, and comes back unsplit", () => {
  const f = columnFacts(PLANT);
  const r = guess(PLANT);
  const split = withoutColumn(r, "Equipment Class / Family", f, 40);
  assert.ok(!split.z.includes("Equipment Class / Family"));
  const other = withoutColumn(split, "Site", f, 40, "Equipment Class / Family");
  assert.ok(other.z.includes("Equipment Class / Family") && !other.z.includes("Site"));
  // A role on the split column is cleared (x then has to be picked again).
  assert.equal(withoutColumn(r, r.x, f, 40).x, "");
});

test("a reading saved at upload sends the same fit request as the Data step for the same sheet", () => {
  for (const [name, sheet] of Object.entries(SHEETS)) {
    const facts = columnFacts(sheet);
    const before = startingMapping(null, sheet.columns, facts, sheet.n_rows);
    // Saved, then read back by a fit flow: through the payload the server keeps.
    const saved = readingPayload(guess(sheet));
    const now = fitFromReading(saved, facts, sheet.n_rows);
    const fields = mappingFields(now.mapping);
    if (name === "window") {
      // The first guess now reads the observation window's end (tr), which the
      // Data step left to be picked by hand: the request then matches the hand-made one.
      assert.deepEqual(fields, [...mappingFields(before.mapping).slice(0, 3), ["tr", "Observed until (h)"],
        ...mappingFields(before.mapping).slice(3)], name);
    } else {
      assert.deepEqual(fields, mappingFields(before.mapping), name);
    }
    assert.equal(now.unit, before.unit, `${name} unit`);
    assert.equal(now.itemTimeline, false, name);
  }
});

test("an older dataset: its newest model's reading, else the guess, marked guessed", () => {
  const sheet = SHEETS.seals;
  const cols = { ...sheet, facts: columnFacts(sheet) };
  const fresh = datasetReading({ reading: null, reading_source: "guessed", last_mapping: null }, cols);
  assert.equal(fresh.source, "guessed");
  assert.equal(fresh.reading.c, "Status");
  const last = {
    mapping: { x: "Hours", c: "Failure mode" }, options: { c_map: { Wear: 0, Installation: 1, "": 1 } },
    unit: "Hours", model_name: "Wear only",
  };
  const kept = datasetReading({ reading: { x: "ignored" }, reading_source: "last_model", last_mapping: last }, cols);
  assert.equal(kept.source, "guessed");
  assert.equal(kept.from, "Wear only");
  assert.equal(kept.reading.c, "Failure mode");
  assert.deepEqual(kept.reading.c_map, { Wear: 0, Installation: 1, "": 1 });
  // Kept with the dataset: used as it is.
  const saved = datasetReading({ reading: { ...emptyReading(), x: "Hours", all_failed: true }, reading_source: "saved" },
    cols);
  assert.equal(saved.source, "saved");
  assert.equal(saved.reading.x, "Hours");
  // No status column, as fits read it before readings: every row failed.
  const bare = { columns: ["Hours"], n_rows: 3, dtypes: ["int64"], n_unique: [3], blanks: [0], values: [null] };
  const b = datasetReading({ reading_source: "guessed" }, { ...bare, facts: columnFacts(bare) });
  assert.equal(b.reading.all_failed, true);
  assert.deepEqual(readingIssues(b.reading, columnFacts(bare), 3), []);
});

test("start and stop rows: one life per item for a plain life model, the item kept for covariates over time", () => {
  const sheet = {
    columns: ["pump", "start_h", "stop_h", "failed", "load"], n_rows: 9,
    dtypes: ["str", "int64", "int64", "int64", "float64"], n_unique: [3, 7, 9, 2, 6], blanks: [0, 0, 0, 0, 0],
    values: [{ P1: 3, P2: 3, P3: 3 }, null, null, { 0: 6, 1: 3 }, null],
  };
  const facts = columnFacts(sheet);
  const r = guess(sheet);
  assert.equal(r.i, "pump");
  assert.equal(r.xl, "start_h");
  assert.equal(r.xr, "stop_h");
  assert.ok(itemRows(r, facts, 9));
  const f = fitFromReading(r, facts, 9);
  assert.equal(f.itemTimeline, true);
  assert.equal(f.mapping.i, "pump");
  assert.deepEqual(f.z, ["load"]);
  // An item column on a table of one row per unit is left out of a life fit.
  const plant = fitFromReading(guess(PLANT), columnFacts(PLANT), 40);
  assert.equal(plant.itemTimeline, false);
  assert.equal(plant.mapping.i, undefined);
});

test("a model kind that needs a role the reading lacks says so", () => {
  const r = guess(PLANT);
  assert.equal(missingFor("life", r), null);
  assert.match(missingFor("repairable", { ...r, i: "" }), /needs i/);
  assert.match(missingFor("degradation", { ...r, m: "" }), /m \(the measured value\)/);
  assert.deepEqual(readingParts({ ...emptyReading(), x: "Age", unit: "Hours", c: "Status", z: ["Load"] })
    .map((p) => p.key), ["x", "c", "z"]);
});
