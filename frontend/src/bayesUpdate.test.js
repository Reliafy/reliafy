import { test } from "node:test";
import assert from "node:assert/strict";
import { TRUST_CHOICES, baselineOf } from "./bayesUpdate.js";

test("the trust choices and their widths", () => {
  assert.deepEqual(TRUST_CHOICES.map((t) => t.value), ["close", "guide", "start"]);
  assert.deepEqual(TRUST_CHOICES.map((t) => t.within), [0.1, 0.3, 0.6]);
});

test("the prior from each way of giving it", () => {
  assert.equal(baselineOf({ kind: "class" }), null);
  assert.equal(baselineOf({ kind: "model" }), null);
  assert.deepEqual(baselineOf({ kind: "model", modelId: "m1" }), { model_id: "m1" });
  assert.equal(baselineOf({ kind: "params", distribution: "weibull", params: { alpha: "3000" } }), null);
  assert.deepEqual(baselineOf({ kind: "params", distribution: "weibull", unit: "hours", params: { alpha: "3000", beta: "2" } }),
    { distribution: "weibull", unit: "hours", params: [{ name: "alpha", value: 3000 }, { name: "beta", value: 2 }] });
  assert.equal(baselineOf({ kind: "b10", b10: { value: 5000, low: 6000, high: 8000 } }), null);
  assert.deepEqual(baselineOf({ kind: "b10", unit: "hours", b10: { value: "5000", low: "3000", high: "8000" }, shape: {} }).shape, { low: 1.2, high: 4 });
});
