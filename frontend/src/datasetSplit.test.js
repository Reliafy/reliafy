// Run with: node --test src/
// The Data section's upload: "Split into datasets by" a column, one sheet
// saved as several datasets. Rows counted per dataset, blank values left out,
// and names that don't clash with saved datasets. No column reading happens
// here (that's at fit time), so there are no per-dataset x/c checks.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  blankWarning, parseCsv, readSheet, splitNames, splitPlan, splitRoom, splitSheet, sourceStem,
} from "./datasetSplit.js";

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
  assert.equal(blankWarning(blank, "Equipment class"), "Rows with no Equipment class are left out: 2");
  assert.equal(blankWarning(0, "Equipment class"), null);
  assert.deepEqual(splitSheet(parseCsv(SHEET), "Nope"), { groups: [], blank: 0 });
});

test("the plan: each dataset's name and row count, before anything is saved", () => {
  const plan = splitPlan(parseCsv(SHEET), "Equipment class", ["transformer"], "plant");
  assert.deepEqual(plan, { blank: 2, parts: [
    { value: "Transformer", name: "Transformer – plant", rows: 2 },
    { value: "Coal mill", name: "Coal mill", rows: 3 },
    { value: "Boiler feed pump", name: "Boiler feed pump", rows: 2 },
  ] });
});

test("a file with no header row: columns named col 1, col 2, … as the server names them", () => {
  const s = readSheet("A,1,0\nB,2,1\nA,3,0\n", true);
  assert.deepEqual(s.header, ["col 1", "col 2", "col 3"]);
  assert.equal(s.rows.length, 3);
  assert.deepEqual(splitPlan(s, "col 1", [], "f").parts.map((p) => [p.name, p.rows]), [["A", 2], ["B", 1]]);
  assert.deepEqual(readSheet("a,b\n1,2\n").header, ["a", "b"]);
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
  assert.match(over.text, /makes 3 datasets, but your free plan allows 3 saved datasets: you can save 2 more/);
  assert.match(splitRoom({ ...billing, usage: { datasets: 3 } }, 2).text, /none of these 2 fit/);
  assert.equal(splitRoom({ ...billing, plan_caps: { datasets: null } }, 9), null); // Pro
  assert.equal(splitRoom({ billing_enabled: false }, 9), null); // self-hosted
});
