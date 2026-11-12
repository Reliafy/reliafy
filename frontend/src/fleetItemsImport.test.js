import { test } from "node:test";
import assert from "node:assert/strict";
import {
  calendarUnit, guessAgeUnit, guessMapping, hasHeader, mergeItems, patchSelected, readBlock, readDate, readItems,
  readNumber, removeSelected, sniffDelimiter, splitRows, summary, unitFactor,
} from "./fleetItemsImport.js";

const TODAY = Date.UTC(2026, 10, 12); // 12 Nov 2026

test("a block from Excel is tab separated; a CSV comma or semicolon", () => {
  assert.equal(sniffDelimiter("Pump\tAge\nP1\t100"), "\t");
  assert.equal(sniffDelimiter("Pump,Age\nP1,100"), ",");
  assert.equal(sniffDelimiter("Pump;Age;Load\nP1;100;3,5"), ";");
});

test("rows keep quoted separators and drop blank lines", () => {
  assert.deepEqual(splitRows("Name,Age\r\n\"Pump, east\",100\n\n\"Say \"\"hi\"\"\",5\n"),
    [["Name", "Age"], ["Pump, east", "100"], ["Say \"hi\"", "5"]]);
});

test("numbers with thousands, decimal commas and units", () => {
  assert.deepEqual(readNumber("1,200"), { value: 1200, unit: "" });
  assert.deepEqual(readNumber("3,5"), { value: 3.5, unit: "" });
  assert.deepEqual(readNumber("1200 h"), { value: 1200, unit: "Hours" });
  assert.deepEqual(readNumber("2.5 years"), { value: 2.5, unit: "Years" });
  assert.equal(readNumber("PU-01"), null);
  assert.equal(readNumber(""), null);
});

test("dates: ISO, day first, and month names", () => {
  assert.equal(readDate("2026-01-12"), Date.UTC(2026, 0, 12));
  assert.equal(readDate("12/01/2026"), Date.UTC(2026, 0, 12));
  assert.equal(readDate("12-Jan-2026"), Date.UTC(2026, 0, 12));
  assert.equal(readDate("Jan 12, 2026"), Date.UTC(2026, 0, 12));
  assert.equal(readDate("31/02/2026"), null);
  assert.equal(readDate("1200"), null);
});

test("a header row is told from data", () => {
  assert.equal(hasHeader([["Pump", "Hours"], ["P1", "100"]]), true);
  assert.equal(hasHeader([["P1", "100"], ["P2", "200"]]), false);
});

test("columns are guessed by header, covariates by their own name", () => {
  const fields = [{ name: "load", label: "Load", type: "number" }];
  const headers = ["Pump ID", "Load", "Run hours", "Hours per month"];
  const rows = [["PU-1", "3", "1200", "500"], ["PU-2", "4", "800", "450"]];
  assert.deepEqual(guessMapping(headers, rows, { fields }), ["name", "cov:load", "current_use", "rate"]);
  // A date column is the last replacement; with no header the first text column is the name.
  assert.deepEqual(guessMapping(["Seal", "Fitted"], [["S1", "2025-01-03"]]), ["name", "last_replaced"]);
  assert.deepEqual(guessMapping(["", ""], [["S1", "40"], ["S2", "50"]]), ["name", "current_use"]);
});

test("the age column's unit from its header or its cells", () => {
  assert.equal(guessAgeUnit("Age (days)"), "Days");
  assert.equal(guessAgeUnit("Age", ["1200 h"]), "Hours");
  assert.equal(guessAgeUnit("Age", ["1200"]), "");
  assert.equal(calendarUnit("hours"), "Hours");
  assert.equal(calendarUnit("Cycles"), "");
  assert.equal(unitFactor("Days", "Hours"), 24);
  assert.equal(unitFactor("Hours", "Cycles"), null);
});

