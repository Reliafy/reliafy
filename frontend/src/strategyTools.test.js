import { test } from "node:test";
import assert from "node:assert/strict";
import { checkPercent } from "./percent.js";
import { STRATEGY_TOOLS, failureFindingMissing, replacementMissing, strategyListFor, strategyUnit } from "./strategyTools.js";

const model = { distribution_id: "weibull", params: [] };

test("replacement says what's missing, in order", () => {
  assert.equal(replacementMissing({ model: null, planned: "1", unplanned: "2" }), "Choose a non-repairable model first.");
  assert.equal(replacementMissing({ model: { kind: "regression", distribution_id: "weibull" }, planned: "1", unplanned: "2" }),
    "Choose a plain distribution model.");
  assert.equal(replacementMissing({ model, planned: "", unplanned: "" }), "Enter both costs.");
  assert.equal(replacementMissing({ model, planned: "", unplanned: "5" }), "Enter the planned replacement cost.");
  assert.equal(replacementMissing({ model, planned: "5", unplanned: "" }), "Enter the unplanned (failure) cost.");
  assert.equal(replacementMissing({ model, planned: "0", unplanned: "5", unit: "days" }), null);
});

// 12 Nov review: a bearing class fitted in days (Weibull α 581, β 5.94), typed
// in as parameters, came back as "replace at about 316 hours" because the unit
// box carried "Hours" over. Typed parameters now need a unit; a saved model's
// own unit always wins.
test("typed parameters need a unit: no default, never hours by accident", () => {
  const typed = { source: "params", distribution_id: "weibull", params: [{ name: "alpha", value: 581 }, { name: "beta", value: 5.94 }] };
  const msg = "Enter the unit of the model's times (e.g. days).";
  assert.equal(replacementMissing({ model: typed, planned: "1050", unplanned: "9000" }), msg);
  assert.equal(replacementMissing({ model: typed, planned: "1050", unplanned: "9000", unit: "  " }), msg);
  assert.equal(replacementMissing({ model: typed, planned: "1050", unplanned: "9000", unit: "days" }), null);
  assert.equal(strategyUnit(typed, " days "), "days");
  assert.equal(strategyUnit(typed, ""), null);
  // A saved model (a class's model from maintenance records is in days) brings its unit.
  const saved = { ...typed, source: "saved", unit: "Days" };
  assert.equal(replacementMissing({ model: saved, planned: "1050", unplanned: "9000" }), null);
  assert.equal(strategyUnit(saved, "Hours"), "Days");
  assert.equal(failureFindingMissing({ model: typed, availability: "99", availCheck: checkPercent("99") }), msg);
  assert.equal(failureFindingMissing({ model: saved, availability: "99", availCheck: checkPercent("99") }), null);
});

test("failure finding needs a model and a target", () => {
  assert.equal(failureFindingMissing({ model: null, availability: "99" }), "Choose a non-repairable model first.");
  assert.equal(failureFindingMissing({ model, availability: "" }), "Enter a target availability.");
  assert.equal(failureFindingMissing({ model, availability: "99", availCheck: checkPercent("99"), unit: "hours" }), null);
  assert.equal(failureFindingMissing({ model, availability: "0.99", availCheck: checkPercent("0.99") }),
    "Check the target availability.");
});

test("every tool has a guide and a saved kind", () => {
  for (const t of Object.values(STRATEGY_TOOLS)) {
    assert.ok(t.kind && t.noun && t.help.guide);
  }
  assert.equal(strategyListFor("failure_finding"), "/strategy?kind=failure_finding");
});
