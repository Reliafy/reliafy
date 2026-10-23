import test from "node:test";
import assert from "node:assert/strict";
import { bLabel, betaSource, parseDemoPrefill } from "./requirement.js";

test("bLabel", () => {
  assert.equal(bLabel(10), "B10");
  assert.equal(bLabel(0.1), "B0.1");
  assert.equal(bLabel(2.5), "B2.5");
});

test("a requirement link pre-fills the demonstration test (saved model)", () => {
  const p = parseDemoPrefill("b=10&life=50000&conf=90&unit=Cycles&model=m-1");
  assert.deepEqual(p, { target: "b_life", bLife: "10", missionTime: "50000", confidence: "90", unit: "Cycles", modelId: "m-1" });
});

test("a requirement link pre-fills β inline (a fit not saved)", () => {
  const p = parseDemoPrefill("b=1&life=800&conf=95&unit=hours&beta=2.08&beta_lo=1.03&beta_hi=4.21&from=Seal+fit");
  assert.equal(p.bLife, "1");
  assert.equal(p.modelId, undefined);
  assert.deepEqual(p.beta, { name: "Seal fit", estimate: 2.08, lower: 1.03, upper: 4.21 });
  // An interval that doesn't hold the estimate is dropped, not trusted.
  const bad = parseDemoPrefill("b=10&life=5&beta=2&beta_lo=3&beta_hi=4");
  assert.deepEqual(bad.beta, { name: "this fit", estimate: 2, lower: null, upper: null });
});

test("no requirement, or a malformed one, pre-fills nothing", () => {
  assert.equal(parseDemoPrefill(""), null);
  assert.equal(parseDemoPrefill("b=10"), null);
  assert.equal(parseDemoPrefill("b=100&life=5"), null);
  assert.equal(parseDemoPrefill("b=x&life=5"), null);
  assert.equal(parseDemoPrefill("b=10&life=-5"), null);
  // A bad confidence is left out; the rest stands.
  assert.equal(parseDemoPrefill("b=10&life=5&conf=150").confidence, undefined);
});

test("a model alone pre-fills its β and unit, not a requirement (#294)", () => {
  assert.deepEqual(parseDemoPrefill("model=m-1&unit=Hours"), { modelId: "m-1", unit: "Hours" });
  assert.deepEqual(parseDemoPrefill("model=m-1"), { modelId: "m-1" });
  // A malformed requirement still pre-fills nothing.
  assert.equal(parseDemoPrefill("model=m-1&b=100&life=5"), null);
});

test("betaSource: a Weibull's β and its interval, nothing for another distribution", () => {
  const weib = { distribution_id: "weibull", params: [{ name: "alpha", value: 900 }, { name: "beta", value: 2.08, ci: [1.03, 4.21] }] };
  assert.deepEqual(betaSource(weib, "Seals", "m-2"), { name: "Seals", estimate: 2.08, lower: 1.03, upper: 4.21, modelId: "m-2" });
  assert.deepEqual(betaSource({ distribution: "Weibull", distribution_id: "best", params: [{ name: "beta", value: 3 }] }, "x"),
                   { name: "x", estimate: 3, lower: null, upper: null });
  assert.equal(betaSource({ distribution_id: "lognormal", params: [{ name: "sigma", value: 1 }] }, "x"), null);
  assert.equal(betaSource({ distribution: "Weibull PH", params: [{ name: "beta", value: 1 }] }, "x"), null);
  assert.equal(betaSource(null), null);
});
