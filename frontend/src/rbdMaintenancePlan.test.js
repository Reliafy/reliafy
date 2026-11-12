// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  PLAN_SUPPORTS, costText, dutyText, dutyWords, intervalBasis, parseCost, parseDuty, parseNumber, planColumns,
  planCounts, planRows, rowProblems, setDuty, setGroup, setInterval, setIntervalBasis, setScheduleField, setTask,
  taskOf, taskSummary, toCalendar, toOperating,
} from "./rbdMaintenancePlan.js";

const block = (id, data = {}) => ({ id, type: "component", data: { label: id, ...data } });

test("the plan lists component blocks, not repeats, gates or standby groups", () => {
  const rows = planRows([
    block("a", { preventive: { policy: "block", interval: 100 } }),
    block("b", { repeat_of: "a" }),
    { id: "k", type: "knode", data: {} },
    { id: "s", type: "standby", data: {} },
    block("c", { inspection: { interval: 50 } }),
    block("d"),
  ]);
  assert.deepEqual(rows.map((r) => [r.id, r.task]), [["a", "block"], ["c", "test"], ["d", "none"]]);
});

test("the crew column shows only with limited crews; nothing the library can't do yet is offered", () => {
  assert.ok(!planColumns().includes("crew"));
  assert.ok(planColumns({ crews: true }).includes("crew"));
  assert.ok(planColumns().includes("restores"));
  assert.deepEqual(PLAN_SUPPORTS.restoration, ["as_new"]);
  assert.equal(PLAN_SUPPORTS.shutdowns, false);
});

test("duty is typed as a percentage and stored as a fraction", () => {
  assert.deepEqual(parseDuty("25"), { value: 0.25, error: null });
  assert.deepEqual(parseDuty(" 12.5 % "), { value: 0.125, error: null });
  assert.deepEqual(parseDuty(""), { value: null, error: null });
  assert.ok(parseDuty("0").error);
  assert.ok(parseDuty("120").error);
  assert.ok(parseDuty("half").error);
  assert.equal(dutyText(0.25), "25");
  assert.equal(dutyText(null), "");
});

test("duty in plain words, with hours a day on a calendar clock", () => {
  assert.equal(dutyWords(0.25, "Hours"), "Runs 25% of the time · about 6 h a day");
  assert.equal(dutyWords(0.5, "Cycles"), "Runs 50% of the time");
  assert.equal(dutyWords(null, "Hours"), "Runs all the time");
  assert.equal(dutyWords(1, "Hours"), "Runs all the time");
});

test("running time converts to calendar time through the duty, and back", () => {
  assert.equal(toCalendar(500, 0.25), 2000);
  assert.equal(toOperating(2000, 0.25), 500);
  assert.equal(toCalendar(500, null), null);
});

test("an interval in running time follows the duty", () => {
  let d = setTask({ label: "Pump" }, "age");
  d = setDuty(d, 0.5);
  d = setInterval(d, 500, "operating");
  assert.equal(intervalBasis(d), "operating");
  assert.deepEqual(d.preventive, { policy: "age", operating_interval: 500, interval: 1000 });
  // Change the duty: the calendar interval moves, the running interval stays.
  d = setDuty(d, 0.25);
  assert.equal(d.preventive.interval, 2000);
  assert.equal(d.preventive.operating_interval, 500);
  // Back to the calendar keeps the same schedule.
  const cal = setIntervalBasis(d, "calendar");
  assert.deepEqual(cal.preventive, { policy: "age", interval: 2000 });
  // And to running time again converts through the duty.
  assert.equal(setIntervalBasis(cal, "operating").preventive.operating_interval, 500);
});

test("running time with no duty is refused in plain words, never guessed", () => {
  let d = setInterval(setTask({}, "age"), 500, "operating");
  assert.equal(d.preventive.interval, undefined);
  assert.match(rowProblems(d, "Hours")[0], /Runs %/);
  assert.match(rowProblems(d, "Cycles")[0], /time unit/);
  // Taking the duty away again leaves the calendar interval unset, not stale.
  d = setDuty(setDuty(d, 0.5), null);
  assert.equal(d.duty, undefined);
  assert.equal(d.preventive.interval, undefined);
});

