import { test } from "node:test";
import assert from "node:assert/strict";
import { inputRows, modelText, reopenLink, savedInputs } from "./analysisInputs.js";
import { formatTarget } from "./format.js";

const weib = [{ name: "alpha", value: 4146.7 }, { name: "beta", value: 3.073 }];

test("a saved analysis lists what it was worked out from", () => {
  const rows = inputRows("optimal_replacement", {
    model_name: "SP-200 impellers", unit: "Hours", planned_cost: 2500, unplanned_cost: 14000, use_per_year: 6000,
    units: 30, distribution_id: "weibull", params: weib,
  }, "$");
  assert.deepEqual(rows.map((r) => [r.label, r.value]), [
    ["Model", "SP-200 impellers"], ["Time unit", "Hours"], ["Planned replacement cost", "$2,500"],
    ["Unplanned (failure) cost", "$14,000"], ["Use a year, per unit", "6,000 hours"], ["Units", "30"],
  ]);
  const ffi = inputRows("failure_finding", { distribution_id: "exponential", params: [{ name: "failure_rate", value: 0.002491 }],
                                             target_availability: 0.995, unit: "Months" });
  assert.equal(ffi.find((r) => r.label === "Target availability").value, "99.5%");
  assert.equal(ffi.find((r) => r.label === "Model").value, "Exponential (failure_rate 0.002491)");
  assert.equal(ffi.find((r) => r.label === "Each test").value, "renews the device");
  const cal = inputRows("calendar_replacement", {
    model_name: "Liners", unit: "Weeks", today: "2026-11-12", failure_cost: 160000,
    opportunities: [{ name: "Monthly shut", cost: 45000, every: 4, every_unit: "weeks", start: "2026-11-25" }],
  });
  assert.ok(cal.some((r) => r.value === "Monthly shut: $45,000, every 4 weeks from 2026-11-25"));
  assert.ok(cal.some((r) => r.label === "Replacing between shuts costs" && r.value === "not allowed"));
  assert.deepEqual(inputRows("compare_two", {}), []);
});

test("Open in the tool keeps the model and the figures", () => {
  assert.equal(reopenLink("optimal_replacement", { model_id: "m1", planned_cost: 2500, unplanned_cost: 14000 }).to,
               "/strategy/replacement?model=m1&planned=2500&unplanned=14000");
  assert.equal(reopenLink("failure_finding", { model_id: "m1", target_availability: 0.995 }).to,
               "/strategy/failure-finding?model=m1&target=99.5");
  assert.equal(reopenLink("calendar_replacement", { model_id: "m1" }).to, "/strategy/replacement?model=m1&mode=calendar");
  assert.equal(reopenLink("optimal_replacement", { distribution_id: "weibull", params: weib }), null);
});

test("only a saved model is kept beside the figures", () => {
  assert.deepEqual(savedInputs({ source: "saved", modelId: "m1", name: "Pumps" }), { model_id: "m1", model_name: "Pumps" });
  assert.deepEqual(savedInputs({ source: "params" }), {});
  assert.equal(modelText({ distribution_id: "weibull", params: weib }), "Weibull (alpha 4,147, beta 3.073)");
});

test("a target reads as typed: 99.5% is never 100%", () => {
  assert.equal(formatTarget(0.995), "99.5%");
  assert.equal(formatTarget(0.9999), "99.99%");
  assert.equal(formatTarget(0.99), "99%");
});
