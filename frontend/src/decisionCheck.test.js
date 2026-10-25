import { test } from "node:test";
import assert from "node:assert/strict";
import { checkDecision } from "./decisionCheck.js";

// The fields each outcome asks for (as GET /api/rcm/options says).
const F = { on_condition: ["task", "interval"], fixed_interval: ["task", "interval"], failure_finding: ["task", "interval"], rtf: ["rtf_basis", "task"], redesign: ["notes"], accept: ["notes"] };
const check = (d, opts) => checkDecision({ fields: F[d.outcome] || [], ...d }, opts);

test("no decision picked: Apply says to choose one", () => {
  assert.deepEqual(check({}).blockers, ["Choose a maintenance decision."]);
});

test("fixed interval and failure finding need an interval, marked and said in plain words", () => {
  for (const outcome of ["fixed_interval", "failure_finding"]) {
    const c = check({ outcome, task: "Replace the bearings" });
    assert.deepEqual(c.blockers, ["Give the task's interval."]);
    assert.match(c.intervalError, /^Give the interval: how often/);
    assert.equal(c.notice, null);
    assert.deepEqual(check({ outcome, interval: "3", intervalUnit: "months" }).blockers, []); // a task's words aren't needed
  }
});

test("an interval given is a number above 0 (as the server checks it)", () => {
  assert.equal(check({ outcome: "fixed_interval", interval: "0" }).intervalError, "The interval must be more than 0.");
  assert.equal(check({ outcome: "on_condition", interval: "-2" }).intervalError, "The interval must be more than 0.");
  assert.equal(check({ outcome: "fixed_interval", interval: "abc" }).intervalError, "The interval must be a number.");
  assert.deepEqual(check({ outcome: "fixed_interval", interval: "0" }).blockers, ["Fix the interval."]);
  assert.deepEqual(check({ outcome: "fixed_interval", interval: "0.5", intervalUnit: "years" }).blockers, []);
});

test("on condition with no interval: Apply stays on, with a quiet notice that no task is made", () => {
  const c = check({ outcome: "on_condition" });
  assert.deepEqual(c.blockers, []);
  assert.equal(c.intervalError, null);
  assert.equal(c.notice, "No task will be created: this decision will show as having no task. Say in the notes what covers it.");
  // Covered by another task, said in the notes: still allowed, still noted.
  assert.deepEqual(check({ outcome: "on_condition", notes: "Covered by the weekly walk-round" }).blockers, []);
  assert.match(check({ outcome: "on_condition", task: "Listen for noise" }).notice, /^No task will be created without an interval/);
  assert.equal(check({ outcome: "on_condition", interval: "1", intervalUnit: "weeks" }).notice, null);
});

test("run to failure needs its reason; nothing else", () => {
  assert.deepEqual(check({ outcome: "rtf" }).blockers, ["Choose why it can run to failure."]);
  assert.deepEqual(check({ outcome: "rtf", rtfBasis: "random" }).blockers, []);
  assert.deepEqual(check({ outcome: "rtf", rtfBasis: "uneconomic", interval: "" }).blockers, []);
  assert.deepEqual(check({ outcome: "redesign" }).blockers, []);
  assert.deepEqual(check({ outcome: "accept" }).blockers, []);
});

test("the Explorer's own limits: at most 100 years, 10 million units of use, notes of 4,000 characters", () => {
  const limits = { limits: true };
  assert.equal(check({ outcome: "fixed_interval", interval: "101", intervalUnit: "years" }, limits).intervalError, "The interval is at most 100 years.");
  assert.equal(check({ outcome: "fixed_interval", interval: "1300", intervalUnit: "months" }, limits).intervalError, "The interval is at most 100 years.");
  assert.equal(check({ outcome: "fixed_interval", interval: "100", intervalUnit: "years" }, limits).intervalError, null);
  assert.match(check({ outcome: "fixed_interval", interval: "20000000", intervalUnit: "hours" }, limits).intervalError, /^The interval is at most 10,000,000 hours/);
  assert.equal(check({ outcome: "fixed_interval", interval: "20000000", intervalUnit: "hours" }).intervalError, null); // a study takes it
  assert.deepEqual(check({ outcome: "accept", notes: "x".repeat(4001) }, limits).blockers, ["Shorten the notes to 4,000 characters or fewer."]);
  assert.deepEqual(check({ outcome: "accept", notes: "x".repeat(4000) }, limits).blockers, []);
});
