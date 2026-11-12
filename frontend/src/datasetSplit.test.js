// Run with: node --test src/
// The Data step's "dataset" selector: one sheet split into several datasets by
// a column. Counts per dataset, blank values left out, problems per dataset
// beside their selector, and names that don't clash with saved datasets.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  blankWarning, countWords, groupCounts, parseCsv, splitNames, splitProblems, splitRoom, splitSheet, sourceStem,
} from "./datasetSplit.js";
import { statusMeaning } from "./lifeData.js";

// A sheet shaped like a joint industry template: one row per unit, the
// equipment class in its own column.
const SHEET = [
  "Tag,Equipment class,Hours,Status,Qty",
  "T-1,Transformer,1200,Failed,1",
  "M-1,Coal mill,300,Failed,2",
  "T-2,Transformer,4000,Running,1",
  "P-1,Boiler feed pump,,Failed,1",
  "M-2,Coal mill,450,Running,1",
  "X-1,,900,Failed,1",
  '"M-3, spare","Coal mill",610,Failed,1',
  ",,,,",
  "X-2,  ,100,Running,1",
  "P-2,Boiler feed pump,abc,Running,1",
].join("\r\n");

const lifeSpec = (mapping) => ({
  needs: [{ row: "x", col: mapping.x, range: [mapping.xl, mapping.xr].filter(Boolean) }],
  c: mapping.c, n: mapping.n, status: mapping.c ? (v) => statusMeaning(v, mapping) : null,
});
const MAPPING = { x: "Hours", c: "Status", n: "Qty", c_map: { Failed: 0, Running: 1 } };

test("CSV is read cell for cell, quotes and CRLF included; blank rows skipped", () => {
  const s = parseCsv(SHEET);
  assert.deepEqual(s.header, ["Tag", "Equipment class", "Hours", "Status", "Qty"]);
  assert.equal(s.rows.length, 9); // the row of commas alone is no row
  assert.deepEqual(s.rows[6], ["M-3, spare", "Coal mill", "610", "Failed", "1"]);
  assert.deepEqual(parseCsv('a,b\n"x ""y""",2').rows, [['x "y"', "2"]]);
});

test("each value its own dataset, in first-seen order; blank values left out and counted", () => {
  const { groups, blank } = splitSheet(parseCsv(SHEET), "Equipment class");
  assert.deepEqual(groups.map((g) => [g.value, g.rows.length]),
    [["Transformer", 2], ["Coal mill", 3], ["Boiler feed pump", 2]]);
  assert.equal(blank, 2); // X-1 and the whitespace-only X-2
  assert.equal(blankWarning(blank), "2 rows have no dataset name and are left out");
  assert.equal(blankWarning(1), "1 row has no dataset name and is left out");
  assert.equal(blankWarning(0), null);
  assert.deepEqual(splitSheet(parseCsv(SHEET), "Nope"), { groups: [], blank: 0 });
});

test("counts per dataset use the one mapping: c meanings and n for every dataset", () => {
  const sheet = parseCsv(SHEET);
  const { groups } = splitSheet(sheet, "Equipment class");
  const c = (g) => groupCounts(sheet.header, g.rows, lifeSpec(MAPPING));
  assert.deepEqual(c(groups[0]), { rows: 2, failed: 1, items: null });
  assert.deepEqual(c(groups[1]), { rows: 3, failed: 3, items: null }); // M-1 stands for 2 units
  assert.equal(countWords(c(groups[1])), "3 rows · 3 failed");
  // 1 = failed in the sheet: the flip applies to every dataset.
  const flipped = { x: "Hours", c: "Flag", c_invert: true };
  const coded = parseCsv("Class,Hours,Flag\nA,1,1\nA,2,0\nB,3,1\n");
  const parts = splitSheet(coded, "Class").groups;
  assert.deepEqual(parts.map((g) => groupCounts(coded.header, g.rows, lifeSpec(flipped)).failed), [1, 1]);
  // No c column: every row failed; a range row with no upper end is still running.
  const ranged = parseCsv("Class,Hours,Last good,Found failed\nA,10,,\nA,,5,8\nA,,5,\n");
  const r = groupCounts(ranged.header, ranged.rows, lifeSpec({ x: "Hours", xl: "Last good", xr: "Found failed" }));
  assert.equal(r.failed, 2);
  // Degradation: items, no failed count.
  const reads = parseCsv("Class,Unit,Age,Wear\nA,u1,1,0.1\nA,u1,2,0.2\nA,u2,1,0.1\n");
  const d = groupCounts(reads.header, reads.rows, { failed: false, items: "Unit" });
  assert.equal(countWords(d), "3 rows · 2 items");
});

