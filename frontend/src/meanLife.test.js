import test from "node:test";
import assert from "node:assert/strict";
import { boundUnavailable, hasMeanLife, meanLevels, meanLifeAnswer, medianOf } from "./meanLife.js";

const fns = { life_path: "/api/models/m-1/life" };

test("the Model characteristics tab: plain, flexible and non-parametric fits only", () => {
  assert.equal(hasMeanLife({ kind: "distribution", functions: fns }), true);
  assert.equal(hasMeanLife({ kind: "flexible", functions: fns }), true);
  assert.equal(hasMeanLife({ kind: "nonparametric", functions: fns }), true);
  // A model saved with its life but no live path still has the saved figures.
  assert.equal(hasMeanLife({ kind: "distribution", life: { mttf: { value: 1 } } }), true);
  for (const kind of ["regression", "discrete", "per_demand", "competing_risks"]) {
    assert.equal(hasMeanLife({ kind, functions: fns }), false, kind);
  }
  assert.equal(hasMeanLife({ kind: "distribution", functions: fns, no_finite_maximum: { note: "x" } }), false);
  assert.equal(hasMeanLife({ kind: "distribution" }), false);
  assert.equal(hasMeanLife(null), false);
});

test("the levels offered keep a typed one", () => {
  assert.deepEqual(meanLevels(90), [80, 90, 95, 99]);
  assert.deepEqual(meanLevels(85), [80, 85, 90, 95, 99]);
  assert.deepEqual(meanLevels("abc"), [80, 90, 95, 99]);
});

test("a whole mean with its bound", () => {
  const a = meanLifeAnswer({ kind: "distribution", distribution_id: "weibull", params: [{ name: "beta", value: 2.5 }] },
                           { value: 1272.4, lower: 1150.2 });
  assert.deepEqual(a, { kind: "mean", value: 1272.4, lower: 1150.2, caveat: null });
  // No bound: the value stands alone.
  assert.equal(meanLifeAnswer({ kind: "distribution" }, { value: 10, lower: null }).lower, null);
});

test("a Weibull shape below 1 says the mean is far out", () => {
  const a = meanLifeAnswer({ kind: "distribution", distribution_id: "weibull", params: [{ name: "beta", value: 0.6 }] },
                           { value: 3000, lower: 2000 });
  assert.match(a.caveat, /below 1/);
});

test("no finite mean: none, and why — never Infinity", () => {
  const lfp = meanLifeAnswer({ kind: "distribution", extras: { p: 0.7 } }, { value: null, lower: null });
  assert.equal(lfp.kind, "none");
  assert.match(lfp.why, /never fail/);
  const heavy = meanLifeAnswer({ kind: "distribution", distribution_id: "loglogistic" }, { value: Infinity });
  assert.equal(heavy.kind, "none");
  assert.match(heavy.why, /no finite mean/);
  assert.equal(meanLifeAnswer({ kind: "distribution" }, null).kind, "none");
});

test("a non-parametric mean is counted to its horizon unless the curve reaches zero", () => {
  const r = meanLifeAnswer({ kind: "nonparametric" }, { value: 25.1, lower: 21.3, tau: 43, restricted: true });
  assert.deepEqual(r, { kind: "restricted", value: 25.1, lower: 21.3, tau: 43, caveat: null });
  const whole = meanLifeAnswer({ kind: "nonparametric" }, { value: 25.1, lower: 21.3, tau: 43, restricted: false });
  assert.equal(whole.kind, "mean");
});

test("the median from the same answer", () => {
  assert.equal(medianOf({ b_lives: [{ label: "B10", value: 5 }, { label: "B50", value: 1240 }] }), 1240);
  assert.equal(medianOf({ b_lives: [{ label: "B50", value: null }] }), null);
  assert.equal(medianOf(null), null);
});

test("a bound a shared page can't fetch says why, in words", () => {
  const signedOut = Object.assign(new Error("Not authenticated"), { status: 401 });
  assert.match(boundUnavailable(signedOut, 0.9), /signed in.*saved 90% figures/);
  const other = Object.assign(new Error("Bad horizon"), { status: 422 });
  assert.equal(boundUnavailable(other, 0.9), "Couldn't work out the mean life: Bad horizon.");
  assert.equal(boundUnavailable(null, 0.9), null);
});
