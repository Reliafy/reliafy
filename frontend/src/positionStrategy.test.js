import { test } from "node:test";
import assert from "node:assert/strict";
import { classPresets, rowInputs, strategiesByLink, strategiesFor, strategyHeadline } from "./positionStrategy.js";

const life = { id: "L1", position_id: "P1", model_type: "model", model_id: "m1", role: "fitted",
  model: { name: "Pump bearings", family: "life", kind: "Weibull" } };
const ids = (link) => strategiesFor(link).choices.map((c) => c.id);

test("the strategy tools that fit each kind of model", () => {
  // Non-repairable life model: replacement by age, at shutdowns, and failure finding for a hidden function.
  assert.deepEqual(ids(life), ["replacement", "calendar", "failureFinding"]);
  // Repairable, minimal repair: overhaul and replace (A27) and the optimal overhaul.
  assert.deepEqual(ids({ ...life, model_type: "recurrent_model", model: { family: "repairable", kind: "Repairable (NHPP)" } }),
    ["overhaulReplace", "overhaul"]);
  // Imperfect repair can't be priced this way: none, with why.
  const grp = strategiesFor({ ...life, model_type: "recurrent_model", model: { family: "repairable", kind: "Repairable (RENEWAL)" } });
  assert.deepEqual(grp.choices, []);
  assert.match(grp.none, /minimal-repair/);
  // Condition and life: the existing condition actions.
  assert.deepEqual(ids({ ...life, model: { family: "condition", kind: "Condition and life" } }), ["conditionRisk", "conditionMonitoring"]);
  // A parts-count prediction (a constant rate): failure finding only.
  assert.deepEqual(ids({ ...life, role: "prediction" }), ["failureFinding"]);
  // Covariate models, RBDs, degradation and missing models: none yet, said plainly.
  assert.deepEqual(ids({ ...life, model: { ...life.model, covariates: ["temp"] } }), []);
  assert.deepEqual(ids({ ...life, model_type: "rbd", model: { family: "rbd", kind: "RBD" } }), []);
  assert.deepEqual(ids({ ...life, model_type: "degradation_model", model: { family: "degradation" } }), []);
  assert.match(strategiesFor({ ...life, model: null }).none, /isn't there/);
});

test("saved strategies are grouped by the model row they were saved for, newest first", () => {
  const by = strategiesByLink([
    { id: "a", kind: "optimal_replacement", position_link_id: "L1", created_at: "2026-11-01" },
    { id: "b", kind: "failure_finding", position_link_id: "L1", created_at: "2026-11-10" },
    { id: "c", kind: "overhaul_replace", position_link_id: "L2", created_at: "2026-11-02" },
    { id: "d", kind: "optimal_replacement", created_at: "2026-11-03" },
    { id: "e", kind: "demonstration_test", position_link_id: "L1", created_at: "2026-11-04" },
  ]);
  assert.deepEqual(Object.keys(by).sort(), ["L1", "L2"]);
  assert.deepEqual(by.L1.map((a) => a.id), ["b", "a"]);
  assert.equal(strategyHeadline([{ headline: "Check every ~1 year" }, { headline: "x" }]), "Check every ~1 year · 1 more");
  assert.equal(strategyHeadline([]), "");
});

test("the class's costs pre-fill the tools; a save keeps the model's row", () => {
  assert.deepEqual(classPresets({ costs: { planned_cost: 200, failure_cost: 1500, availability_target: 0.995 },
    replacement_cost: { amount: 4000 } }), { planned: 200, unplanned: 1500, target: 99.5, replace: 4000 });
  assert.deepEqual(classPresets(null), { planned: null, unplanned: null, target: null, replace: null });
  assert.deepEqual(rowInputs(life), { position_link_id: "L1", position_id: "P1" });
});
