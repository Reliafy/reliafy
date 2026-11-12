// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { PASTED_FILE, dataName, defaultFitName } from "./fitName.js";

test("a new model is named after its distribution and its data", () => {
  assert.equal(defaultFitName("Weibull", { fileName: "Seal history.csv" }), "Weibull — Seal history");
  assert.equal(defaultFitName("Weibull", { fileName: "pumps.xlsx" }), "Weibull — pumps");
  assert.equal(defaultFitName("Lognormal", { sourceName: "Bearings (sample)" }), "Lognormal — Bearings");
  assert.equal(defaultFitName("Weibull", { fileName: "data.csv" }, { prior: true }), "Weibull with a prior — data");
  assert.equal(defaultFitName("Weibull", {}), "Weibull — dataset");
});

test("pasted values have no name of their own: the day stands in", () => {
  const today = new Date(2026, 10, 12);
  assert.equal(dataName({ fileName: PASTED_FILE, today }), "Pasted values, 12 Nov 2026");
  assert.equal(defaultFitName("Weibull", { fileName: PASTED_FILE, today }), "Weibull — pasted values, 12 Nov 2026");
});
