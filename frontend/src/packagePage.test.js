import { test } from "node:test";
import assert from "node:assert/strict";
import {
  editBody, formProblem, initialForm, outcomeText, packageSentence, patternsFor, taskLabel, visitDay, visitTasksText,
} from "./packagePage.js";

const TODAY = "2026-11-10";
const PKG = {
  id: "p1", name: "Saturday round", status: "active", timing: "fixed", trade: "", notes: "",
  cadence: { every: 1, unit: "weeks", weekday: "saturday", text: "every Saturday" },
  tolerance: { amount: 1, unit: "days", enforced: true }, next_visit: "2026-11-14", open_work_order: null,
  tasks: [
    { task_id: "t1", name: "Check seal", visit_rule: "every", suppresses: [] },
    { task_id: "t2", name: "Grease", visit_rule: "nth", every_nth: 4, suppresses: [{ id: "t1", name: "Check seal" }] },
  ],
};

test("visitDay: a short day and date, the year only when it differs", () => {
  assert.equal(visitDay("2026-11-14", TODAY), "Sat 14 Nov");
  assert.equal(visitDay("2027-01-02", TODAY), "Sat 2 Jan 2027");
  assert.equal(visitDay(null), "");
});

test("packageSentence: the answer first", () => {
  assert.equal(packageSentence(PKG, TODAY), "Every Saturday, next visit Sat 14 Nov.");
  const late = { ...PKG, open_work_order: { number: 7, visit_on: "2026-11-07", late: true, days_late: 2, visits_missed: 1 } };
  assert.equal(packageSentence(late, TODAY), "Every Saturday, visit of Sat 7 Nov open (#7); 1 visit late, by 2 days.");
  const paused = { ...PKG, status: "paused", pause: { text: "paused until 1 Dec 2026" } };
  assert.equal(packageSentence(paused, TODAY), "Every Saturday; paused until 1 Dec 2026.");
  assert.equal(packageSentence({ ...PKG, status: "retired", retired_reason: "Sold" }, TODAY), "Retired: Sold. It visited every Saturday.");
  const layer = { ...PKG, parent: { id: "p0", name: "Weekly" }, cadence: { text: "every 4 weeks" } };
  assert.match(packageSentence(layer, TODAY), /^Every 4 weeks, on Weekly's visits, next visit Sat 14 Nov\.$/);
});

test("the form starts from the package and sends only what changed", () => {
  const form = initialForm(PKG);
  assert.equal(form.pattern, "weekday");
  assert.deepEqual(form.rules, { t1: { rule: "every", nth: "" }, t2: { rule: "nth", nth: "4" } });
  assert.deepEqual(editBody(PKG, form), {});
  assert.deepEqual(editBody(PKG, { ...form, name: " New name ", trade: "Fitter", notes: "Bring rags" }),
    { name: "New name", trade: "Fitter", notes: "Bring rags" });
  assert.deepEqual(editBody(PKG, { ...form, tolerance: "0" }), { tolerance: 0, tolerance_unit: "days" });
});

test("timing goes as a whole, its pattern replaced or cleared", () => {
  const form = initialForm(PKG);
  assert.deepEqual(editBody(PKG, { ...form, weekday: "monday" }),
    { timing: "fixed", every: 1, unit: "weeks", weekday: "monday" });
  assert.deepEqual(editBody(PKG, { ...form, unit: "months", pattern: "weekday", nth: "-1" }),
    { timing: "fixed", every: 1, unit: "months", weekday: "saturday", nth: -1 });
  assert.deepEqual(editBody(PKG, { ...form, unit: "months", pattern: "day", day: "15" }),
    { timing: "fixed", every: 1, unit: "months", day: 15 });
  assert.deepEqual(editBody(PKG, { ...form, timing: "from_last_visit", every: "2" }),
    { timing: "from_last_visit", every: 2, unit: "weeks", clear_pattern: true });
  assert.deepEqual(patternsFor({ timing: "fixed", unit: "days" }), ["none"]);
  assert.deepEqual(patternsFor({ timing: "fixed", unit: "months" }), ["weekday", "day"]);
});

test("visit rules: each changed task, its covers kept", () => {
  const form = initialForm(PKG);
  const body = editBody(PKG, { ...form, rules: { t1: { rule: "nth", nth: "2" }, t2: { rule: "every", nth: "" } } });
  assert.deepEqual(body.tasks, [
    { task_id: "t1", visit_rule: "nth", every_nth: 2, suppresses: [] },
    { task_id: "t2", visit_rule: "every", suppresses: ["t1"] },
  ]);
  assert.equal(editBody(PKG, { ...form, rules: { ...form.rules, t2: { rule: "nth", nth: "4" } } }).tasks, undefined);
});

test("a layer keeps fixed dates and has no tolerance of its own", () => {
  const layer = { ...PKG, parent: { id: "p0", name: "Weekly" } };
  const form = initialForm(layer);
  assert.deepEqual(editBody(layer, { ...form, every: "4", tolerance: "3" }),
    { timing: "fixed", every: 4, unit: "weeks", weekday: "saturday" });
});

test("formProblem says what to fix", () => {
  const form = initialForm(PKG);
  assert.equal(formProblem(form, PKG), null);
  assert.match(formProblem({ ...form, name: " " }, PKG), /name/);
  assert.match(formProblem({ ...form, every: "1.5" }, PKG), /whole number/);
  assert.match(formProblem({ ...form, tolerance: "-1" }, PKG), /On time within/);
  assert.match(formProblem({ ...form, rules: { ...form.rules, t2: { rule: "nth", nth: "1" } } }, PKG), /^Grease:/);
});

test("outcomeText", () => {
  assert.equal(outcomeText({ status: "open" }), "Open");
  assert.equal(outcomeText({ status: "in_progress", overdue: true }), "Open, late");
  assert.equal(outcomeText({ status: "closed", done: [{ kind: "inspect", finding: "ok" }] }), "Checked, nothing done");
  assert.equal(outcomeText({ status: "cancelled" }), "Cancelled");
});

test("the weekday the server capitalises starts the form unchanged", () => {
  const pkg = { ...PKG, cadence: { ...PKG.cadence, weekday: "Saturday" } };
  assert.equal(initialForm(pkg).weekday, "saturday");
  assert.deepEqual(editBody(pkg, initialForm(pkg)), {});
});

test("taskLabel and visitTasksText tell like tasks apart, and count them", () => {
  const tasks = [
    { task_id: "a", name: "Check seal", subject: { name: "Pump 1" } },
    { task_id: "b", name: "Check seal", subject: { name: "Pump 2" } },
    { task_id: "c", name: "Grease", subject: { name: "Pump 1" } },
  ];
  assert.equal(taskLabel(tasks[0], tasks), "Check seal · Pump 1");
  assert.equal(taskLabel(tasks[2], tasks), "Grease");
  assert.equal(visitTasksText(["a", "b", "c"], tasks), "Check seal ×2, Grease");
  assert.equal(visitTasksText(["x"], tasks), "");
});
