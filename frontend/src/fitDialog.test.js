import { test } from "node:test";
import assert from "node:assert/strict";
import { bodyOf, effective, previewKey, priorChoices, problem } from "./fitDialog.js";

const base = { data: "position", method: "mle", priorKind: "class", distribution: "weibull", trust: "guide", modes: [], exclude: [],
  unit: "hours", params: {}, b10: {}, shape: {} };

test("the data choice sets what the method and prior can be", () => {
  assert.deepEqual(effective(base), { method: "mle", priorKind: null });
  assert.deepEqual(effective({ ...base, data: "both" }), { method: "bayes", priorKind: "class" });
  assert.deepEqual(effective({ ...base, method: "bayes" }), { method: "bayes", priorKind: "class" });
  // The class as data can't be the prior too.
  assert.deepEqual(effective({ ...base, data: "class", method: "bayes", priorKind: "class" }), { method: "bayes", priorKind: "model" });
  assert.deepEqual(priorChoices("class").map((p) => p.value), ["model", "params", "b10"]);
  assert.deepEqual(priorChoices("position").map((p) => p.value), ["class", "model", "params", "b10"]);
});

test("the request for each choice, and what's missing", () => {
  assert.deepEqual(bodyOf(base), { data: "position", method: "mle", distribution: "weibull", failure_mode_ids: [], exclude: [] });
  assert.deepEqual(bodyOf({ ...base, data: "both" }).prior, { kind: "class" });
  assert.equal(bodyOf({ ...base, data: "both" }).trust, "guide");
  const nums = { ...base, method: "bayes", priorKind: "params", params: { alpha: "400", beta: "3" } };
  assert.equal(problem({ ...nums, params: {} }), "Give the prior's numbers.");
  assert.equal(problem(nums), null);
  assert.deepEqual(bodyOf(nums).prior, { kind: "params", distribution: "weibull", unit: "hours",
    params: [{ name: "alpha", value: 400 }, { name: "beta", value: 3 }] });
  assert.equal(problem({ ...base, method: "bayes", priorKind: "model" }), "Pick the model to use as the prior.");
  assert.equal(problem({ ...base, method: "bayes", distribution: "best" }), "“Best of” is for a plain fit: choose a distribution.");
  assert.notEqual(previewKey(base), previewKey({ ...base, data: "class" }));
});

test("the panel's words: For, the history, a refusal's way out", async () => {
  const { countsWords, forWords, historyRow, refusalSwitch } = await import("./fitDialog.js");
  const modes = Array.from({ length: 8 }, (_, i) => ({ id: `m${i}`, text: `Mode ${i}` }));
  assert.equal(forWords(modes, []), "All failures of this position");
  assert.equal(forWords(modes, ["m2"]), "Mode 2");
  assert.equal(forWords(modes, ["m1", "m2", "m3"]), "3 of 8 picked");
  assert.equal(countsWords({ failures: 0, suspensions: 1 }), "0 failures, 1 suspension");
  assert.deepEqual(historyRow({ c: 0, x: 1440.4, to: "2026-01-02", failure_mode: "Seal leaks", item: "P1" }, "Days"),
    { when: "2026-01-02", what: "Seal leaks · P1", age: "1,440 days", kind: "Failure" });
  assert.equal(historyRow({ c: 1, x: 90, from: "2026-03-01", status: "still fitted" }).what, "Still running");
  assert.equal(historyRow({ c: 2, xl: 100, xr: 200 }, "days").age, "100–200 days");
  assert.deepEqual(refusalSwitch("mle"), { to: "bayes", label: "Fit with a prior instead" });
  assert.equal(refusalSwitch("bayes"), null);
});
