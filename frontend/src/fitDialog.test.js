import { test } from "node:test";
import assert from "node:assert/strict";
import { bodyOf, dataOptions, effective, previewKey, priorChoices, problem, refusalWords } from "./fitDialog.js";

const base = { data: "position", method: "mle", priorKind: "class", distribution: "weibull", trust: "guide", modes: [], exclude: [],
  unit: "hours", params: {}, b10: {}, shape: {} };

test("the data choice sets what the method and prior can be", () => {
  assert.deepEqual(effective(base), { method: "mle", priorKind: null });
  assert.deepEqual(effective({ ...base, data: "both" }), { method: "bayes", priorKind: "class" });
  assert.deepEqual(effective({ ...base, method: "bayes" }), { method: "bayes", priorKind: "class" });
  // The class as data can't be the prior too.
  assert.deepEqual(effective({ ...base, data: "class", method: "bayes", priorKind: "class" }), { method: "bayes", priorKind: "model" });
  assert.deepEqual(priorChoices("class").map((p) => p.value), ["model", "library", "params", "around", "b10"]);
  assert.deepEqual(priorChoices("position").map((p) => p.value), ["class", "model", "library", "params", "around", "b10"]);
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

test("Data and Prior as dropdowns, and a prior around a value between two bounds", async () => {
  const { AROUND_PARAMS, aroundParams, dataOptions, showsTrust, PRIOR_CHOICES } = await import("./fitDialog.js");
  assert.deepEqual(dataOptions({ positionCounts: { failures: 0, suspensions: 1 }, cls: { positions: 2, failures: 5, suspensions: 2 } }).map((o) => o.label), [
    "This position's history (0 failures, 1 suspension)", "The class's pooled history (2 positions, 5 failures, 2 suspensions)",
    "Both: this position's, with the class's as a prior"]);
  assert.deepEqual(dataOptions({ hasClass: false }).map((o) => o.value), ["position"]);
  assert.deepEqual(PRIOR_CHOICES.map((p) => p.value), ["class", "model", "library", "params", "around", "b10"]);
  assert.ok(showsTrust("params") && !showsTrust("around") && !showsTrust("b10"));
  assert.deepEqual(AROUND_PARAMS.weibull.map(([n]) => n), ["alpha", "beta"]);
  const s = { ...base, method: "bayes", priorKind: "around", around: { alpha: { about: "4", lo: "3", hi: "6" }, beta: { lo: "1.5", hi: "3" } } };
  assert.deepEqual(aroundParams(s).params, { alpha: { about: 4, between: [3, 6] }, beta: { between: [1.5, 3] } });
  assert.equal(problem(s), null);
  assert.deepEqual(bodyOf(s).prior, { kind: "around", distribution: "weibull", unit: "hours",
    params: { alpha: { about: 4, between: [3, 6] }, beta: { between: [1.5, 3] } } });
  assert.match(problem({ ...s, around: { alpha: { lo: "6", hi: "3" } } }), /low bound must be below/);
  assert.match(problem({ ...s, around: { alpha: { about: "9", lo: "3", hi: "6" } } }), /must lie between/);
  assert.match(problem({ ...s, around: { alpha: { lo: "3" } } }), /both bounds/);
  assert.match(problem({ ...s, around: {} }), /at least one/);
  const e = { ...s, distribution: "exponential", around: { mean: { lo: "100", hi: "300" }, failure_rate: { lo: "0.001", hi: "0.01" } } };
  assert.match(problem(e), /not both/);
});

test("a library record as the prior", async () => {
  const { libraryPriorWords, showsTrust } = await import("./fitDialog.js");
  const s = { ...base, method: "bayes", priorKind: "library", distribution: "exponential" };
  assert.equal(problem(s), "Pick a library record.");
  assert.deepEqual(bodyOf({ ...s, recordId: "nrc-inl-2020:aov-fc" }).prior, { kind: "library", record_id: "nrc-inl-2020:aov-fc" });
  const w = { ...s, recordId: "r1", distribution: "weibull", libShape: { lo: "0.8", hi: "3" } };
  assert.deepEqual(bodyOf(w).prior, { kind: "library", record_id: "r1", shape: [0.8, 3] });
  assert.match(problem({ ...w, libShape: { lo: "3", hi: "1" } }), /low < high/);
  assert.ok(!showsTrust("library"));
  assert.match(libraryPriorWords("exponential"), /conjugate/);
  assert.match(libraryPriorWords("weibull"), /prior on the mean life/);
});

test("refusalWords names the distribution as the app does; dataOptions counts positions in the singular", () => {
  assert.equal(refusalWords("This position's history has 0 failures; a plain weibull fit needs at least 2. Or fit with a prior."),
    "This position's history has 0 failures; a plain Weibull fit needs at least 2. Or fit with a prior.");
  assert.equal(refusalWords("a lognormal model needs at least 2"), "a Lognormal model needs at least 2");
  assert.equal(refusalWords(null), "");
  const opts = dataOptions({ cls: { positions: 1, failures: 0, suspensions: 1 } });
  assert.match(opts[1].label, /\(1 position, /);
});

test("the fit opens as its opener asked, and counts as changed only when a choice is", async () => {
  const { fitChanged, fitTitle, initialFit } = await import("./fitDialog.js");
  const plain = initialFit();
  assert.equal(plain.data, "position");
  assert.equal(plain.method, "mle");
  assert.equal(plain.distribution, "weibull");
  // A library record as the prior opens on the exponential (the exact update).
  const lib = initialFit({ method: "bayes", priorKind: "library", recordId: "r1" });
  assert.equal(lib.distribution, "exponential");
  assert.equal(lib.recordId, "r1");
  // A refit keeps the row's failure modes.
  assert.deepEqual(initialFit({}, { failure_modes: [{ id: "m1" }, { id: "m2" }] }).modes, ["m1", "m2"]);

  assert.equal(fitChanged(plain, initialFit()), false);
  assert.equal(fitChanged(plain, { ...plain, method: "bayes" }), true);
  assert.equal(fitChanged(plain, { ...plain, exclude: new Set(["f1"]) }), true);
  assert.equal(fitChanged(plain, { ...plain, params: { alpha: "400" } }), true);
  // Typed and cleared again, or only asked about an age: nothing to lose.
  assert.equal(fitChanged(plain, { ...plain, params: { alpha: "" } }), false);
  assert.equal(fitChanged(plain, { ...plain, around: { alpha: { about: "", lo: "" } } }), false);
  assert.equal(fitChanged(plain, { ...plain, age: "1000" }), false);
  // The same failure modes picked in another order are the same.
  assert.equal(fitChanged({ ...plain, modes: ["a", "b"] }, { ...plain, modes: ["b", "a"] }), false);

  assert.equal(fitTitle(), "Fit a life model");
  assert.equal(fitTitle({ id: "l1" }), "Refit the life model");
});
