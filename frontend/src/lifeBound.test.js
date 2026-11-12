// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { atLevel, crossingBound, levelText, oneSidedLevel, rulBoundText, twoSidedFor } from "./lifeBound.js";

test("a tracked item's life left is a 90% one-sided lower bound, never a two-sided 95% range", () => {
  // Stored at the life-bound level: an 80% two-sided interval, its lower end the 90% bound.
  const pred = { method: "bayesian", rul: 4585, rul_interval: [4290.4, 4924], alpha_ci: 0.2,
    failure_time: 6585, failure_time_interval: [6290, 6924] };
  assert.equal(rulBoundText(pred, "hours"), "4,585 hours (at least 4,290, 90%)");
  assert.doesNotMatch(rulBoundText(pred, "hours"), /–/);
  assert.deepEqual(crossingBound(pred), { level: "90%", lower: 6290 });
  // One stored at 95% two-sided says what its lower end really is (97.5% one-sided).
  assert.equal(rulBoundText({ ...pred, alpha_ci: 0.05, rul_interval: [4159, 5123] }, "hours"), "4,585 hours (at least 4,159, 97.5%)");
  assert.equal(rulBoundText({ method: "point", rul: 12 }, "hours"), "12 hours");
  assert.equal(rulBoundText({ method: "error" }), "—");
});

test("the confidence picker's one-sided levels map to the two-sided interval asked for", () => {
  assert.equal(twoSidedFor(0.9), 0.8);
  assert.equal(twoSidedFor(0.95), 0.9);
  assert.equal(twoSidedFor(0.99), 0.98);
  assert.equal(oneSidedLevel(0.2), 0.9);
  assert.equal(atLevel({ alpha_ci: 0.2 }, 0.9), true);
  assert.equal(atLevel({ alpha_ci: 0.05 }, 0.9), false);
  assert.equal(levelText(0.975), "97.5%");
});
