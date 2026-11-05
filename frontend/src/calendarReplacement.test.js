import { test } from "node:test";
import assert from "node:assert/strict";
import {
  buildRequest, dearer, formatDate, localToday, newShut, parseDates, timeUnit, visibleSchedule,
} from "./calendarReplacement.js";

const MODEL = { distribution_id: "weibull", params: [{ name: "alpha", value: 365 }, { name: "beta", value: 2 }] };

test("a model's unit as a time unit", () => {
  assert.equal(timeUnit("hrs"), "Hours");
  assert.equal(timeUnit("Days"), "Days");
  assert.equal(timeUnit("months"), "Months");
  assert.equal(timeUnit("Cycles"), "");
  assert.equal(timeUnit(""), "");
});

test("today is the viewer's own date, and dates read without a time zone shift", () => {
  assert.equal(localToday(new Date(2026, 9, 18, 23, 30)), "2026-10-18");
  assert.equal(formatDate("2027-03-17"), "17 Mar 2027");
  assert.equal(formatDate(null), "—");
});

test("dates typed one per line or comma-separated", () => {
  assert.deepEqual(parseDates("2027-01-26\n2027-12-12, 2028-12-25"), {
    dates: ["2027-01-26", "2027-12-12", "2028-12-25"], bad: [],
  });
  assert.deepEqual(parseDates("2027-01-26 soon").bad, ["soon"]);
});

test("the request: shuts every N units or on dates, the any-day cost optional", () => {
  const shuts = [
    { ...newShut("2026-10-18"), cost: "100", every: "6", everyUnit: "months" },
    { name: "Turnaround", cost: "50", how: "dates", dates: "2027-05-01\n2028-05-01" },
  ];
  const { body, error } = buildRequest({ model: MODEL, unit: "days", today: "2026-10-18", shuts, failureCost: "400",
                                         anytimeCost: "", maxAge: "", method: "dp" });
  assert.equal(error, undefined);
  assert.equal(body.unit, "Days");
  assert.equal(body.anytime_cost, null);
  assert.deepEqual(body.opportunities, [
    { name: "Annual shutdown", cost: 100, every: 6, every_unit: "months", start: "2026-10-18" },
    { name: "Turnaround", cost: 50, dates: ["2027-05-01", "2028-05-01"] },
  ]);
});

test("the request says what's missing", () => {
  const base = { model: MODEL, unit: "Days", today: "2026-10-18", shuts: [{ ...newShut("2026-10-18"), cost: "1" }],
                 failureCost: "400", anytimeCost: "" };
  assert.match(buildRequest({ ...base, model: null }).error, /non-repairable model/);
  assert.match(buildRequest({ ...base, unit: "Cycles" }).error, /time unit/);
  assert.match(buildRequest({ ...base, failureCost: "" }).error, /failure/);
  assert.match(buildRequest({ ...base, shuts: [{ ...newShut("x"), cost: "" }] }).error, /costs/);
  assert.match(buildRequest({ ...base, shuts: [{ name: "T", cost: "1", how: "dates", dates: "" }] }).error, /dates/);
  assert.match(buildRequest({ ...base, shuts: [] }).error, /Add a shut/);
  assert.equal(buildRequest({ ...base, shuts: [], anytimeCost: "150" }).error, undefined);
});

test("the schedule shows the likely replacements unless asked for all", () => {
  const rows = [{ chance: 0.96 }, { chance: 0 }, { chance: 0.0005 }];
  assert.equal(visibleSchedule(rows).length, 1);
  assert.equal(visibleSchedule(rows, true).length, 3);
  assert.equal(visibleSchedule([{ chance: 0 }]).length, 1);
  assert.equal(visibleSchedule([{ kind: "a", chance: 0 }, { kind: "b", chance: 0 }], false, ["a"]).length, 1);
});

test("how much dearer a rule is", () => {
  assert.equal(dearer(0.0082), "+0.8%");
  assert.equal(dearer(0.994), "+99%");
  assert.equal(dearer(0), "the same");
  assert.equal(dearer(null), "—");
});
