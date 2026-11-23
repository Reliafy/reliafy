import test from "node:test";
import assert from "node:assert/strict";
import { convertPeriod, itemsOnFleetRate, itemsWithoutUsage, periodDays, periodsText, usageInputValue } from "./fleetUsage.js";

const items = [
  { name: "Pump 1", current_use: 300, rate: null },
  { name: "Pump 2", current_use: 700 },
];

test("a new forecast (usage 0) with items is missing usage", () => {
  const settings = { default_rate: 0, periods: 12, period_label: "months" };
  assert.equal(itemsWithoutUsage(settings, items), 2);
  assert.equal(itemsWithoutUsage({ ...settings, default_rate: "" }, items), 2);
  assert.equal(itemsWithoutUsage({ ...settings, default_rate: "0" }, items), 2);
  assert.equal(itemsWithoutUsage({}, items), 2);
});

test("a usage per period, or every item's own rate, is enough", () => {
  assert.equal(itemsWithoutUsage({ default_rate: 100 }, items), 0);
  assert.equal(itemsWithoutUsage({ default_rate: "0.5" }, items), 0);
  const own = items.map((it, i) => ({ ...it, rate: i === 0 ? "40" : 0 }));
  assert.equal(itemsWithoutUsage({ default_rate: 0 }, own), 0);
});

test("no items: nothing is missing", () => {
  assert.equal(itemsWithoutUsage({ default_rate: 0 }, []), 0);
});

test("estimated rates count only when rates come from API readings", () => {
  const est = [{ name: "A", rate: null, estimated_rate: 12, estimated_rate_n: 2 }, { name: "B", rate: null }];
  assert.equal(itemsOnFleetRate({ rate_source: "estimated" }, est).length, 1);
  assert.equal(itemsWithoutUsage({ default_rate: 0, rate_source: "estimated" }, est), 1);
  assert.equal(itemsWithoutUsage({ default_rate: 0, rate_source: "manual" }, est), 2);
});

test("the usage box shows a stored 0 as blank but keeps a typed 0", () => {
  assert.equal(usageInputValue(0), "");
  assert.equal(usageInputValue(null), "");
  assert.equal(usageInputValue(undefined), "");
  assert.equal(usageInputValue("0"), "0");
  assert.equal(usageInputValue(500), 500);
});

test("months to quarters: usage scales up, counts of periods scale down", () => {
  const settings = { default_rate: 730, periods: 12, period_label: "months", spares: { lead_time: 3, review: "" } };
  const out = convertPeriod(settings, [{ name: "A", rate: 100 }, { name: "B", rate: null }], "months", "quarters");
  assert.equal(out.settings.default_rate, 2190);
  assert.equal(out.settings.periods, 4);
  assert.equal(out.settings.period_label, "quarters");
  assert.equal(out.settings.spares.lead_time, 1);
  assert.equal(out.settings.spares.review, "");
  assert.equal(out.items[0].rate, 300);
  assert.equal(out.items[1].rate, null);
  // The same calendar span at the same usage: 730 h a month for 12 months is
  // 8,760 h, and so is 2,190 h a quarter for 4 quarters.
  assert.equal(out.settings.default_rate * out.settings.periods, 730 * 12);
});

test("back again, and to years", () => {
  const q = { default_rate: 2190, periods: 4, period_label: "quarters" };
  assert.equal(convertPeriod(q, [], "quarters", "months").settings.default_rate, 730);
  const y = convertPeriod({ default_rate: 730, periods: 24, period_label: "months" }, [], "Months", "year");
  assert.equal(y.settings.default_rate, 8760);
  assert.equal(y.settings.periods, 2);
});

test("no calendar length, or the same period: nothing to convert", () => {
  const s = { default_rate: 730, periods: 12, period_label: "months" };
  assert.equal(convertPeriod(s, [], "months", "cycles"), null);
  assert.equal(convertPeriod(s, [], "shifts", "quarters"), null);
  assert.equal(convertPeriod(s, [], "months", "month"), null);
  assert.equal(periodDays("Quarters"), 91.3125);
});

// Regression check: usage and horizon typed in months, then the period set to
// years, read "1 years" (5 months rounded up to a year). A horizon converts only
// when it is a whole number of the new period; otherwise nothing changes and
// the page says why.
test("a horizon that isn't a whole number of the new period isn't changed", () => {
  const typed = { default_rate: 1, periods: 5, period_label: "months" };
  const out = convertPeriod(typed, [{ name: "A", rate: 2 }], "months", "years");
  assert.equal(out.settings, undefined);
  assert.equal(out.blocked,
    "5 months isn't a whole number of years, so the period stays months. Make the horizon a multiple of 12 first (12 months is 1 year).");
  // 12 or 24 months are exact: 1 and 2 years, with the usage per year exact too.
  const year = convertPeriod({ ...typed, periods: 12 }, [], "months", "years");
  assert.equal(year.settings.periods, 1);
  assert.equal(year.settings.default_rate, 12);
  assert.equal(convertPeriod({ ...typed, periods: 24 }, [], "months", "year").settings.periods, 2);
  // Near a whole number is the same span: 3 months is 91 days, 5 months 22 weeks.
  assert.equal(convertPeriod({ ...typed, periods: 3 }, [], "months", "days").settings.periods, 91);
  assert.match(convertPeriod({ ...typed, periods: 12 }, [], "months", "days").blocked, /365 days, more than a forecast's 120/);
  assert.equal(convertPeriod(typed, [], "months", "weeks").settings.periods, 22);
  assert.ok(convertPeriod(typed, [], "months", "quarters").blocked);
  // Quarters to months is always whole.
  assert.ok(convertPeriod({ ...typed, periods: 2 }, [], "quarters", "months").settings.periods === 6);
});

test("a count of periods reads in the right number", () => {
  assert.equal(periodsText(1, "years"), "1 year");
  assert.equal(periodsText(5, "months"), "5 months");
  assert.equal(periodsText(2, "Year"), "2 Years");
  assert.equal(periodsText(1, "cycles"), "1 cycle");
  assert.equal(periodsText(3, "shifts"), "3 shifts");
});
