import { test } from "node:test";
import assert from "node:assert/strict";
import { restorationBody, restorationForm, restorationOf, restorationProblem } from "./taskRestoration.js";

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
