import { test } from "node:test";
import assert from "node:assert/strict";
import { guessCostColumns, systemIds, toggleSystem } from "./recurrentSystems.js";

test("systemIds: every system in the rows, natural order, no blanks", () => {
  const cols = ["unit", "days"];
  const rows = [["CV-10", 3], ["CV-2", 1], ["CV-2", 5], [null, 4], ["", 2]];
  assert.deepEqual(systemIds(cols, rows, "unit"), ["CV-2", "CV-10"]);
  assert.deepEqual(systemIds(cols, rows, "nope"), []);
});

test("toggleSystem: adds and takes out", () => {
  assert.deepEqual(toggleSystem([], "A"), ["A"]);
  assert.deepEqual(toggleSystem(["A", "B"], "A"), ["B"]);
});

test("guessCostColumns: downtime by name; one cost column, a total over its parts", () => {
  assert.deepEqual(guessCostColumns(["unit", "days", "downtime hours", "total cost"], ["unit", "days"]),
    { downtime: "downtime hours", cost: "total cost" });
  // Parts and labour costs with no total: no cost guessed (a part isn't the whole).
  assert.deepEqual(guessCostColumns(["unit", "days", "parts cost", "labour cost"], ["unit", "days"]),
    { downtime: "", cost: "" });
  assert.deepEqual(guessCostColumns(["unit", "days", "observed_to"], ["unit", "days", "observed_to"]),
    { downtime: "", cost: "" });
});
