import { test } from "node:test";
import assert from "node:assert/strict";
import { adjustRequest, adjustableWhy, adjustedLine, boundsWords, compareRows, lifeScaleExact, ratioWords } from "./modelAdjust.js";

const weibull = { kind: "distribution", results: { kind: "distribution", distribution_id: "weibull",
  params: [{ name: "alpha", value: 1000 }, { name: "beta", value: 2 }] } };

test("a single-distribution model can be adjusted; others say why not", () => {
  assert.equal(adjustableWhy(weibull), null);
  assert.match(adjustableWhy({ kind: "regression", results: { kind: "regression" } }), /single-distribution/);
  assert.match(adjustableWhy({ ...weibull, results: { ...weibull.results, no_finite_maximum: {} } }), /refit/);
});

test("a life scale is offered only where it's exact", () => {
  assert.equal(lifeScaleExact(weibull.results), true);
  assert.equal(lifeScaleExact({ distribution_id: "exponential" }), true);
  assert.equal(lifeScaleExact({ distribution_id: "lognormal" }), false);
  assert.equal(lifeScaleExact({ distribution_id: "weibull", extras: { gamma: 10 } }), false);
  assert.equal(lifeScaleExact({ distribution_id: "weibull", extras: { hr: 1.5 } }), true);
});

test("the form's number becomes the request, or says what to do", () => {
  assert.deepEqual(adjustRequest("hr", "1.5"), { hazardRatio: 1.5 });
  assert.deepEqual(adjustRequest("life", "0.667"), { lifeScale: 0.667 });
  assert.match(adjustRequest("hr", "").error, /Enter a hazard ratio/);
  assert.match(adjustRequest("hr", "0").error, /above 0/);
  assert.match(adjustRequest("hr", "5000").error, /between/);
});

test("the hand check's before and after: B10 324.6 h to 265.0 h", () => {
  const preview = { unit: "Hours", before: { b10: 324.593, mean: 886.227 }, after: { b10: 265.029, mean: 723.601,
    mean_note: "No bound on the mean life: SurPyval doesn't give one for a model adjusted by a hazard ratio." } };
  const [b10, mean] = compareRows(preview);
  assert.equal(b10.before, "325 hours");
  assert.equal(b10.after, "265 hours");
  assert.equal(b10.change, "−18.4%");
  assert.equal(mean.change, "−18.4%");
  assert.match(boundsWords(preview).join(" "), /one-sided.*held fixed.*No bound on the mean/);
  assert.deepEqual(boundsWords({ before: { bounds_note: "No confidence bounds: x." }, after: { bounds_note: "No confidence bounds: x." } }),
                   ["No confidence bounds: x."]);
  assert.match(ratioWords(1.5), /^1\.5 times the hazard.*harsher/);
  assert.match(ratioWords(0.8), /milder/);
});

test("an adjusted model names its original", () => {
  assert.equal(adjustedLine({}), null);
  assert.deepEqual(adjustedLine({ adjusted: { from_model_id: "m1", from_name: "Pump", hazard_ratio: 1.5 } }),
                   { from: "m1", name: "Pump", ratio: "1.5" });
});
