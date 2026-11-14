import { test } from "node:test";
import assert from "node:assert/strict";
import { dayRuns, formFromPlan, hoursByDay, hoursWords, parseRuns, planFromForm, planWords, typicalWeek } from "./operatingPlan.js";

const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-9, `${a} ≠ ${b}`);

test("specific runs hand over to the background with no extra hours (the server gives the same)", () => {
  // Runs end Tue 03:30; the background is 3 h a day: Tue = 3.5 h of runs + 3 × 20.5 / 24.
  const form = { ...formFromPlan(null, "2026-11-14"), kind: "rate", rate: { amount: "3", per: "day" },
    specific: "2026-11-14 12:31, 2026-11-15 03:27\n2026-11-16 12:30\t2026-11-17 03:30" };
  const { plan, problem } = planFromForm(form);
  assert.equal(problem, undefined);
  assert.deepEqual(plan.specific[0].covers, ["2026-11-14T00:00", "2026-11-17T03:30"]);
  const days = Object.fromEntries(hoursByDay(plan, "2026-11-13", 6).map((d) => [d.date, d]));
  close(days["2026-11-13"].hours, 3);
  close(days["2026-11-14"].hours, 11 + 29 / 60);
  close(days["2026-11-15"].hours, 3 + 27 / 60);
  close(days["2026-11-17"].hours, 3.5 + 3 * 20.5 / 24);
  close(days["2026-11-18"].hours, 3);
  for (const d of Object.values(days)) close(d.hours, d.runs.reduce((t, r) => t + r.to - r.from, 0) + d.spread);
});

test("a repeating week: 80 hours, clipped where set runs cover, overnight shifts carry over", () => {
  const form = formFromPlan(null, "2026-11-14");
  const { plan } = planFromForm(form);
  assert.equal(typicalWeek(plan), 80);
  assert.equal(hoursWords(typicalWeek(plan)), "about 80 hours a week");
  assert.equal(planWords(plan), "Monday to Friday, 06:00 to 22:00");
  const night = planFromForm({ ...form, shifts: [{ days: ["Friday"], start: "22:00", stop: "06:00" }] }).plan;
  assert.deepEqual(dayRuns(night, "2026-11-21").runs, [{ from: 0, to: 6, layer: "background" }]); // Saturday
  assert.equal(dayRuns(night, "2026-11-20").hours, 2); // Friday 22:00 to midnight
});

test("rosters, all the time, and runs only", () => {
  const base = formFromPlan(null, "2026-11-16");
  const roster = planFromForm({ ...base, kind: "roster" }).plan;
  close(typicalWeek(roster), 42);
  assert.equal(dayRuns(roster, "2026-11-19").hours, 12); // the 4th day on
  assert.equal(dayRuns(roster, "2026-11-20").hours, 0); // the 1st day off
  assert.equal(typicalWeek(planFromForm({ ...base, kind: "continuous" }).plan), 168);
  const runs = planFromForm({ ...base, kind: "runs", runs: "On,Off\n14/11/2026 12:31,15/11/2026 03:27" }).plan;
  assert.deepEqual(runs.background.runs, [["2026-11-14T12:31", "2026-11-15T03:27"]]);
  assert.equal(typicalWeek(runs), null);
  close(dayRuns(runs, "2026-11-15").hours, 3.45);
});

test("problems are said in words", () => {
  const base = formFromPlan(null, "2026-11-16");
  assert.match(planFromForm({ ...base, kind: "rate", rate: { amount: "30", per: "day" } }).problem, /only 24 hours/);
  assert.match(planFromForm({ ...base, shifts: [{ days: [], start: "06:00", stop: "22:00" }] }).problem, /tick the days/);
  assert.match(planFromForm({ ...base, shifts: [{ days: ["Monday"], start: "06:00", stop: "14:00" },
    { days: ["Monday"], start: "12:00", stop: "20:00" }] }).problem, /overlap/);
  assert.match(planFromForm({ ...base, kind: "runs", runs: "" }).problem, /at least one run/);
  assert.match(parseRuns("2026-11-14 10:00, 2026-11-14 09:00").problems[0], /after the on time/);
  assert.match(parseRuns("2026-11-14 10:00, 2026-11-14 12:00\n2026-11-14 11:00, 2026-11-14 13:00").problems[0], /overlap/);
});

test("a saved plan reads back into the same form", () => {
  const { plan } = planFromForm({ ...formFromPlan(null, "2026-11-16"), kind: "rate", specific: "2026-11-16 08:00, 2026-11-16 12:00" });
  const again = planFromForm(formFromPlan({ plan, name: "x" }, "2026-11-16")).plan;
  assert.deepEqual(again, plan);
});
