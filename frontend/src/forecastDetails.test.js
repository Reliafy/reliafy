import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bars, columns, detailsCsv, emptyColumns, detailsQuery, everyFor, groupsFor, pageOf, rowLabel, treeSummary, whatText, whenText,
} from "./forecastDetails.js";

const CAL = {
  basis: "calendar", period: "month", start: "2026-12-01", end: "2027-01-31", subject: { kind: "task" },
  rows: [
    { start: "2026-12-01", end: "2026-12-31", tasks: 4, labour_hours: 2, labour_cost: 120, materials_cost: 40, visits_cost: 0, planned_cost: 160, total_cost: 160 },
    { start: "2027-01-01", end: "2027-01-31", tasks: 5, labour_hours: 2.5, labour_cost: 150, materials_cost: 50, visits_cost: 0, planned_cost: 200, total_cost: 200 },
  ],
  totals: { tasks: 9, labour_hours: 4.5, labour_cost: 270, materials_cost: 90, visits_cost: 0, planned_cost: 360, total_cost: 360, failures: null },
};

test("the query asks for what the controls say, and for one task or package", () => {
  assert.deepEqual(detailsQuery({ root: "r", subject: { kind: "task", taskId: "t1" }, basis: "calendar", months: "12", group: "month" }),
    { root: "r", basis: "calendar", task_id: "t1", period: "month", months: "12" });
  assert.deepEqual(detailsQuery({ subject: { kind: "package", packageId: "p1" }, basis: "calendar", months: "custom", end: "2027-03-31", group: "week" }),
    { root: null, basis: "calendar", package_id: "p1", period: "week", end: "2027-03-31" });
  assert.deepEqual(detailsQuery({ subject: { kind: "level" }, basis: "hours", hours: "1000", every: "100", reading: "" }),
    { root: null, basis: "hours", hours: "1000", every: "100", reading: null });
  // First read: no basis, so the server picks (a duty: the calendar).
  assert.deepEqual(detailsQuery({ subject: { kind: "level" } }), { root: null, basis: null });
});

test("day grouping is offered up to about a year, and hours rows stay under 400", () => {
  assert.equal(groupsFor("12").find((g) => g.value === "day").disabled, undefined);
  assert.equal(groupsFor("24").find((g) => g.value === "day").disabled, true);
  assert.equal(everyFor("40000").find((e) => e.value === "50").disabled, true);
  assert.equal(everyFor("40000").find((e) => e.value === "100").disabled, undefined);
});

test("rows are labelled by period or by running hours", () => {
  assert.equal(rowLabel(CAL, CAL.rows[0], 0), "Dec 2026");
  assert.equal(rowLabel({ basis: "calendar", period: "week" }, { start: "2026-12-01" }, 0), "From 1 Dec 2026");
  assert.equal(rowLabel({ basis: "calendar", period: "week" }, { start: "2026-12-07" }, 1), "Week of 7 Dec 2026");
  assert.equal(rowLabel({ basis: "calendar", period: "day" }, { start: "2026-12-07" }, 1), "Mon 7 Dec 2026");
  assert.equal(rowLabel({ basis: "hours" }, { from_hours: 0, to_hours: 100 }, 0), "0 to 100 h");
});

test("failure columns show only with a life, saying their range is 90% two-sided", () => {
  assert.equal(columns(CAL).some((c) => c.id === "failures"), false);
  const withLife = { ...CAL, totals: { ...CAL.totals, failures: 0.6 } };
  const f = columns(withLife).find((c) => c.id === "failures");
  assert.match(f.title, /90% two-sided/);
  assert.equal(f.cell({ failures: 0.62, failures_range: [0, 1] }), "0.62 (0 to 1)");
});

test("a cost column nothing has is left out and named", () => {
  const bare = { ...CAL, totals: { ...CAL.totals, labour_hours: 0, labour_cost: null, visits_cost: 0 } };
  assert.deepEqual(columns(bare).map((c) => c.id), ["tasks", "materials_cost", "planned_cost", "total_cost"]);
  assert.deepEqual(emptyColumns(bare), ["labour", "labour cost", "visit costs"]);
});

test("the CSV has a line a row and the totals", () => {
  const csv = detailsCsv(CAL).trim().split("\n");
  assert.equal(csv.length, 4);
  assert.equal(csv[0], "period,start,end,tasks,labour_hours,labour_cost,materials_cost,planned_cost,total_cost");
  assert.equal(csv[1], "Dec 2026,2026-12-01,2026-12-31,4,2,120,40,160,160");
  assert.equal(csv[3], "In all,2026-12-01,2027-01-31,9,4.5,270,90,360,360");
});

test("When next pages 20 at a time and stays in range", () => {
  const list = Array.from({ length: 45 }, (_, i) => i);
  assert.deepEqual(pageOf(list, 0), { items: list.slice(0, 20), page: 0, pages: 3, from: 1, to: 20, total: 45 });
  assert.equal(pageOf(list, 2).items.length, 5);
  assert.equal(pageOf(list, 9).page, 2);
  assert.deepEqual(pageOf([], 0), { items: [], page: 0, pages: 1, from: 0, to: 0, total: 0 });
});

test("each time done says when and what", () => {
  assert.equal(whenText(CAL, { date: "2026-12-24", moment: "2026-12-24T08:00" }), "Thu 24 Dec 2026 at 08:00");
  assert.equal(whenText({ basis: "hours", reading: 1180 }, { hours: 70 }), "in 70 h (1,250 h on the meter)");
  assert.equal(whatText({ kind: "visit", name: "50 h service", tasks: [{ name: "Change oil" }, { name: "Grease deck" }] }),
    "50 h service visit: Change oil, Grease deck");
  assert.equal(whatText({ kind: "task", name: "Grease deck", package: { name: "50 h service" } }), "Grease deck (on the 50 h service visit)");
});

test("the bars are each row's count", () => {
  assert.deepEqual(bars(CAL), { counts: [4, 5], max: 5 });
  assert.deepEqual(bars({ rows: [] }), { counts: [], max: 1 });
});

test("the Forecast row's summary: next, how many a year and the cost a year; not dated says why", () => {
  const d = {
    tasks: [{ id: "a", dates: ["2026-12-05", "2027-01-05"], count: 12, cost_each: 103.33, overdue: false }],
    not_placed: [{ task: { id: "b" }, reason: "every 250 h, not dated: set a duty in Operations" }],
    occurrences: [],
  };
  assert.equal(treeSummary(d, ["a"]), "next 5 Dec 2026 · 12 times a year · $1,240 a year");
  assert.equal(treeSummary(d, ["b"]), "every 250 h, not dated: set a duty in Operations");
  assert.equal(treeSummary(d, ["a", "b"]), "next 5 Dec 2026 · 12 times a year · $1,240 a year · 1 not dated");
  assert.equal(treeSummary({ tasks: [], not_placed: [] }, ["a"]), "None due in the next year");
});
