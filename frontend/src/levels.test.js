// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { ALPHA, AUTO_BOUND, LEVEL, LEVEL_TEXT, boundOptions, ciLevelOf, ciPct, effectiveBound, levelPct, rangeLevelText, ruleBound } from "./levels.js";
import { effectText, forestRows, intervalLevel } from "./modelFrame.js";

test("one level everywhere: 90%, SurPyval's alpha 0.1", () => {
  assert.equal(LEVEL, 0.9);
  assert.equal(ALPHA, 0.1);
  assert.equal(LEVEL_TEXT, "90%");
  assert.equal(levelPct(0.9), "90%");
  assert.equal(levelPct(0.995), "99.5%");
  assert.equal(levelPct(undefined), "90%");
});

test("a result says its own level; one saved before the rule without one was 95%", () => {
  assert.equal(ciPct({ ci_level: 0.9 }), "90%");
  assert.equal(ciPct({}), "95%");
  assert.equal(ciLevelOf({}, 0.9), 0.9);
  assert.deepEqual(intervalLevel({ kind: "distribution", ci_level: 0.9 }), { pct: 90, label: "90%", credible: false });
  assert.equal(intervalLevel({ method: "bayesian_update", credible_level: 0.9 }).label, "90% credible");
});

test("a forecast's likely range: 90% now, 80% for one made before (P10–P90)", () => {
  assert.equal(rangeLevelText(0.9), "90%");
  assert.equal(rangeLevelText(undefined), "90%");
  assert.equal(rangeLevelText("P10–P90"), "80%");
});

test("an effect in words carries its result's level", () => {
  const result = { kind: "regression", ratio_label: "hazard ratio", ci_level: 0.9,
    coefficients: [{ name: "temp_C", value: 0.138, ratio: 1.148, ci: [0.1005, 0.1759] }] };
  const [row] = forestRows(result);
  assert.equal(row.level, "90%");
  assert.match(effectText(row, "hazard ratio"), /\(90% 1\.11 to 1\.19\)/);
});

test("a calculator's bound sits on the safe side for the function shown", () => {
  // Reliability and lives: the lower bound; a chance of failing and the
  // cumulative hazard: the upper one ("28%, at most 34%", never "at least 23%").
  assert.equal(ruleBound("sf"), "lower");
  assert.equal(ruleBound("time"), "lower");
  assert.equal(ruleBound("ff"), "upper");
  assert.equal(ruleBound("Hf"), "upper");
  assert.equal(ruleBound("hf"), "two-sided");
  assert.equal(effectiveBound(AUTO_BOUND, "ff"), "upper");
  assert.equal(effectiveBound("lower", "ff"), "lower"); // the user's own choice stands
  assert.equal(boundOptions("ff")[0].label, "Safe side (upper)");
});
