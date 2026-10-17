import { test } from "node:test";
import assert from "node:assert/strict";
import { TEST_PLAN_TABS, TEST_PLANNING_PATH, altPlanLink, altPrefill, frac, num, tabFromPath } from "./testPlanning.js";

test("each tab has its own path, the Demonstration tab the page's", () => {
  assert.equal(TEST_PLAN_TABS[0].path, TEST_PLANNING_PATH);
  assert.equal(new Set(TEST_PLAN_TABS.map((t) => t.path)).size, TEST_PLAN_TABS.length);
  for (const t of TEST_PLAN_TABS) assert.equal(tabFromPath(t.path), t.id);
  assert.equal(tabFromPath("/strategy/test-planning/"), "demonstration");
  assert.equal(tabFromPath("/strategy/test-planning/life/"), "life");
  assert.equal(tabFromPath("/strategy/test-planning/nope"), "demonstration");
});

test("form values: blank is not given", () => {
  assert.equal(num(""), null);
  assert.equal(num("12.5"), 12.5);
  assert.equal(frac("90"), 0.9);
  assert.equal(frac(null), null);
});

const ALT = {
  distribution_id: "weibull",
  life_model_id: "arrhenius",
  unit: "hours",
  stresses: [{ key: "s1", column: "temp", label: "Temperature", unit: "K" }],
  params: [{ name: "beta", value: 2.1 }],
  coefficients: [{ name: "a", value: 6000 }, { name: "b", value: 3e-5 }],
  levels: [{ stress: [353], n: 10 }, { stress: [393], n: 10 }, { stress: [373], n: 10 }],
};

test("an ALT model's planning values for the next test", () => {
  assert.deepEqual(altPrefill(ALT), {
    distribution: "weibull",
    lifeModel: "arrhenius",
    params: { a: "6000", b: "0.00003" },
    shape: "2.1",
    unit: "hours",
    stressUnit: "K",
    highStress: "393",
  });
  assert.equal(altPlanLink("m 1"), "/strategy/test-planning/accelerated?model=m%201");
});

test("models a plan can't use give no prefill", () => {
  assert.equal(altPrefill(null), null);
  assert.equal(altPrefill({ ...ALT, life_model_id: "dual_power" }), null);
  assert.equal(altPrefill({ ...ALT, distribution_id: "gamma" }), null);
  assert.equal(altPrefill({ ...ALT, stresses: [{}, {}] }), null);
  assert.equal(altPrefill({ ...ALT, coefficients: [{ name: "a", value: 1 }] }), null);
});
