import { test } from "node:test";
import assert from "node:assert/strict";
import { checkPercent } from "./percent.js";
import { STRATEGY_TOOLS, failureFindingMissing, replacementMissing, strategyListFor } from "./strategyTools.js";

const model = { distribution_id: "weibull", params: [] };

test("replacement says what's missing, in order", () => {
  assert.equal(replacementMissing({ model: null, planned: "1", unplanned: "2" }), "Choose a non-repairable model first.");
  assert.equal(replacementMissing({ model: { kind: "regression", distribution_id: "weibull" }, planned: "1", unplanned: "2" }),
    "Choose a plain distribution model.");
  assert.equal(replacementMissing({ model, planned: "", unplanned: "" }), "Enter both costs.");
  assert.equal(replacementMissing({ model, planned: "", unplanned: "5" }), "Enter the planned replacement cost.");
  assert.equal(replacementMissing({ model, planned: "5", unplanned: "" }), "Enter the unplanned (failure) cost.");
  assert.equal(replacementMissing({ model, planned: "0", unplanned: "5" }), null);
});

test("failure finding needs a model and a target", () => {
  assert.equal(failureFindingMissing({ model: null, availability: "99" }), "Choose a non-repairable model first.");
  assert.equal(failureFindingMissing({ model, availability: "" }), "Enter a target availability.");
  assert.equal(failureFindingMissing({ model, availability: "99", availCheck: checkPercent("99") }), null);
  assert.equal(failureFindingMissing({ model, availability: "0.99", availCheck: checkPercent("0.99") }),
    "Check the target availability.");
});

test("every tool has a guide and a saved kind", () => {
  for (const t of Object.values(STRATEGY_TOOLS)) {
    assert.ok(t.kind && t.noun && t.help.guide);
  }
  assert.equal(strategyListFor("failure_finding"), "/strategy?kind=failure_finding");
});
