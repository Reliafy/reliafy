import test from "node:test";
import assert from "node:assert/strict";
import { CANCELLED_TEXT, cancelTarget, createRunGuard, jobFinished, newRunToken } from "./jobCancel.js";

test("run tokens are unique and URL-safe", () => {
  const a = newRunToken();
  const b = newRunToken();
  assert.notEqual(a, b);
  assert.match(a, /^[A-Za-z0-9]+$/);
});

test("a cancelled run's answer is ignored", () => {
  const g = createRunGuard();
  assert.equal(g.active, false);
  const t = g.start();
  assert.ok(g.isCurrent(t) && g.active);
  assert.equal(g.cancel(), t);
  assert.equal(g.isCurrent(t), false);
  assert.equal(g.active, false);
  assert.equal(g.cancel(), null); // nothing left to cancel
});

test("a new run supersedes the old one; finishing clears only its own run", () => {
  const g = createRunGuard();
  const first = g.start();
  const second = g.start();
  assert.equal(g.isCurrent(first), false);
  g.finish(first);
  assert.ok(g.isCurrent(second));
  g.finish(second);
  assert.equal(g.active, false);
  assert.equal(g.isCurrent(null), false);
});

test("cancel the job when queued, else the run token", () => {
  assert.equal(cancelTarget({ jobId: "j1", runToken: "t1" }), "j1");
  assert.equal(cancelTarget({ runToken: "t1" }), "t1");
  assert.equal(cancelTarget({}), null);
});

test("polling stops on done, failed and cancelled", () => {
  for (const s of ["done", "failed", "cancelled"]) assert.ok(jobFinished(s));
  for (const s of ["queued", "running", undefined]) assert.equal(jobFinished(s), false);
  assert.match(CANCELLED_TEXT, /^Cancelled/);
});
