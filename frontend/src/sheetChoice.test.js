import { test } from "node:test";
import assert from "node:assert/strict";
import { forgetSheets, nextSheet, rememberSheet, usedSheets } from "./sheetChoice.js";

test("a second part from the same workbook opens on the sheet not used yet", () => {
  forgetSheets();
  const sheets = [{ name: "Notes", rows: 0 }, { name: "Life", rows: 60 }, { name: "Readings", rows: 622 }];
  const file = { name: "fan-bearings.xlsx", size: 1234, lastModified: 5 };
  assert.equal(nextSheet(sheets, usedSheets(file)).name, "Life");
  rememberSheet(file, "Life");
  // The same workbook dropped again (another File object, same name, size and date).
  assert.equal(nextSheet(sheets, usedSheets({ ...file })).name, "Readings");
  rememberSheet(file, "Readings");
  // Every sheet used: back to the first with data.
  assert.equal(nextSheet(sheets, usedSheets(file)).name, "Life");
  // Another workbook starts afresh.
  assert.equal(nextSheet(sheets, usedSheets({ ...file, size: 99 })).name, "Life");
  assert.equal(nextSheet([{ name: "Empty", rows: 0 }]).name, "Empty");
  assert.equal(nextSheet([]), null);
});
