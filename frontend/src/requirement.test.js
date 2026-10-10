import test from "node:test";
import assert from "node:assert/strict";
import { bLabel, betaSource, demoLink, parseDemoPrefill, requirementVerdict, verdictText } from "./requirement.js";

const CHECK = { b: 10, label: "B10", life: 50000, confidence: 0.9, bounds_note: null };

test("bLabel", () => {
  assert.equal(bLabel(10), "B10");
  assert.equal(bLabel(0.1), "B0.1");
  assert.equal(bLabel(2.5), "B2.5");
});

test("does not meet: the bound is below, whatever the estimate", () => {
  const v = requirementVerdict({ ...CHECK, estimate: 47500, lower: 20500, verdict: "does_not_meet", estimate_meets: false },
                               "Cycles");
  assert.equal(v.tone, "bad");
  assert.equal(v.short, "Does not meet");
  assert.equal(verdictText(v),
    "Does not meet: at 90% confidence B10 ≥ 20,500 cycles, below the 50,000 required. Best estimate 47,500.");
  assert.equal(v.note, null);
  // The numbers are bold.
  assert.deepEqual(v.segments.filter(([, b]) => b).map(([t]) => t), ["20,500 cycles", "50,000", "47,500"]);

  const close = requirementVerdict({ ...CHECK, estimate: 61000, lower: 41000, verdict: "does_not_meet", estimate_meets: true });
  assert.equal(close.tone, "bad");
  assert.match(close.note, /best estimate meets it/);
});

test("meets: the bound is at or above", () => {
  const v = requirementVerdict({ ...CHECK, estimate: 83000, lower: 61200, verdict: "meets", estimate_meets: true }, "hours");
  assert.equal(v.tone, "good");
  assert.equal(verdictText(v),
    "Meets: at 90% confidence B10 ≥ 61,200 hours, at or above the 50,000 required. Best estimate 83,000.");
});

test("unknown: no bounds, an amber caveat with the estimate", () => {
  const v = requirementVerdict({ ...CHECK, confidence: 0.95, estimate: 47500, lower: null, verdict: "unknown",
                                 estimate_meets: false, bounds_note: "No confidence bounds: …" }, "");
  assert.equal(v.tone, "caveat");
  assert.equal(verdictText(v),
    "Can't check at 95% confidence: this model has no confidence bounds. The best estimate of B10 is 47,500, below the 50,000 required.");
  assert.equal(v.note, "No confidence bounds: …");
  assert.equal(requirementVerdict({ ...CHECK, estimate: null, lower: null, verdict: "unknown" }).short, "Can't check");
  assert.equal(requirementVerdict(null), null);
});

test("the demonstration test link round-trips (saved model)", () => {
  const link = demoLink({ b: 10, life: 50000, confidence: 90, unit: "Cycles", modelId: "m-1" });
  assert.ok(link.startsWith("/strategy/demonstration-test?"));
  const p = parseDemoPrefill(link.split("?")[1]);
  assert.deepEqual(p, { target: "b_life", bLife: "10", missionTime: "50000", confidence: "90", unit: "Cycles", modelId: "m-1" });
});

test("the demonstration test link round-trips (a fit not saved: β inline)", () => {
  const beta = { name: "Seal fit", estimate: 2.08, lower: 1.03, upper: 4.21 };
  const p = parseDemoPrefill(demoLink({ b: 1, life: 800, confidence: 95, unit: "hours", beta }).split("?")[1]);
  assert.equal(p.bLife, "1");
  assert.equal(p.modelId, undefined);
  assert.deepEqual(p.beta, beta);
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

test("betaSource: a Weibull's β and its interval, nothing for another distribution", () => {
  const weib = { distribution_id: "weibull", params: [{ name: "alpha", value: 900 }, { name: "beta", value: 2.08, ci: [1.03, 4.21] }] };
  assert.deepEqual(betaSource(weib, "Seals", "m-2"), { name: "Seals", estimate: 2.08, lower: 1.03, upper: 4.21, modelId: "m-2" });
  assert.deepEqual(betaSource({ distribution: "Weibull", distribution_id: "best", params: [{ name: "beta", value: 3 }] }, "x"),
                   { name: "x", estimate: 3, lower: null, upper: null });
  assert.equal(betaSource({ distribution_id: "lognormal", params: [{ name: "sigma", value: 1 }] }, "x"), null);
  assert.equal(betaSource({ distribution: "Weibull PH", params: [{ name: "beta", value: 1 }] }, "x"), null);
  assert.equal(betaSource(null), null);
});