test("switching task keeps what was typed and drops what doesn't apply", () => {
  let d = setTask({ maintenance_group: "North" }, "age");
  d = setInterval(d, 500);
  d = setScheduleField(d, "duration", 8);
  d = setScheduleField(d, "cost", { min: 300, max: 700 });
  d = setScheduleField(d, "opportunity", 400);
  assert.equal(taskOf(d), "age");
  const cbm = setTask(d, "condition");
  assert.deepEqual(cbm.preventive, { policy: "condition", interval: 500, duration: 8, cost: { min: 300, max: 700 } });
  const test_ = setTask(d, "test");
  assert.deepEqual(test_.inspection, { interval: 500, duration: 8, cost: { min: 300, max: 700 } });
  assert.equal(test_.preventive, undefined);
  assert.equal(test_.maintenance_group, undefined, "a proof-tested block can't be in a group");
  const none = setTask(d, "none");
  assert.equal(none.preventive, undefined);
  assert.equal(none.maintenance_group, "North");
});

test("costs: a number or a range", () => {
  assert.deepEqual(parseCost("1,500"), { value: 1500, error: null });
  assert.deepEqual(parseCost("300-700"), { value: { min: 300, max: 700 }, error: null });
  assert.deepEqual(parseCost("300 – 700"), { value: { min: 300, max: 700 }, error: null });
  assert.deepEqual(parseCost("500-500"), { value: 500, error: null });
  assert.ok(parseCost("700-300").error);
  assert.ok(parseCost("-5").error);
  assert.equal(costText({ min: 300, max: 700 }), "300–700");
  assert.equal(costText(250), "250");
  assert.equal(costText(null), "");
  assert.ok(parseNumber("0", { positive: true }).error);
  assert.ok(parseNumber("1.2", { max: 1 }).error);
  assert.equal(parseNumber("0.05", { max: 1 }).value, 0.05);
});

test("a row says what's missing", () => {
  assert.match(rowProblems(setTask({}, "age"))[0], /how often it's replaced/);
  assert.match(rowProblems(setInterval(setTask({}, "condition"), 100)).join(), /threshold/);
  let t = setInterval(setTask({}, "test"), 100);
  t = setScheduleField(t, "coverage", 0.9);
  assert.match(rowProblems(t).join(), /full-test interval/);
  t = setScheduleField(t, "full_test", 250);
  assert.match(rowProblems(t).join(), /whole multiple/);
  t = setScheduleField(t, "full_test", 300);
  assert.deepEqual(rowProblems(t), []);
  const early = setScheduleField(setInterval(setTask({}, "age"), 100), "opportunity", 50);
  assert.match(rowProblems(early).join(), /needs a maintenance group/);
  assert.deepEqual(rowProblems(setGroup(early, "North")), []);
  assert.deepEqual(rowProblems({ duty: 1.5 }).length, 1);
});

test("the summary reads as a sentence", () => {
  let d = setInterval(setTask({}, "age"), 4380);
  d = setScheduleField(d, "duration", 8);
  assert.equal(taskSummary(d, "Hours"), "Replace at age every 4,380 h, takes 8 h, as new");
  d = setInterval(setDuty(d, 0.5), 2190, "operating");
  assert.equal(taskSummary(d, "Hours"), "Replace at age every 4,380 h (2,190 running h), takes 8 h, as new");
  assert.equal(taskSummary(setInterval(setTask({}, "test"), 8760), "Hours"), "Proof test every 8,760 h, no downtime");
  assert.equal(taskSummary({}, "Hours"), "Run to failure");
});

test("the plan's counts", () => {
  const rows = planRows([
    block("a", { preventive: { policy: "age", interval: 100 }, duty: 0.5 }),
    block("b", { preventive: { policy: "age" } }),
    block("c"),
  ]);
  assert.deepEqual(planCounts(rows), { blocks: 3, planned: 2, withDuty: 1, problems: 1 });
});
