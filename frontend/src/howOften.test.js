import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addMonths, formFromPackage, formFromTask, howOftenPreview, howOftenProblem, howOftenWords, nextDates, packageBody, packageDates,
  patternOf, ruleDates, ruleOf, taskBody,
} from "./howOften.js";

const TODAY = "2026-11-14";

test("the first Saturday of each month, from 14 Nov 2026 (the server's Cadence gives the same)", () => {
  const rule = { kind: "monthly", every: 1, weekday: "Saturday", nth: 1 };
  assert.deepEqual(ruleDates(rule, TODAY, TODAY, 4), ["2026-12-05", "2027-01-02", "2027-02-06", "2027-03-06"]);
});

test("the first Tuesday of November every year", () => {
  const rule = { kind: "yearly", every: 1, month: 11, weekday: "Tuesday", nth: 1 };
  assert.deepEqual(ruleDates(rule, TODAY, TODAY), ["2027-11-02", "2028-11-07", "2029-11-06"]);
  assert.deepEqual(ruleDates({ ...rule, every: 2 }, TODAY, TODAY), ["2028-11-07", "2030-11-05", "2032-11-02"]);
});

test("a fifth Saturday skips the months with none; the last Friday; a short month's last day", () => {
  assert.deepEqual(ruleDates({ kind: "monthly", every: 1, weekday: "Saturday", nth: 5 }, "2027-01-01", "2027-01-01", 4),
    ["2027-01-30", "2027-05-29", "2027-07-31", "2027-10-30"]);
  assert.deepEqual(ruleDates({ kind: "monthly", every: 3, weekday: "Friday", nth: -1 }, TODAY, TODAY),
    ["2026-11-27", "2027-02-26", "2027-05-28"]);
  assert.deepEqual(ruleDates({ kind: "monthly", every: 1, day: 30 }, "2027-01-01", "2027-01-01"),
    ["2027-01-30", "2027-02-28", "2027-03-30"]);
  assert.deepEqual(ruleDates({ kind: "yearly", every: 1, month: 2, day: 29 }, "2027-01-01", "2027-01-01"),
    ["2027-02-28", "2028-02-29", "2029-02-28"]);
});

test("every 2 weeks on Saturday counts weeks from the anchor's week", () => {
  assert.deepEqual(ruleDates({ kind: "weekly", every: 2, weekdays: ["Saturday"] }, "2026-11-02", "2026-11-02"),
    ["2026-11-07", "2026-11-21", "2026-12-05"]);
});

test("a task's form, its words, its body and its next dates", () => {
  const form = formFromTask({ interval: 1, unit: "months", rule: { kind: "monthly", every: 1, weekday: "Saturday", nth: 1 } });
  assert.equal(patternOf(form), "nth");
  assert.equal(howOftenWords(form), "Every month on the first Saturday");
  assert.deepEqual(taskBody(form).rule, { kind: "monthly", every: 1, weekday: "Saturday", nth: 1 });
  assert.deepEqual(nextDates(form, { from: TODAY }), ["2026-12-05", "2027-01-02", "2027-02-06"]);
  // Last done on the first Saturday of November: the next is December's.
  assert.deepEqual(nextDates(form, { from: "2026-11-07", after: true, count: 1 }), ["2026-12-05"]);
  const yearly = { ...form, unit: "years", month: "11", weekday: "Tuesday" };
  assert.equal(howOftenWords(yearly), "Every year on the first Tuesday of November");
  assert.deepEqual(ruleOf(yearly), { kind: "yearly", every: 1, month: 11, weekday: "Tuesday", nth: 1 });
});

test("by use, with a calendar limit too", () => {
  const form = { ...formFromTask({ interval: 2000, unit: "hours" }), also: "12", alsoUnit: "months" };
  assert.equal(howOftenWords(form), "Every 2,000 operating hours, or every 12 months, whichever comes first");
  assert.equal(nextDates(form, { from: TODAY }), null);
  assert.deepEqual(taskBody(form), { interval: 2000, unit: "hours", also_interval: 12, also_unit: "months", rule: null });
  // A plain interval, both limits on the calendar: the sooner each time.
  const both = { ...formFromTask({ interval: 6, unit: "months" }), also: "20", alsoUnit: "weeks" };
  assert.deepEqual(nextDates(both, { from: TODAY }), ["2027-04-03", "2027-08-21", "2028-01-08"]);
});

test("problems are said in words", () => {
  const form = formFromTask({ interval: 1, unit: "months" });
  assert.equal(howOftenProblem({ ...form, every: "" }), "Say how often: a number more than 0.");
  assert.equal(howOftenProblem({ ...form, pattern: "day", day: "32" }), "The day of the month is 1 to 31.");
  assert.equal(howOftenProblem({ ...form, pattern: "nth", every: "1.5" }), "Every is a whole number here.");
  assert.equal(howOftenProblem({ ...form, also: "3", alsoUnit: "months" }).startsWith("The second limit needs"), true);
  assert.equal(howOftenProblem(form), null);
});

test("a package's cadence round-trips through the form", () => {
  const pkg = { cadence: { every: 1, unit: "years", weekday: "tuesday", nth: 1, month: 11, anchor: TODAY } };
  const form = formFromPackage(pkg);
  assert.deepEqual(packageBody(form), { every: 1, unit: "years", weekday: "tuesday", nth: 1, month: 11 });
  assert.deepEqual(packageDates(form, { anchor: TODAY, today: TODAY }), ["2027-11-02", "2028-11-07", "2029-11-06"]);
  const plain = formFromPackage({ cadence: { every: 2, unit: "weeks", anchor: "2026-11-02" } });
  assert.deepEqual(packageBody(plain), { every: 2, unit: "weeks", clear_pattern: true });
  assert.deepEqual(packageDates(plain, { anchor: "2026-11-02", today: TODAY }), ["2026-11-16", "2026-11-30", "2026-12-14"]);
  const monthly = formFromPackage({ cadence: { every: 1, unit: "months", anchor: "2027-01-31" } });
  assert.deepEqual(packageDates(monthly, { anchor: "2027-01-31", today: "2027-01-01" }), ["2027-01-31", "2027-02-28", "2027-03-31"]);
  assert.equal(addMonths("2027-01-31", 1), "2027-02-28");
});

test("what shows under it: dates, or the calendar limit's for a task by use", () => {
  const byUse = { ...formFromTask({ interval: 2000, unit: "hours" }), also: "12", alsoUnit: "months" };
  assert.deepEqual(howOftenPreview(byUse, { from: TODAY }), {
    dates: ["2027-11-14", "2028-11-14", "2029-11-14"], lead: "By the 12-month limit", note: "",
    after: "or sooner, when the meter gets there first.",
  });
  assert.equal(howOftenPreview({ ...byUse, also: "" }, { from: TODAY }).note, "By operating hours: its dates come from its meter readings.");
  assert.equal(howOftenPreview(formFromTask({ interval: 1, unit: "weeks" }), { from: TODAY }).dates[0], "2026-11-21");
});
