import test from "node:test";
import assert from "node:assert/strict";
import { guessAltColumns, stressLevelsWarning, temperatureUnitOf } from "./altGuess.js";

// The capacitor test's workbook: unit, hours, temp_C, temp_K, status, censored.
const capacitors = {
  columns: ["unit", "hours", "temp_C", "temp_K", "status", "censored"],
  dtypes: ["object", "float64", "int64", "float64", "object", "int64"],
  values: [null, null, { 105: 20, 125: 20, 145: 20 }, { "378.15": 20, "398.15": 20, "418.15": 20 },
    { failed: 34, suspended: 26 }, { 0: 34, 1: 26 }],
  n_unique: [60, 37, 3, 3, 2, 2],
};

test("never a text id for the time, never hours for the stress", () => {
  const g = guessAltColumns(capacitors, { nStress: 1, lifeModel: "arrhenius" });
  assert.equal(g.x, "hours");
  assert.equal(g.c, "censored");
  assert.equal(g.unit, "Hours");
  assert.deepEqual(g.stress, [{ col: "temp_K", label: "", unit: "K" }]);
});

test("a Celsius column alone is guessed with its unit", () => {
  const src = { ...capacitors, columns: ["unit", "hours", "temp_C", "status", "censored"],
    dtypes: ["object", "float64", "int64", "object", "int64"],
    values: [null, null, { 105: 20 }, { failed: 1 }, { 0: 1, 1: 1 }], n_unique: [60, 37, 3, 2, 2] };
  const g = guessAltColumns(src, { lifeModel: "eyring" });
  assert.deepEqual(g.stress[0], { col: "temp_C", label: "", unit: "°C" });
});

test("a voltage model takes the voltage, and a two-stress thermal model temperature first", () => {
  const src = {
    columns: ["id", "cycles", "volts", "temp_degC", "c"],
    dtypes: ["int64", "float64", "float64", "float64", "int64"],
    values: [null, null, { 10: 5, 20: 5 }, { 60: 5, 80: 5 }, { 0: 8, 1: 2 }],
    n_unique: [10, 10, 2, 2, 2],
  };
  assert.equal(guessAltColumns(src, { lifeModel: "inverse_power" }).stress[0].col, "volts");
  const two = guessAltColumns(src, { nStress: 2, lifeModel: "power_exponential" });
  assert.equal(two.x, "cycles");
  assert.deepEqual(two.stress.map((s) => s.col), ["temp_degC", "volts"]);
  assert.equal(two.stress[0].unit, "°C");
});

test("a 1 = failed flag isn't guessed (the fit can't flip it here)", () => {
  const src = { columns: ["hours", "tempK", "failed"], dtypes: ["float64", "float64", "int64"],
    values: [null, { 330: 3 }, { 0: 1, 1: 2 }], n_unique: [3, 1, 2] };
  assert.equal(guessAltColumns(src).c, "");
});

test("temperature units from names", () => {
  assert.equal(temperatureUnitOf("temp_C"), "°C");
  assert.equal(temperatureUnitOf("Temperature (°F)"), "°F");
  assert.equal(temperatureUnitOf("TempK"), "K");
  assert.equal(temperatureUnitOf("kelvin"), "K");
  assert.equal(temperatureUnitOf("temperature"), "");
});

test("a stress column with many values asks whether it is the right one", () => {
  assert.match(stressLevelsWarning(capacitors, "hours"), /37 different values/);
  assert.equal(stressLevelsWarning(capacitors, "temp_K"), null);
});

test("suggestLifeModel: a voltage suggests the inverse power law, a temperature Arrhenius", async () => {
  const { suggestLifeModel } = await import("./altGuess.js");
  const src = (columns) => ({ columns, dtypes: columns.map(() => "float64") });
  assert.equal(suggestLifeModel(src(["minutes", "voltage_kV", "censored"])), "inverse_power");
  assert.equal(suggestLifeModel(src(["hours", "temp_C", "voltage"])), "arrhenius");
  assert.equal(suggestLifeModel(src(["hours", "level"])), "");
});
