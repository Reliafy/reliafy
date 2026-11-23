import { test } from "node:test";
import assert from "node:assert/strict";
import { canSupport, modeSupportBody, supportBody, supportForm, supportOf, supportProblem, supportWords, supportsMode } from "./taskSupport.js";

const saved = { failure_mode_ids: ["fm1"], reference: { value: 50, unit: "hours" }, impact: { form: "hazard_ratio", k: 2 },
  grace: 0, source: "assumed", note: "" };

test("a task's support becomes the form and back, unchanged", () => {
  const f = supportForm({ support: saved });
  assert.equal(f.supporting, true);
  assert.equal(f.k, "2");
  assert.equal(f.reference, "50");
  assert.deepEqual(supportBody({ support: saved }, f, { modes: ["fm1"], unit: "hours" }), {});
  assert.equal(supportForm(null).supporting, false);
  assert.deepEqual(supportBody(null, supportForm(null)), {});
});

test("marking, changing and clearing", () => {
  const f = { ...supportForm(null), supporting: true };
  assert.deepEqual(supportBody(null, f, { unit: "hours" }),
    { support: { failure_mode_ids: [], impact: null, grace: 0, source: "assumed", note: "" } });
  const g = { ...supportForm({ support: saved }), k: "3", grace: "20", supportSource: "maker" };
  assert.deepEqual(supportBody({ support: saved }, g, { modes: ["fm1"], unit: "hours" }).support.impact, { form: "hazard_ratio", k: 3 });
  assert.deepEqual(supportBody({ support: saved }, { ...g, supporting: false }), { support: null });
  // A failure mode the task no longer serves is dropped.
  assert.deepEqual(supportOf({ ...g, supports: new Set(["fm1", "gone"]) }, { modes: ["fm1"] }).failure_mode_ids, ["fm1"]);
});

test("what's refused, in words", () => {
  const f = { ...supportForm(null), supporting: true };
  assert.equal(supportProblem(f), null);
  assert.match(supportProblem({ ...f, k: "0.5" }), /× 1/);
  assert.match(supportProblem({ ...f, grace: "120" }), /0% to 100%/);
  assert.match(supportProblem({ ...f, reference: "0" }), /more than 0/);
  assert.equal(supportProblem({ ...f, supporting: false, k: "x" }), null);
});

test("words, kinds and one failure mode at a time (the RCM)", () => {
  assert.equal(supportWords(saved, { fm1: "Bearing worn out" }), "Keeps it on its life: Bearing worn out · failure rate × 2 if not done");
  assert.equal(supportWords({ ...saved, failure_mode_ids: [], impact: null }), "Keeps it on its life: its whole life · no modelled impact");
  assert.equal(canSupport(""), true);
  assert.equal(canSupport("fixed_interval"), true);
  assert.equal(canSupport("on_condition"), false);
  assert.equal(supportsMode({ failure_mode_ids: [] }, "x"), true);
  assert.deepEqual(modeSupportBody(null, "fm2", true), { support: { failure_mode_ids: ["fm2"] } });
  assert.deepEqual(modeSupportBody({ support: saved }, "fm2", true).support.failure_mode_ids, ["fm1", "fm2"]);
  assert.deepEqual(modeSupportBody({ support: saved }, "fm1", false), { support: null });
  assert.deepEqual(modeSupportBody({ support: { ...saved, failure_mode_ids: [] } }, "fm1", false, { modes: ["fm1", "fm2"] }).support.failure_mode_ids, ["fm2"]);
  assert.deepEqual(modeSupportBody({ support: saved }, "fm1", true), {});
});
