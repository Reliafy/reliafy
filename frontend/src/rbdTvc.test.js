// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  blockSchedules, covariateWords, draftFromSpec, dutyCycle, exprNumber, initialTable, niceNumber,
  presetExpression, scheduleSpec, stairPoints, stairValueAt,
} from "./rbdTvc.js";

const LOAD = { name: "load_pct", type: "number", default: 75.625, unit: "%", min: 60, max: 90, step: 10 };

test("presets insert editable templates built from the fitted range", () => {
  const opts = { value: 75, tMax: 9600, unit: "Hours" };
  assert.equal(presetExpression("constant", LOAD, opts), "75");
  assert.equal(presetExpression("phases", LOAD, opts), "60 if t < 3000 else (90 if t < 6000 else 75)");
  assert.equal(presetExpression("duty", LOAD, opts), "90 if t % 24 < 8 else 60");
  assert.equal(presetExpression("ramp", LOAD, opts), "60 + 10 * floor(t / 2000)");
  assert.equal(presetExpression("geometric", LOAD, opts), "60 * 1.1 ** floor(t / 2000)");
});

test("a covariate without a known range still gets a sensible template", () => {
  const temp = { name: "temp_C", type: "number", default: 79.375 };
  const expr = presetExpression("phases", temp, { tMax: 1000 });
  assert.match(expr, /^79\.38 if t < 300 else \(95\.25 if t < 700 else 79\.38\)$/);
});

test("the duty cycle follows the diagram's unit", () => {
  assert.deepEqual(dutyCycle("Hours"), { period: 24, on: 8 });
  assert.deepEqual(dutyCycle("days"), { period: 7, on: 5 });
  assert.deepEqual(dutyCycle("Cycles", 20000), { period: 1000, on: 300 });
});

test("round numbers for templates", () => {
  assert.equal(niceNumber(3200), 3000);
  assert.equal(niceNumber(0.0123), 0.01);
  assert.equal(niceNumber(-1), 1);
  assert.equal(exprNumber(75.625), "75.63");
  assert.equal(exprNumber(1e6), "1000000");
});

test("drafts become stored schedules and back", () => {
  assert.deepEqual(scheduleSpec({ expression: "  60 if t < 10 else 90 " }), { expression: "60 if t < 10 else 90" });
  assert.equal(scheduleSpec({ expression: " " }), null);
  const table = { table: [{ t: "0", value: "north" }, { t: "500", value: "south" }, { t: "", value: "x" }], period: "1000" };
  const spec = scheduleSpec(table);
  assert.deepEqual(spec, { table: [{ t: 0, value: "north" }, { t: 500, value: "south" }], period: 1000 });
  assert.deepEqual(draftFromSpec(spec), { table: [{ t: "0", value: "north" }, { t: "500", value: "south" }], period: "1000" });
  assert.deepEqual(draftFromSpec({ expression: "5" }), { expression: "5" });
  assert.deepEqual(initialTable({ options: ["a", "b"], default: "b" }), [{ t: "0", value: "b" }]);
});

test("only covariates in schedule mode are stored", () => {
  const modes = { load_pct: "schedule", temp: "constant", site: "schedule" };
  const drafts = { load_pct: { expression: "60" }, temp: { expression: "70" }, site: { expression: "" } };
  assert.deepEqual(blockSchedules(modes, drafts), { load_pct: { expression: "60" } });
  assert.equal(blockSchedules({ temp: "constant" }, drafts), null);
  assert.equal(covariateWords("load", 60, null), "load=60");
  assert.equal(covariateWords("load", 60, { expression: "60" }), "load follows a schedule");
});

test("a stair-step path holds each value until the next change", () => {
  assert.deepEqual(stairPoints([0, 10, 30], [1, 2, 3], 20), [[0, 1], [10, 1], [10, 2], [20, 2]]);
  assert.deepEqual(stairPoints([0], [5], 100), [[0, 5], [100, 5]]);
  assert.equal(stairValueAt([0, 10, 30], [1, 2, 3], 15), 2);
  assert.equal(stairValueAt([0, 10, 30], [1, 2, 3], 30), 3);
});
