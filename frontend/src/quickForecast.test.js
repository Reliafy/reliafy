import { test } from "node:test";
import assert from "node:assert/strict";
import { BLANK, BLANK_WORK, answerOf, boundText, formFromStart, lineCells, missing, requestOf, seriesOf } from "./quickForecast.js";

const WEIBULL = { distribution_id: "weibull", params: [{ name: "alpha", value: 14000 }, { name: "beta", value: 2.2 }], name: "Engine" };

test("schedule only needs no model; the running and horizon are one sentence", () => {
  const f = { ...BLANK, runPer: "week", runHours: "12", work: { ...BLANK_WORK, name: "Grease", every: "50", hoursEach: "0.2" } };
  assert.equal(missing(f, null, ""), null);
  const body = requestOf(f, null, "", "2026-11-24");
  assert.deepEqual(body.running, { hours: 12, per: "week" });
  assert.equal(body.months, 12);
  assert.equal(body.start, "2026-11-24");
  assert.deepEqual(body.work, { name: "Grease", every: 50, unit: "hours", effect: "none", hours_each: 0.2, cost_each: null,
    spares_each: null, spare_name: null });
  assert.equal(body.part, undefined);
});

test("what's missing is said in words", () => {
  assert.match(missing(BLANK, null, ""), /Add work on a schedule/);
  assert.match(missing({ ...BLANK, runPer: "day", runHours: "30", work: { ...BLANK_WORK, every: "5" } }, null, ""), /24 h a day/);
  assert.match(missing({ ...BLANK, work: { ...BLANK_WORK } }, null, ""), /how often/);
  assert.match(missing({ ...BLANK, part: true }, null, ""), /Pick a saved model/);
  assert.match(missing({ ...BLANK, part: true }, WEIBULL, "hours"), /how old the part is now/);
  assert.match(missing({ ...BLANK, part: true, ages: "10" }, WEIBULL, "cycles"), /cycles a unit adds a day/);
  // Work that replaces the part needs one.
  assert.match(missing({ ...BLANK, work: { ...BLANK_WORK, every: "100", effect: "replaces" } }, null, ""), /needs a part/);
});

test("a part with a list of ages counts the units; replaces only with a part", () => {
  const f = { ...BLANK, part: true, ages: "120 900 1,450", costIfFails: "900", work: { ...BLANK_WORK, every: "100", effect: "replaces" } };
  const body = requestOf(f, WEIBULL, "hours");
  assert.deepEqual(body.part.ages, [120, 900, 1450]);
  assert.equal(body.units, 3);
  assert.equal(body.part.cost_if_fails, 900);
  assert.equal(body.work.effect, "replaces");
  const noPart = requestOf({ ...f, part: false }, WEIBULL, "hours");
  assert.equal(noPart.work.effect, "none");
});

test("filled in from the Explorer: duty, ages, the task's needs", () => {
  const f = formFromStart({ hours_per_day: 20, model: { id: "m" }, ages: [9000], failure_cost: 180000,
    task: { name: "Replace engine", interval: 9000, unit: "hours" }, replace_at: 9000, planned_cost: 50000, planned_hours: 40 });
  assert.equal(f.runPer, "day");
  assert.equal(f.runHours, "20");
  assert.equal(f.part, true);
  assert.equal(f.ages, "9000");
  assert.equal(f.costIfFails, "180000");
  assert.equal(f.work.effect, "replaces");
  assert.equal(f.work.costEach, "50000");
});

const OUT = {
  status: "ok", units: 1, months: 12, period_label: "months", running: { text: "20 h a day" },
  no_failure_before: { in_life_unit: 1063, days: 53.2 },
  lines: [
    { id: "work", owner: "Change engine oil", owner_kind: "task", number: "certain", times: { expected: 29 },
      every: { value: 250, unit: "hours" }, hours: { expected: 43.5 }, cost: { expected: 16312.5 }, spares: null,
      gaps: [{ view: "spares", text: "no spares each time" }] },
    { id: "failures", owner: "Engine", owner_kind: "failure", number: "simulated", method: "Simulated: 2,000 seeded runs",
      times: { expected: 0.69, interval: [0, 1], probability: 0.64 }, hours: null, cost: { expected: 124200, interval: [0, 180000] },
      spares: { expected: 0.69, interval: [0, 1] }, gaps: [{ view: "hours", text: "no hours if it fails" }] },
  ],
  totals: { hours: { expected: 43.5, interval: [43.5, 43.5], known: false, leaves_out: ["Engine failures (no hours if it fails)"] },
    cost: { expected: 140512.5, interval: [16312.5, 196312.5], known: true, leaves_out: [] },
    spares: { items: [{ name: "replacement part (Engine)", expected: 0.69, interval: [0, 1], number: "simulated" }], known: false, leaves_out: [] } },
  rows: [{ period: 1, work: 2, failures: 0.05, hours: 3, cost: 10000 }],
  part: { views: { costs: { per_period: [{ cost: { expected: 9000, interval: [0, 0] } }] } }, strategy: { per_period: [{ parts: { expected: 0.05, interval: [0, 0] } }] } },
};
const money = (v) => `$${Math.round(v).toLocaleString("en-GB")}`;

test("the answer leads with the view's total; gaps make it the known total", () => {
  const c = answerOf(OUT, "costs", money);
  assert.equal(c.lead, "$140,513 expected in the next 12 months.");
  assert.deepEqual(c.detail[0], { label: "Likely range (90% two-sided)", value: "$16,313 to $196,313" });
  const h = answerOf(OUT, "hours", money);
  assert.match(h.lead, /known hours/);
  assert.deepEqual(h.leavesOut, ["Engine failures (no hours if it fails)"]);
  assert.match(answerOf(OUT, "spares", money).lead, /0\.69 × replacement part \(Engine\) \(0 to 1, 90% two-sided\)/);
  // One unit, a part only, under one failure expected: the chance leads.
  const only = { ...OUT, lines: [OUT.lines[1]] };
  assert.match(answerOf(only, "costs", money).lead, /^64% chance it fails in the next 12 months/);
  // Schedule only: times first.
  const sched = { ...OUT, lines: [OUT.lines[0]], totals: { ...OUT.totals, hours: { expected: 43.5, interval: [43.5, 43.5], known: true, leaves_out: [] } } };
  assert.equal(answerOf(sched, "hours").lead, "29 times in the next 12 months: 43.5 h.");
  assert.equal(boundText(OUT), "90% chance of no failure before month 2 (90% one-sided).");
});

test("a line's cells: certain has no range; a gap says not given", () => {
  assert.deepEqual(lineCells(OUT.lines[0], "costs", money), { times: "29", amount: "$16,313", gap: null });
  const f = lineCells(OUT.lines[1], "hours", money);
  assert.equal(f.amount, null);
  assert.equal(f.gap, "no hours if it fails");
  assert.equal(lineCells(OUT.lines[1], "costs", money).times, "0.69 expected (0 to 1)");
});

test("by period: the certain work is added to both ends of the part's range", () => {
  const [r] = seriesOf(OUT, "costs");
  assert.equal(r.value, 10000);
  assert.equal(r.low, 1000);
  assert.equal(r.high, 1000);
});
