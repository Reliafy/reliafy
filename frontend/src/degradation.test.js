// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { distinctCount, guessMeasurementUnit, guessTimeUnit, usableForDegradation } from "./degradation.js";

// The brake-pad sample: 48 rows, six pads, but its first rows are all pad-01.
const brake = {
  columns: ["item", "hours", "wear_mm"],
  preview: [["pad-01", 500, 1.16], ["pad-01", 1050, 1.96], ["pad-01", 1600, 2.53]],
  n_rows: 48,
};

test("distinct ids come from the server's count over every row", () => {
  assert.equal(distinctCount({ ...brake, n_unique: [6, 8, 47] }, "item"), 6);
  assert.equal(distinctCount({ ...brake, n_unique: [6, 8, 47] }, "hours"), 8);
});

test("a first-rows preview alone gives no count, so no false warning", () => {
  assert.equal(distinctCount(brake, "item"), null);
});

test("a preview holding every row is counted directly", () => {
  const whole = { ...brake, n_rows: 3 };
  assert.equal(distinctCount(whole, "item"), 1);
  const two = { columns: ["i"], preview: [["a"], ["b"], ["a"], [null]], n_rows: 4 };
  assert.equal(distinctCount(two, "i"), 2);
});

test("an unmapped or unknown column has no count", () => {
  assert.equal(distinctCount(brake, ""), null);
  assert.equal(distinctCount(brake, "nope"), null);
  assert.equal(distinctCount(null, "item"), null);
});

test("datasets with fewer than three columns can't be fitted", () => {
  assert.equal(usableForDegradation({ n_columns: 3 }), true);
  assert.equal(usableForDegradation({ n_columns: 2 }), false);
  assert.equal(usableForDegradation({}), false);
});

test("time units from column names, in the pickers' spelling", () => {
  assert.equal(guessTimeUnit("hours"), "Hours");
  assert.equal(guessTimeUnit("time_h"), "Hours");
  assert.equal(guessTimeUnit("Age (days)"), "Days");
  assert.equal(guessTimeUnit("operating_hrs"), "Hours");
  assert.equal(guessTimeUnit("odometerKm"), "Kilometres");
  assert.equal(guessTimeUnit("cycles"), "Cycles");
  assert.equal(guessTimeUnit("t"), "");
  assert.equal(guessTimeUnit("time"), "");
  assert.equal(guessTimeUnit("h"), "");
});

test("measurement units from column names", () => {
  assert.equal(guessMeasurementUnit("wear_mm"), "mm");
  assert.equal(guessMeasurementUnit("Crack length (µm)"), "µm");
  assert.equal(guessMeasurementUnit("Wear [mm]"), "mm");
  assert.equal(guessMeasurementUnit("temp_c"), "°C");
  assert.equal(guessMeasurementUnit("capacity_pct"), "%");
  assert.equal(guessMeasurementUnit("resistance (kOhm)"), "kOhm");
  assert.equal(guessMeasurementUnit("wear"), "");
  assert.equal(guessMeasurementUnit("mm"), "");
  assert.equal(guessMeasurementUnit("reading"), "");
});
