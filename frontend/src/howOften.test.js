import { test } from "node:test";
import assert from "node:assert/strict";
import {
  formFromPackage, formFromTask, howOftenProblem, packageBody, previewFor, ruleOf, stepChoices, taskBody, typesFor,
} from "./howOften.js";

const TODAY = "2026-12-01";

test("the types offered: running hours only with a unit of use, a rule only with patterns, shutdowns on a position", () => {
  const all = ["days", "weeks", "months", "years", "hours", "km"];
  assert.deepEqual(typesFor(all, { shutdowns: true }).map((t) => t.value), ["hours", "interval", "rule", "shutdowns"]);
  assert.deepEqual(typesFor(["days", "weeks", "months", "years"]).map((t) => t.value), ["interval", "rule"]);
  assert.deepEqual(typesFor(["weeks", "months"], { patterns: false }).map((t) => t.value), ["interval"]);
});

test("a task on the first Saturday of every month: its form, its rule and its body", () => {
  const form = formFromTask({ interval: 1, unit: "months", rule: { kind: "monthly", every: 1, weekday: "Saturday", nth: 1 } });
  assert.equal(form.type, "rule");
  assert.equal(form.step, "months:1");
  assert.deepEqual(ruleOf(form), { kind: "monthly", every: 1, weekday: "Saturday", nth: 1 });
  assert.deepEqual(taskBody(form, TODAY), { interval: 1, unit: "months", also_interval: 0, also_unit: null,
    rule: { kind: "monthly", every: 1, weekday: "Saturday", nth: 1, anchor: TODAY } });
});

test("1 March and 1 September; the last day of each quarter; every second Tuesday", () => {
  const base = formFromTask({ interval: 1, unit: "months" });
  const marSep = { ...base, type: "rule", step: "months:6", pattern: "day", day: "1", startMonth: "3" };
  assert.deepEqual(ruleOf(marSep, TODAY), { kind: "monthly", every: 6, day: 1, anchor: "2026-03-01" });
  const quarter = { ...base, type: "rule", step: "months:3", pattern: "lastday", startMonth: "3" };
  assert.deepEqual(ruleOf(quarter, TODAY), { kind: "monthly", every: 3, day: 31, anchor: "2026-03-01" });
  const tuesdays = { ...base, type: "rule", step: "weeks:2", pattern: "weekday", weekday: "Tuesday" };
  assert.deepEqual(ruleOf(tuesdays, TODAY), { kind: "weekly", every: 2, weekdays: ["Tuesday"], anchor: TODAY });
  // A saved rule reads back the same.
  assert.equal(formFromTask({ interval: 3, unit: "months", rule: { kind: "monthly", every: 3, day: 31, anchor: "2026-03-01" } }).pattern, "lastday");
  assert.equal(formFromTask({ interval: 6, unit: "months", rule: { kind: "monthly", every: 6, day: 1, anchor: "2026-03-01" } }).startMonth, "3");
  // The last day of February each year is the 29th (a leap year's; the 28th in others).
  assert.equal(ruleOf({ ...base, type: "rule", step: "years:1", pattern: "lastday", month: "2" }).day, 29);
});

test("at shutdowns: its rule, its body and its preview needs the position", () => {
  const form = formFromTask({ interval: 12, unit: "months", rule: { kind: "shutdowns", every: 12, unit: "months" } });
  assert.equal(form.type, "shutdowns");
  assert.deepEqual(taskBody(form).rule, { kind: "shutdowns", every: 12, unit: "months" });
  assert.equal(previewFor(form, { from: TODAY }).request, null);
  assert.deepEqual(previewFor(form, { from: TODAY, positionId: "p1" }).request,
    { start: TODAY, after: false, count: 5, rule: { kind: "shutdowns", every: 12, unit: "months" }, position_id: "p1" });
  assert.equal(howOftenProblem({ ...form, every: "1.5" }), "Give a whole number here.");
});

test("by use, with a calendar limit too: the preview asks for the calendar limit's dates", () => {
  const form = { ...formFromTask({ interval: 2000, unit: "hours" }), also: "12", alsoUnit: "months" };
  assert.equal(form.type, "hours");
  assert.deepEqual(taskBody(form), { interval: 2000, unit: "hours", also_interval: 12, also_unit: "months", rule: null });
  const p = previewFor(form, { from: TODAY });
  assert.deepEqual(p.request.rule, { kind: "every", every: 12, unit: "months" });
  assert.equal(p.lead, "By the 12-month limit");
  assert.match(previewFor({ ...form, also: "" }, { from: TODAY }).note, /^By operating hours/);
  // A plain interval with a second calendar limit: both go to the server, the sooner each time.
  const both = { ...formFromTask({ interval: 6, unit: "months" }), also: "20", alsoUnit: "weeks" };
  assert.deepEqual(previewFor(both, { from: TODAY, after: true }).request,
    { start: TODAY, after: true, count: 5, rule: { kind: "every", every: 6, unit: "months" }, also: { every: 20, unit: "weeks" } });
  // A part month goes as days.
  assert.deepEqual(previewFor({ ...both, every: "1.5", also: "" }, { from: TODAY }).request.rule, { kind: "every", every: 46, unit: "days" });
});

test("problems are said in words", () => {
  const form = formFromTask({ interval: 1, unit: "months" });
  assert.equal(howOftenProblem({ ...form, every: "" }), "Say how often: a number more than 0.");
  assert.equal(howOftenProblem({ ...form, type: "rule", pattern: "day", day: "32" }), "The day of the month is 1 to 31.");
  assert.equal(howOftenProblem({ ...form, also: "3", alsoUnit: "months" }).startsWith("The second limit needs"), true);
  assert.equal(howOftenProblem(form), null);
  assert.equal(previewFor({ ...form, every: "" }, { from: TODAY }).request, null);
});

test("a package's cadence round-trips through the form", () => {
  const pkg = { cadence: { every: 1, unit: "years", weekday: "tuesday", nth: 1, month: 11, anchor: TODAY } };
  const form = formFromPackage(pkg);
  assert.deepEqual(packageBody(form), { every: 1, unit: "years", weekday: "tuesday", nth: 1, month: 11 });
  const plain = formFromPackage({ cadence: { every: 2, unit: "weeks", anchor: "2026-11-02" } });
  assert.deepEqual(packageBody(plain), { every: 2, unit: "weeks", clear_pattern: true });
  // On set dates, a plain interval counts from its anchor.
  assert.deepEqual(previewFor(plain, { from: TODAY, anchor: "2026-11-02", fixed: true }).request.rule,
    { kind: "every", every: 2, unit: "weeks", anchor: "2026-11-02" });
});

test("a rule's step not in the list (every 9 weeks, from Optimise) is still offered", () => {
  assert.equal(stepChoices("weeks:9").at(-1)[1], "every 9 weeks");
  assert.equal(stepChoices("months:1").length, stepChoices(null).length);
});