test("problems are per dataset, beside the selector they concern", () => {
  const sheet = parseCsv(SHEET);
  const { groups } = splitSheet(sheet, "Equipment class");
  const problems = splitProblems(sheet.header, groups, lifeSpec(MAPPING));
  assert.deepEqual(problems.filter((p) => !p.note), [
    { row: "x", text: "Boiler feed pump: 1 row has no x" },
    { row: "x", text: "Boiler feed pump: 1 row has x that isn't a number" },
  ]);
  // A dataset where nothing failed: a note, not a block.
  const quiet = parseCsv("Class,Hours,Status\nA,1,Failed\nB,2,Running\n");
  const notes = splitProblems(quiet.header, splitSheet(quiet, "Class").groups,
    lifeSpec({ x: "Hours", c: "Status", c_map: { Failed: 0, Running: 1 } }));
  assert.deepEqual(notes, [{ row: "c", text: "B: nothing failed, so there's nothing to fit yet", note: true }]);
  // A range fills in for a blank x; an item id needn't be a number.
  const ranged = parseCsv("Class,Hours,Last good,Found failed,Unit\nA,,5,8,u1\nA,,,,\n");
  const rp = splitProblems(ranged.header, splitSheet(ranged, "Class").groups, {
    needs: [{ row: "i", col: "Unit", number: false }, { row: "x", col: "Hours", range: ["Last good", "Found failed"] }],
  });
  assert.deepEqual(rp.filter((p) => !p.note).map((p) => p.text), ["A: 1 row has no i", "A: 1 row has no x"]);
  const ids = parseCsv("Class,Unit,Hours\nA,u1,5\nA,,6\n");
  assert.deepEqual(splitProblems(ids.header, splitSheet(ids, "Class").groups, {
    needs: [{ row: "i", col: "Unit", number: false }, { row: "x", col: "Hours" }],
  }).filter((p) => !p.note), [{ row: "i", text: "A: 1 row has no i" }]);
});

test("names: the value, or the value with the file when a dataset of that name exists", () => {
  assert.deepEqual(splitNames(["Transformer", "Coal mill"], [], "plant"), ["Transformer", "Coal mill"]);
  assert.deepEqual(splitNames(["Transformer", "Coal mill"], ["transformer"], "plant"),
    ["Transformer – plant", "Coal mill"]);
  assert.deepEqual(splitNames(["Pump"], ["Pump", "Pump – plant"], "plant"), ["Pump – plant (2)"]);
  assert.equal(sourceStem("JIP data.xlsx"), "JIP data");
  assert.equal(sourceStem("plant.csv"), "plant");
});

test("the free plan's cap: says how many fit before saving", () => {
  const billing = { billing_enabled: true, plan_caps: { datasets: 3 }, usage: { datasets: 1 } };
  assert.equal(splitRoom(billing, 2), null);
  const over = splitRoom(billing, 3);
  assert.equal(over.room, 2);
  assert.match(over.text, /makes 3 datasets, but your free plan allows 3 saved datasets and only 2 more fit/);
  assert.match(splitRoom({ ...billing, usage: { datasets: 3 } }, 2).text, /none of these 2 fit/);
  assert.equal(splitRoom({ ...billing, plan_caps: { datasets: null } }, 9), null); // Pro
  assert.equal(splitRoom({ billing_enabled: false }, 9), null); // self-hosted
});

test("a dataset split from a sheet starts its fit from the reading it was split with", async () => {
  const { startingMapping, savedMapping, columnFacts } = await import("./lifeData.js");
  const saved = { mapping: { x: "Hours", c: "Status" }, options: { c_map: { Failed: 0, Running: 1 } }, unit: "hours",
                  model_name: "", split_from: "plant" };
  const kept = savedMapping(saved, ["Tag", "Hours", "Status"]);
  assert.equal(kept.split, "plant");
  assert.deepEqual(kept.mapping.c_map, { Failed: 0, Running: 1 });
  const csv = { columns: ["Tag", "Hours", "Status"], n_rows: 3, preview: [["T-1", 5, "Failed"]], n_unique: [3, 3, 2],
                dtypes: ["str", "int64", "str"], blanks: [0, 0, 0], values: [null, null, { Failed: 2, Running: 1 }],
                whole: [null, true, null] };
  const s = startingMapping(saved, csv.columns, columnFacts(csv), 3);
  assert.equal(s.split, "plant");
  // A model of its own wins: no split wording then.
  assert.equal(savedMapping({ ...saved, model_name: "Weibull" }, csv.columns).split, undefined);
});
