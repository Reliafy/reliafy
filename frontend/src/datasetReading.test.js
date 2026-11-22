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
  readingNotes, readingParts, readingPayload, readingText, readingWaiting, setRole, toggleZ, withoutColumn, zLine,
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
    "x = Cumulative Operating Age at Failure or End (h) · c = Life Record Status (Failed / Right-censored) · "
    + "i = Equipment Tag · failure mode = Failure Mode · s = Duty · Z: Site");
});

test("x and c are required, each said beside its selector", () => {
  const f = columnFacts(PLANT);
  const none = { ...emptyReading() };
  assert.deepEqual(readingIssues(none, f, 40).map((i) => i.row), ["x"]);
  // A failure-mode column with no status column says it itself (a blank mode is still running).
  const modesOnly = { ...guess(PLANT), c: "", c_map: null };
  assert.deepEqual(readingIssues(modesOnly, f, 40), []);
  assert.match(readingText(modesOnly), /c = none: a blank failure mode is still running/);
  const noC = { ...modesOnly, e: "" };
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

test("the x line doesn't repeat a unit the column name already carries", () => {
  const x = (r) => readingParts({ ...emptyReading(), ...r }).find((p) => p.key === "x").value;
  assert.equal(x({ x: "Age", unit: "Hours" }), "Age (hours)");
  assert.equal(x({ x: "Age (h)", unit: "Hours" }), "Age (h)");
});

test("pasted values carry their own reading: no columns to ask about", async () => {
  const { pastedReading } = await import("./datasetReading.js");
  const { parsePastedValues } = await import("./lifeData.js");
  const two = pastedReading(parsePastedValues("1200 0\n1850 0\n2000 1\n"));
  assert.equal(two.x, "time");
  assert.equal(two.c, "censored");
  assert.equal(two.c_invert, false);
  assert.equal(two.all_failed, false);
  assert.equal(two.unit, "");
  const one = pastedReading(parsePastedValues("1200\n1850\n2000\n"));
  assert.equal(one.x, "time");
  assert.equal(one.c, "");
  assert.equal(one.all_failed, true);
});

// A status column of words, one of them not yet given a meaning.
const LIVES = {
  columns: ["Controller", "Hours", "Status"],
  preview: [["Site 01-1", 10152, "Running"], ["Site 02-1", 10152, "Running"]],
  n_rows: 63, dtypes: ["object", "int64", "object"], blanks: [0, 0, 0],
  values: [null, null, { Running: 60, Failed: 2, "Removed - wiring fault": 1 }],
  n_unique: [63, 20, 3], whole: [null, true, null],
};

test("Save waits with the note itself, beside the selector it sits by", () => {
  const f = columnFacts(LIVES);
  const r = guessReading(LIVES.columns, f, LIVES.n_rows);
  const issues = readingIssues(r, f, LIVES.n_rows);
  assert.deepEqual(issues.map((i) => i.row), ["c"]);
  // Not "the note beside x": the status column's own note, named in full.
  assert.equal(readingWaiting(r, f, LIVES.n_rows),
    "Say whether “Removed - wiring fault” means failed or still running (beside c).");
  const settled = { ...r, c_map: { ...r.c_map, "Removed - wiring fault": 1 } };
  assert.equal(readingWaiting(settled, f, LIVES.n_rows), null);
  // Two notes: the first, and how many more.
  assert.match(readingWaiting({ ...r, x: "", all_failed: false }, f, LIVES.n_rows), /^Pick x: .* \(beside x\)\.$/);
});

// Inspection data (a range on some rows) with a failure-mode column.
const RETURNS = {
  columns: ["serial", "age_months", "last_ok_months", "found_failed_months", "status", "mode"],
  preview: [["PC2-10001", 28, null, null, "Running", null], ["PC2-10002", null, 6, 12, "Failed", "solder"]],
  n_rows: 600, dtypes: ["object", "float64", "float64", "float64", "object", "object"], blanks: [0, 20, 580, 580, 0, 501],
  values: [null, null, null, null, { Running: 501, Failed: 99 }, { solder: 60, capacitor: 39 }],
  n_unique: [600, 50, 10, 10, 2, 2], whole: [null, true, true, true, null, null],
};

test("a dataset keeps failure modes beside ranges: a note, not a block", () => {
  const f = columnFacts(RETURNS);
  const r = { ...emptyReading(), x: "age_months", xl: "last_ok_months", xr: "found_failed_months", c: "status",
    c_map: { Running: 1, Failed: 0 }, e: "mode", unit: "Months" };
  assert.deepEqual(readingIssues(r, f, RETURNS.n_rows), []);
  assert.equal(readingWaiting(r, f, RETURNS.n_rows), null);
  assert.equal(readingNotes(r).length, 1);
  assert.equal(readingNotes(r)[0].row, "e");
  assert.deepEqual(readingNotes({ ...r, xl: "", xr: "" }), []);
});

// A replacement log of one fleet: a date, the fleet's hours, the set it was
// on (a few values), the part and the reason. The date is never the item.
const FLEET_LOG = {
  columns: ["replacement", "date", "fleet_hours", "genset", "part", "reason"],
  n_rows: 48,
  preview: [[1, "2023-12-01", 191, "GS-09", "FLP-20 fuel lift pump", "failed in service"]],
  dtypes: ["int64", "str", "int64", "str", "str", "str"],
  n_unique: [48, 47, 48, 12, 1, 1],
  blanks: [0, 0, 0, 0, 0, 0],
  values: [null, null, null, { "GS-01": 4, "GS-02": 4, "GS-09": 5 }, { "FLP-20 fuel lift pump": 48 },
    { "failed in service": 48 }],
  whole: [true, null, true, null, null, null],
};

test("a date column is never guessed as the item", () => {
  const r = guess(FLEET_LOG);
  assert.equal(r.x, "fleet_hours");
  assert.equal(r.i, "");
  assert.ok(r.not_used.includes("date"));
});

test("every row as one stream: said on purpose, cleared by picking an item", () => {
  const facts = columnFacts(FLEET_LOG);
  const r = { ...guess(FLEET_LOG), one_stream: true };
  assert.equal(missingFor("repairable", r), null);
  assert.match(missingFor("repairable", { ...r, one_stream: false }), /one stream/);
  assert.deepEqual(readingParts(r).find((p) => p.key === "i"), { key: "i", label: "i", value: "none: every row is one stream" });
  assert.equal(setRole(r, "i", "genset", facts, FLEET_LOG.n_rows).one_stream, false);
  assert.equal(readingPayload(r).one_stream, true);
});

test("the end of record is kept on the reading and shown on its summary", () => {
  assert.equal(emptyReading().record_end, null);
  const r = { ...emptyReading(), x: "fleet_hours", all_failed: true, one_stream: true, unit: "Hours", record_end: 216000 };
  const part = readingParts(r).find((p) => p.key === "record_end");
  assert.equal(part.label, "record ends at");
  assert.match(part.value, /216,000 hours/);
  assert.ok(readingText(r).includes("record ends at = 216,000 hours"));
  // A column of ends (tr) says it instead; with none, nothing is shown.
  assert.equal(readingParts({ ...r, tr: "ends" }).some((p) => p.key === "record_end"), false);
  assert.equal(readingParts({ ...r, record_end: null }).some((p) => p.key === "record_end"), false);
});
