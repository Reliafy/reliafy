import { test } from "node:test";
import assert from "node:assert/strict";
import {
  modeRestorationBody, modeRestorationForm, modeRestorationProblem, restorationBody, restorationForm, restorationOf, restorationProblem, restorationWords,
} from "./taskRestoration.js";

const TASK = {
  restoration: { own: { kind: "kijima2", q: 0.3, replace_every: 3 }, source: "task" },
  basis_set: null, older_than: null,
};

test("the form says restores %, the server stores q", () => {
  const f = restorationForm(TASK);
  assert.equal(f.restoreKind, "kijima2");
  assert.equal(f.restores, "70");
  assert.equal(f.replaceEvery, "3");
  assert.deepEqual(restorationOf(f), { kind: "kijima2", q: 0.3, replace_every: 3 });
  assert.equal(restorationForm(null).restoreKind, "as_new");
});

test("only what changed is sent", () => {
  const f = { ...restorationForm(TASK), outcome: "fixed_interval", unit: "months" };
  assert.deepEqual(restorationBody(TASK, f), {});
  assert.deepEqual(restorationBody(TASK, { ...f, restores: "50" }).restoration, { kind: "kijima2", q: 0.5, replace_every: 3 });
  assert.deepEqual(restorationBody(TASK, { ...f, restoreKind: "as_new" }), { restoration: null });
  assert.deepEqual(restorationBody(TASK, { ...f, runningHours: true }), { basis: "operating" });
  assert.deepEqual(restorationBody(TASK, { ...f, olderThan: "18" }), { older_than: { value: 18, unit: "months" } });
  // A task counted on a meter has no basis to set.
  assert.deepEqual(restorationBody(TASK, { ...f, unit: "hours", runningHours: true }), {});
  // A new task: only what isn't the default.
  const blank = { ...restorationForm(null), outcome: "fixed_interval", unit: "months" };
  assert.deepEqual(restorationBody(null, blank), {});
});

test("problems in words", () => {
  const f = { ...restorationForm(null), restoreKind: "kijima1" };
  assert.match(restorationProblem(f), /how much/);
  assert.equal(restorationProblem({ ...f, restores: "70" }), null);
  assert.match(restorationProblem({ ...f, restores: "70", replaceEvery: "1" }), /2 to 100/);
  assert.match(restorationProblem({ ...restorationForm(null), olderThan: "-1" }), /more than 0/);
});

// ---- one failure mode's own restoration (RCM task details) ----

test("a mode with no restoration of its own follows the task", () => {
  const task = { restoration: { kind: "kijima2", q: 0.3 } };
  assert.deepEqual(modeRestorationForm(task, "m1"), { kind: "task", restores: "" });
  assert.equal(restorationWords(task.restoration), "Restores 70% of its age");
  assert.equal(restorationWords(null), "As new");
});

test("a mode's own restoration is read, checked and written as % taken away, q stored", () => {
  const task = { restoration: { kind: "kijima1", q: 0.5, replace_every: 3, replacement_cost: 900 }, restorations: { m1: { kind: "kijima1", q: 0.2 } } };
  const f = modeRestorationForm(task, "m1");
  assert.deepEqual(f, { kind: "kijima1", restores: "80" });
  assert.equal(modeRestorationProblem({ kind: "kijima1", restores: "" }), "Say how much of its age the task takes away: 0% to 100%.");
  assert.equal(modeRestorationProblem({ kind: "kijima1", restores: "120" }) != null, true);
  assert.equal(modeRestorationProblem(f), null);
  assert.deepEqual(modeRestorationBody(task, "m1", { kind: "kijima2", restores: "60" }),
    { restoration: { kind: "kijima2", q: 0.4, failure_mode_id: "m1", replace_every: 3, replacement_cost: 900 } });
  assert.deepEqual(modeRestorationBody(task, "m1", { kind: "as_new", restores: "" }), { restoration: { kind: "as_new", failure_mode_id: "m1" } });
  assert.deepEqual(modeRestorationBody(task, "m1", { kind: "task", restores: "" }), { restoration: { failure_mode_id: "m1" } });
});
