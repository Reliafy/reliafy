import test from "node:test";
import assert from "node:assert/strict";
import { dueText, madeTask, startBody, startWhy, takesStart } from "./taskStart.js";

test("dueText says the first due date set for a task, else the next due date", () => {
  assert.equal(dueText({ first_due: "2027-10-01", next_due: "2027-10-01" }), "first due 1 Oct 2027");
  assert.equal(dueText({ next_due: "2027-11-09" }), "next due 9 Nov 2027");
  assert.equal(dueText({ next_due: null }), "");
  assert.equal(dueText(null), "");
});

test("only a calendar task takes a start date", () => {
  assert.ok(takesStart({ unit: "months" }));
  assert.ok(takesStart({ unit: "hours", also_unit: "months" }));
  assert.ok(!takesStart({ unit: "hours" }));
  assert.ok(!takesStart(null));
});

test("startWhy accepts a date or nothing", () => {
  assert.equal(startWhy(""), "");
  assert.equal(startWhy("2027-10-01"), "");
  assert.match(startWhy("October"), /Enter a date/);
});

test("startBody sets or clears the start", () => {
  assert.deepEqual(startBody("2027-10-01"), { start: "2027-10-01" });
  assert.deepEqual(startBody(""), { start: null });
});

test("madeTask finds the task a save made, by name when several are new", () => {
  const after = { tasks: [{ id: "a", name: "Old" }, { id: "b", name: "Raise the dose" }, { id: "c", name: "Other" }] };
  assert.equal(madeTask(["a"], after, "raise the dose").id, "b");
  assert.equal(madeTask(["a", "b"], after, "nope").id, "c");
  assert.equal(madeTask(["a", "b", "c"], after, "x"), null);
  assert.equal(madeTask([], { decision: { tasks: [{ id: "d", name: "D" }] } }, "D").id, "d");
});
