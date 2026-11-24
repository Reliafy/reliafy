import { test } from "node:test";
import assert from "node:assert/strict";
import { answerText, groupsFor, isHours, missing, parseAges, periodsOf, ratePerPeriod, requestOf, rowsOf, whenNext, whenText } from "./sparesForecast.js";

const model = { source: "params", distribution_id: "weibull", params: [{ name: "alpha", value: 1200 }, { name: "beta", value: 2.5 }] };
const form = { ages: "500", units: "10", perDay: "8", daysWeek: "5", group: "months", horizon: "12", policy: "failure",
  replaceAt: "", failureCost: "", plannedCost: "", spares: {} };

test("ages: one for them all, or a list; thousands stay one number", () => {
  assert.deepEqual(parseAges("500").ages, [500]);
  assert.deepEqual(parseAges("100, 900 1,500\n2000;30").ages, [100, 900, 1500, 2000, 30]);
  assert.match(parseAges("").error, /age now/);
  assert.match(parseAges("ten").error, /isn't a number/);
  assert.match(parseAges("-5").error, /negative/);
});

test("the horizon splits into whole periods; use a period from the use a day and the days a week", () => {
  assert.deepEqual(groupsFor("12").map((g) => g.value), ["months", "quarters", "years"]);
  assert.deepEqual(groupsFor("12").length, 3);
  assert.equal(periodsOf("24", "quarters"), 8);
  assert.equal(periodsOf("12", "years"), 1);
  // 8 h a day, 5 days a week, over a month of 30.4375 days: about 174 h.
  assert.equal(Math.round(ratePerPeriod(8, 5, "months") * 100) / 100, 173.93);
  assert.ok(isHours("hours") && isHours("Operating hours") && !isHours("cycles"));
});

test("what's missing is said before Forecast runs", () => {
  assert.match(missing(form, null, "hours"), /Pick a saved model/);
  assert.match(missing(form, model, ""), /unit/);
  assert.match(missing({ ...form, perDay: "" }, model, "hours"), /hours a unit runs a day/);
  assert.match(missing({ ...form, perDay: "" }, model, "cycles"), /cycles a unit adds a day/);
  assert.match(missing({ ...form, policy: "age" }, model, "hours"), /age to replace at, in hours/);
  assert.match(missing({ ...form, daysWeek: "8" }, model, "hours"), /1 to 7/);
  assert.equal(missing(form, model, "hours"), null);
});

test("the request: one age with a count, or a list; a planned policy with its age and price", () => {
  const one = requestOf(form, model, "hours");
  assert.equal(one.ages, 500);
  assert.equal(one.units, 10);
  assert.equal(one.periods, 12);
  assert.equal(one.strategy, "run_to_failure");
  assert.equal(one.replace_at, null);
  assert.equal(one.spares, null);
  const list = requestOf({ ...form, ages: "100 900", policy: "age", replaceAt: "800", plannedCost: "300", spares: { lead_time: 2 } }, model, "hours");
  assert.deepEqual([list.ages, list.units, list.strategy, list.replace_at, list.planned_cost], [[100, 900], 2, "age", 800, 300]);
  assert.deepEqual(list.spares, { lead_time: 2 });
});

test("when next: the period each of the first spares is likely used, from the expected counts", () => {
  const fc = { periods: 4, period_label: "months", per_period: [0.6, 0.6, 1.2, 0.2], expected: 2.6 };
  const w = whenNext(fc);
  assert.deepEqual(w.items, [{ n: 1, period: 2 }, { n: 2, period: 3 }]);
  assert.equal(w.more, 0);
  assert.equal(whenText(fc, w.items[0]), "Spare 1 · month 2");
  // A planned policy counts its planned replacements too.
  const st = { kind: "age", per_period: [{ period: 1, parts: { expected: 3 } }, { period: 2, parts: { expected: 25 } }],
    total: { failures: { expected: 8 }, planned: { expected: 20 } } };
  const many = whenNext({ ...fc, strategy: st, periods: 2 }, 20);
  assert.equal(many.items.length, 20);
  assert.equal(many.more, 8);
  assert.deepEqual(answerText({ ...fc, strategy: st, periods: 2 }), { parts: "28", horizon: "2 months", failures: "8", planned: "20" });
  assert.equal(answerText({ ...fc, periods: 1 }).horizon, "1 month");
  assert.equal(rowsOf(fc).length, 4);
});