test("20 pumps pasted from Excel: every row read, ages converted to the model's unit", () => {
  const lines = ["Pump\tAge (days)", ...Array.from({ length: 20 }, (_, k) => `PU-${k + 1}\t${10 * (k + 1)}`)];
  const block = readBlock(lines.join("\n"));
  assert.equal(block.header, true);
  assert.deepEqual(block.mapping, ["name", "current_use"]);
  const out = readItems(block.rows, block.mapping, { modelUnit: "Hours", ageUnit: "Days", firstRow: block.firstRow });
  assert.equal(out.items.length, 20);
  assert.deepEqual(out.items[0], { name: "PU-1", current_use: 240, rate: null });
  assert.deepEqual(out.notes, ["Ages in days converted to hours."]);
  assert.equal(summary(out), "20 items read");
});

test("rows that can't be read are skipped, each with its reason and spreadsheet row", () => {
  const block = readBlock("Pump,Hours\nP1,100\n,200\nP3,lots\nP4,-5\nP5,300");
  const out = readItems(block.rows, block.mapping, { firstRow: block.firstRow });
  assert.deepEqual(out.items.map((i) => i.name), ["P1", "P5"]);
  assert.deepEqual(out.skipped, [
    { row: 3, why: "no name" },
    { row: 4, why: "the current use “lots” isn't a number of at least 0" },
    { row: 5, why: "the current use “-5” isn't a number of at least 0" },
  ]);
  assert.equal(summary(out), "2 items read; 3 rows skipped");
});

test("a replacement date gives the age at the item's usage rate, and its time in service", () => {
  const rows = [["S1", "2026-05-12", ""], ["S2", "2026-05-12", "100"]];
  const out = readItems(rows, ["name", "last_replaced", "rate"],
                        { modelUnit: "Hours", defaultRate: 500, periodLabel: "months", today: TODAY });
  const months = 184 / 30.4375;
  assert.ok(Math.abs(out.items[0].current_use - 500 * months) < 1e-8);
  assert.ok(Math.abs(out.items[1].current_use - 100 * months) < 1e-8);
  assert.ok(Math.abs(out.items[0].service_periods - months) < 1e-9);
  // No usage rate: the calendar time since, in the model's unit.
  const days = readItems([["S1", "2026-11-02"]], ["name", "last_replaced"], { modelUnit: "Days", today: TODAY });
  assert.equal(days.items[0].current_use, 10);
  const none = readItems([["S1", "2026-11-02"]], ["name", "last_replaced"], { modelUnit: "Cycles", today: TODAY });
  assert.equal(none.skipped[0].why, "an age from a date needs the usage per period set first");
});

test("covariate levels are matched to the model's, numbers read as numbers", () => {
  const fields = [{ name: "site", label: "Site", type: "category", options: ["North", "South"] },
                  { name: "load", type: "number" }];
  const out = readItems([["P1", "10", "north", "2.5"], ["P2", "10", "West", "1"]],
                        ["name", "current_use", "cov:site", "cov:load"], { fields });
  assert.deepEqual(out.items[0].covariates, { site: "North", load: 2.5 });
  assert.equal(out.skipped[0].why, "Site “West” isn't one of North, South");
});

test("many items at once: add, replace, set for the selected, remove", () => {
  const items = [{ name: "a", current_use: 1 }, { name: "b", current_use: 2 }, { name: "c", current_use: 3 }];
  assert.equal(mergeItems(items, [{ name: "d" }]).length, 4);
  assert.deepEqual(mergeItems(items, [{ name: "d" }], true), [{ name: "d" }]);
  assert.equal(mergeItems([], Array.from({ length: 600 }, () => ({}))).length, 500);
  assert.match(summary({ items: Array.from({ length: 30 }, () => ({})) }, 490), /only the first 10 fit/);
  const sel = new Set([0, 2]);
  assert.deepEqual(patchSelected(items, sel, { current_use: 9 }).map((i) => i.current_use), [9, 2, 9]);
  assert.deepEqual(removeSelected(items, sel).map((i) => i.name), ["b"]);
});

test("converted ages carry no floating-point noise", () => {
  const out = readItems([["P", "2.24"]], ["name", "current_use"], { modelUnit: "Months", ageUnit: "Years" });
  assert.equal(out.items[0].current_use, 26.88);
});
