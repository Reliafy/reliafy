import test from "node:test";
import assert from "node:assert/strict";
import { guessRecurrentMapping, numericColumns } from "./recurrentMapping.js";

test("the end of record is guessed, not offered as a covariate", () => {
  const g = guessRecurrentMapping(["truck", "pump_failure_hours", "observed_to_hours"],
    { preview: [["HT-01", 907, 16400], ["HT-01", 1729, 16400]] });
  assert.deepEqual([g.i, g.x, g.tr], ["truck", "pump_failure_hours", "observed_to_hours"]);
  const h = guessRecurrentMapping(["compressor", "failure_hours", "records_end_hours"],
    { dtypes: ["object", "int64", "int64"] });
  assert.deepEqual([h.i, h.x, h.tr], ["compressor", "failure_hours", "records_end_hours"]);
  for (const name of ["tr", "End of record", "test_end", "Observed until", "recordsEnd"]) {
    assert.equal(guessRecurrentMapping(["id", "time", name], { dtypes: ["object", "float64", "float64"] }).tr, name);
  }
});

test("a text column is never guessed as a time", () => {
  const g = guessRecurrentMapping(["unit", "site", "failure_hours", "trial_end_hours", "failure_mode"],
    { preview: [["PD-01", "Coastal", 15, 4000, "bearing"]] });
  assert.deepEqual([g.i, g.x, g.tr, g.mode], ["unit", "failure_hours", "trial_end_hours", "failure_mode"]);
  // Only text columns: no time is guessed rather than a wrong one.
  const t = guessRecurrentMapping(["system", "site"], { preview: [["A", "North"]] });
  assert.equal(t.x, "");
  assert.equal(t.tr, "");
});

test("no end column: tr stays empty", () => {
  const g = guessRecurrentMapping(["system", "hours"], { preview: [["A", 10]] });
  assert.deepEqual([g.i, g.x, g.tr], ["system", "hours", ""]);
});

test("numericColumns reads dtypes, else the preview", () => {
  assert.deepEqual(numericColumns(["a", "b"], { dtypes: ["int64", "object"] }), [true, false]);
  assert.deepEqual(numericColumns(["a", "b"], { preview: [[1, "x"], [null, "y"]] }), [true, false]);
});
