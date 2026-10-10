import test from "node:test";
import assert from "node:assert/strict";
import {
  dataText, effectTone, ratioCiText, familyOf, growthReading, orderedParams, paramLabel, pct, perUnit, ratioText, repairTitle,
} from "./recurrentResults.js";

test("paramLabel: plain names with the unit, per model", () => {
  const ca = { model: { id: "crow_amsaa" }, unit: "Hours" };
  assert.equal(paramLabel(ca, "alpha"), "Scale α (hours)");
  assert.equal(paramLabel(ca, "beta"), "Shape β");
  // Duane's alpha is its shape, not a scale.
  assert.equal(paramLabel({ model: { id: "duane" }, unit: "hours" }, "alpha"), "Growth shape α");
  assert.equal(paramLabel({ model: { id: "hpp" }, unit: "hours" }, "lambda"), "Failure rate λ (per hour)");
  const grp = { family: "renewal", model: { id: "grp_i" }, unit: "hours" };
  assert.equal(paramLabel(grp, "q"), "Restoration factor q");
  assert.equal(paramLabel({ family: "renewal", model: { id: "ari" }, baseline: { id: "crow_amsaa" } }, "rho"),
    "Repair efficiency ρ");
  assert.equal(paramLabel({ family: "regression", baseline: { id: "crow_amsaa" }, unit: "days" }, "alpha"),
    "Scale α (days)");
  assert.equal(paramLabel(ca, "mystery"), "mystery");
});

test("orderedParams: shape before scale, restoration first", () => {
  const ca = { model: { id: "crow_amsaa" }, params: [{ name: "alpha" }, { name: "beta" }] };
  assert.deepEqual(orderedParams(ca).map((p) => p.name), ["beta", "alpha"]);
  const grp = { family: "renewal", model: { id: "grp_i" }, params: [{ name: "alpha" }, { name: "beta" }, { name: "q" }] };
  assert.deepEqual(orderedParams(grp).map((p) => p.name), ["q", "beta", "alpha"]);
});

test("growthReading: the verdict and the interval that decides it", () => {
  const r = {
    growth: "deteriorating",
    growth_basis: { symbol: "β", no_trend: 1, ci: [1.44, 2.95], estimate: 2.06 },
  };
  assert.deepEqual(growthReading(r), {
    title: "Deteriorating",
    text: "β's 95% interval, 1.44–2.95, is wholly above 1: failures are accelerating.",
  });
  const flat = { growth: "stable", growth_basis: { symbol: "β", no_trend: 1, ci: [0.8, 1.3] } };
  assert.match(growthReading(flat).text, /includes 1/);
  const params = { growth: "improving", growth_basis: { symbol: "β", no_trend: 1, ci: null, estimate: 0.7 } };
  assert.match(growthReading(params).text, /built from parameters/);
  assert.equal(growthReading({ growth: null }), null);
});

test("small words", () => {
  assert.equal(perUnit("Hours"), "hour");
  assert.equal(perUnit("flights"), "flights");
  assert.equal(ratioText(2.164), "×2.2");
  assert.equal(ratioText(1.0334), "×1.03");
  assert.equal(ratioCiText([1.012, 1.056]), "1.01–1.06");
  assert.equal(effectTone("lower"), "success");
  assert.equal(effectTone("higher"), "warning");
  assert.equal(effectTone("unclear"), "neutral");
  assert.equal(repairTitle("partial"), "Partial repair");
  assert.equal(pct(0.793), "79%");
  assert.equal(pct(null), "—");
  assert.equal(dataText({ n_systems: 4, n_events: 30 }), "4 systems, 30 failures");
  assert.equal(dataText({ n_systems: null }), null);
  assert.equal(familyOf({}), "nhpp");
});
