// New model's "With a prior": when the data allows one, what's still missing, and the request.
import { test } from "node:test";
import assert from "node:assert/strict";
import { initialFit } from "./fitDialog.js";
import { DATASET_PRIOR_CHOICES, priorAsksDistribution, priorBlocked, priorProblem, priorRequest } from "./priorFit.js";

const MAP = { x: "hours", c: "censored", n: "", xl: "", xr: "", tl: "", tr: "", e: "", g: "", c_invert: false, c_map: null };

test("every prior the Explorer offers but the class's history", () => {
  assert.deepEqual(DATASET_PRIOR_CHOICES.map((p) => p.value), ["model", "library", "params", "around", "b10"]);
  assert.equal(priorAsksDistribution("around"), true);
  assert.equal(priorAsksDistribution("model"), false);
});

test("a prior takes one time column and a status column", () => {
  assert.equal(priorBlocked(MAP), null);
  assert.match(priorBlocked(MAP, { hasCovariates: true }), /no covariates/);
  assert.match(priorBlocked(MAP, { tvc: "intervals" }), /no covariates/);
  assert.match(priorBlocked({ ...MAP, e: "mode" }), /failure-mode/);
  assert.match(priorBlocked({ ...MAP, x: "", xl: "a", xr: "b" }), /one time column/);
  assert.match(priorBlocked({ ...MAP, n: "count" }), /count column/);
  assert.match(priorBlocked({ ...MAP, tl: "from" }), /truncation/);
});

test("what's missing: the data's unit first, then the prior's own", () => {
  const s = { ...initialFit({ method: "bayes", priorKind: "model" }) };
  assert.match(priorProblem(s, ""), /data's unit/);
  assert.equal(priorProblem(s, "Hours"), "Pick the model to use as the prior.");
  assert.equal(priorProblem({ ...s, modelId: "m1" }, "Hours"), null);
  assert.equal(priorProblem({ ...s, priorKind: "params" }, "Hours"), "Give the prior's numbers.");
});

test("the request: a saved dataset or the table's text, its columns, the prior in the data's unit", () => {
  const s = { ...initialFit({ method: "bayes", priorKind: "params" }), params: { alpha: "1000", beta: "2" }, age: "500" };
  const req = priorRequest(s, { ...MAP, c_invert: true }, "Hours", { datasetId: "d1" });
  assert.deepEqual(req, {
    dataset_id: "d1", time_column: "hours", censor_column: "censored", c_invert: true, unit: "hours",
    distribution: "weibull", trust: "guide", age: 500,
    prior: { kind: "params", distribution: "weibull", unit: "hours",
      params: [{ name: "alpha", value: 1000 }, { name: "beta", value: 2 }] },
  });
  const pasted = priorRequest({ ...s, age: "" }, { ...MAP, c: "", c_map: { a: 0 } }, "Days", { content: "time\n1\n" }, { save: true, name: "N" });
  assert.equal(pasted.content, "time\n1\n");
  assert.equal(pasted.dataset_id, undefined);
  assert.equal(pasted.censor_column, null);
  assert.equal(pasted.c_map, undefined);
  assert.equal(pasted.age, undefined);
  assert.equal(pasted.save, true);
  assert.equal(pasted.prior.unit, "days");
});
