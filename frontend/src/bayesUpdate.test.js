import { test } from "node:test";
import assert from "node:assert/strict";
import { TRUST_CHOICES, baselineOf, bodyOf, ready, rowWords, trustWords } from "./bayesUpdate.js";

test("the trust choices say their widths in words", () => {
  assert.deepEqual(TRUST_CHOICES.map((t) => t.within), [0.1, 0.3, 0.6]);
  assert.equal(trustWords(TRUST_CHOICES[1]), "each number within about 30%; a fitted baseline counts as half of its evidence");
});

test("the baseline from each way of giving it, and the request", () => {
  assert.equal(baselineOf({ kind: "class" }), null);
  assert.ok(ready({ kind: "class" }));
  assert.equal(baselineOf({ kind: "model" }), null);
  assert.deepEqual(baselineOf({ kind: "model", modelId: "m1" }), { model_id: "m1" });
  assert.equal(baselineOf({ kind: "params", distribution: "weibull", params: { alpha: "3000" } }), null);
  assert.deepEqual(baselineOf({ kind: "params", distribution: "weibull", unit: "hours", params: { alpha: "3000", beta: "2" } }),
    { distribution: "weibull", unit: "hours", params: [{ name: "alpha", value: 3000 }, { name: "beta", value: 2 }] });
  assert.equal(baselineOf({ kind: "b10", b10: { value: 5000, low: 6000, high: 8000 } }), null);
  assert.deepEqual(baselineOf({ kind: "b10", unit: "hours", b10: { value: "5000", low: "3000", high: "8000" }, shape: {} }).shape, { low: 1.2, high: 4 });
  assert.deepEqual(bodyOf({ kind: "model", modelId: "m1", trust: "guide", exclude: new Set(["f1"]), age: "1000" }),
    { baseline: { model_id: "m1" }, trust: "guide", exclude: ["f1"], age: 1000 });
  assert.deepEqual(bodyOf({ kind: "class", trust: "close", exclude: [] }), { trust: "close", exclude: [] });
});

test("a history row in words", () => {
  assert.equal(rowWords({ c: 0, x: 1440 }, "Hours"), "Failed at 1,440 hours");
  assert.equal(rowWords({ c: 1, x: 900, status: "still fitted" }, "Hours"), "Still running at 900 hours");
  assert.equal(rowWords({ c: 1, x: 900, status: "removed" }, "Hours"), "Removed at 900 hours");
  assert.equal(rowWords({ c: 2, xl: 100, xr: 200 }, "days"), "Failed between 100 and 200 days");
});
