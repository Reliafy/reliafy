import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cadenceFor, cadenceWords, cantJoin, cellText, daysLate, freeTasks, kindText, lateText, nextSort, nextVisit, ordinal, packageScope,
  parseSort, searchTasks, sortParam, sortTasks, tickAll, tickState,
  proposalBatch, proposalProblem, proposalRows, renameRow, toggleRow, visitRuleText,
} from "./packagesTab.js";

const pkg = (over) => ({ id: "x", name: "X", status: "active", parent: null, task_count: 0, cadence: { text: "every Saturday" }, ...over });

test("scope, cadence and visit rules in words", () => {
  assert.deepEqual(packageScope({ type: "pos", key: "p1" }), { position_id: "p1" });
  assert.deepEqual(packageScope({ type: "loc", key: "l1" }), { location_id: "l1" });
  assert.equal(packageScope({ type: "item", key: "i" }), null);
  assert.equal(cadenceWords(pkg()), "Every Saturday");
  assert.equal(ordinal(1), "1st");
  assert.equal(ordinal(12), "12th");
  assert.equal(ordinal(22), "22nd");
  assert.equal(visitRuleText({ visit_rule: "nth", every_nth: 4 }), "every 4th visit");
  assert.equal(visitRuleText({ visit_rule: "every" }), "every visit");
});

test("late: the open work order says; with none, a visit past its tolerance", () => {
  assert.equal(daysLate(pkg({ open_work_order: { late: true, days_late: 3 } }), "2026-11-20"), 3);
  assert.equal(daysLate(pkg({ open_work_order: { late: false } }), "2026-11-20"), 0);
  const due = pkg({ next_visit: "2026-11-14", tolerance: { amount: 1, enforced: true } });
  assert.equal(daysLate(due, "2026-11-15"), 0);
  assert.equal(daysLate(due, "2026-11-18"), 3);
  assert.equal(daysLate({ ...due, pause: { until: null } }, "2026-11-18"), 0);
  assert.equal(lateText(1), "Late by 1 day");
  assert.equal(lateText(0), "");
});

test("the proposal table: tick, rename, batch", () => {
  const drafts = [
    { ref: "p1", name: "Pool weekly check", layer_of: null, create: { name: "Pool weekly check", position_id: "s", weekday: "saturday", tasks: ["t1"] }, tasks: [{ id: "t1", name: "Skim" }] },
    { ref: "p2", name: "Pool monthly check", layer_of: "p1", create: { name: "Pool monthly check", parent_id: "@p1", tasks: ["t2"] }, tasks: [{ id: "t2", name: "Clean cell" }, { id: "t1", name: "Skim" }] },
  ];
  let rows = proposalRows(drafts);
  rows = toggleRow(rows, "p1", false);
  assert.deepEqual(rows.map((r) => r.ticked), [false, false]);
  assert.equal(proposalProblem(rows), "Tick at least one package to make.");
  rows = toggleRow(rows, "p2", true);
  assert.deepEqual(rows.map((r) => r.ticked), [true, true]);
  rows = renameRow(rows, "p1", "Saturday walk");
  const batch = proposalBatch(rows, { tolerance: "1" });
  assert.deepEqual(batch[0], { ref: "p1", name: "Saturday walk", position_id: "s", weekday: "saturday", tasks: ["t1"], tolerance: 1, tolerance_unit: "days" });
  assert.equal(batch[1].parent_id, "@p1");
  assert.equal(batch[1].tolerance, undefined);
  assert.equal(proposalProblem(renameRow(rows, "p2", " ")), "Give every ticked package a name.");
  assert.deepEqual(freeTasks({ drafts }).map((t) => t.name), ["Clean cell", "Skim"]);
});

test("the Summary's next visit", () => {
  assert.equal(nextVisit([{ due_by: "interval", next_due: "2026-11-01" }]), null);
  assert.deepEqual(nextVisit([
    { due_by: "package", package: { id: "a", name: "Weekly" }, next_due: "2026-11-14" },
    { due_by: "package", package: { id: "a", name: "Weekly" }, next_due: "2026-11-21" },
  ]), { id: "a", name: "Weekly", on: "2026-11-14" });
});

const task = (over) => ({
  id: "t", name: "Task", subject: { id: "p", name: "Pump" }, modes: [], kind: "fixed_interval", interval: 1, unit: "months",
  trigger: null, on_event: false, trade: "", next_due: null, package: null, why_not: null, ...over,
});
const tasks = [
  task({ id: "a", name: "Grease bearings", subject: { name: "Pump 2" }, interval: 3, unit: "months", next_due: "2026-12-01", trade: "Fitter",
         modes: [{ id: "m", text: "Bearing worn", function: "Pump water", failure: "No flow" }] }),
  task({ id: "b", name: "Check pH", subject: { name: "Pool" }, kind: "on_condition", interval: 1, unit: "weeks", next_due: "2026-11-14",
         package: { id: "k", name: "Pool weekly" } }),
  task({ id: "c", name: "Test alarm", subject: { name: "Pool" }, kind: "failure_finding", interval: 6, unit: "months" }),
  task({ id: "d", name: "Clear drain", subject: { name: "Pump 2" }, on_event: true, trigger: { text: "120 mm rain" }, interval: null }),
];

test("the table's cells in words", () => {
  assert.equal(kindText(tasks[1]), "On condition");
  assert.equal(kindText(tasks[3]), "on event: 120 mm rain");
  assert.equal(cellText(tasks[0], "interval"), "3 months");
  assert.equal(cellText(tasks[1], "interval"), "1 week");
  assert.equal(cellText(tasks[3], "interval"), "");
  assert.equal(cellText(tasks[0], "mode"), "Bearing worn");
  assert.equal(cellText(tasks[1], "package"), "Pool weekly");
});

test("search: every word somewhere in the row, the failure mode's function and failure too", () => {
  assert.deepEqual(searchTasks(tasks, "").map((t) => t.id), ["a", "b", "c", "d"]);
  assert.deepEqual(searchTasks(tasks, "pool").map((t) => t.id), ["b", "c"]);
  assert.deepEqual(searchTasks(tasks, "no flow fitter").map((t) => t.id), ["a"]);
  assert.deepEqual(searchTasks(tasks, "POOL weekly").map((t) => t.id), ["b"]);
  assert.deepEqual(searchTasks(tasks, "rain").map((t) => t.id), ["d"]);
});

test("sort: a click sorts by one column, again reverses, again clears; shift adds a key", () => {
  let keys = nextSort([], "due");
  assert.deepEqual(keys, [{ col: "due", dir: 1 }]);
  assert.deepEqual(nextSort(keys, "due"), [{ col: "due", dir: -1 }]);
  assert.deepEqual(nextSort([{ col: "due", dir: -1 }], "due"), []);
  assert.deepEqual(nextSort(keys, "task"), [{ col: "task", dir: 1 }]);
  keys = nextSort([{ col: "position", dir: 1 }], "interval", true);
  assert.equal(sortParam(keys), "position,interval");
  assert.equal(sortParam(nextSort(keys, "interval", true)), "position,-interval");
  assert.equal(sortParam(nextSort(nextSort(keys, "interval", true), "interval", true)), "position");
  assert.deepEqual(parseSort("position,-interval,bogus"), [{ col: "position", dir: 1 }, { col: "interval", dir: -1 }]);
  assert.deepEqual(parseSort(null), []);
  // Blank values last either way; intervals by length.
  assert.deepEqual(sortTasks(tasks, parseSort("due")).map((t) => t.id), ["b", "a", "c", "d"]);
  assert.deepEqual(sortTasks(tasks, parseSort("-due")).map((t) => t.id), ["a", "b", "c", "d"]);
  assert.deepEqual(sortTasks(tasks, parseSort("interval")).map((t) => t.id), ["b", "a", "c", "d"]);
  assert.deepEqual(sortTasks(tasks, parseSort("position,-interval")).map((t) => t.id), ["c", "b", "a", "d"]);
  // No keys: position, then task.
  assert.deepEqual(sortTasks(tasks, []).map((t) => t.id), ["b", "c", "d", "a"]);
});

test("ticking, and a new package's cadence from the tasks ticked", () => {
  const shown = tasks.slice(0, 2);
  let picked = new Set(["c"]);
  assert.equal(tickState(shown, picked), "none");
  picked = tickAll(shown, picked, true);
  assert.deepEqual([...picked].sort(), ["a", "b", "c"]);
  assert.equal(tickState(shown, picked), "all");
  assert.equal(tickState(shown, new Set(["a"])), "some");
  assert.deepEqual([...tickAll(shown, picked, false)], ["c"]);
  assert.deepEqual(cadenceFor([tasks[1], task({ interval: 1, unit: "weeks" }), tasks[0]]), { every: 1, unit: "weeks", mixed: true });
  assert.deepEqual(cadenceFor([task({ interval: 14, unit: "days" })]), { every: 2, unit: "weeks", mixed: false });
  assert.deepEqual(cadenceFor([task({ interval: 1, unit: "years" })]), { every: 12, unit: "months", mixed: false });
  assert.deepEqual(cadenceFor([tasks[3]]), { every: 1, unit: "weeks", mixed: false });
  assert.deepEqual(cantJoin([tasks[0], task({ id: "z", why_not: "by use" })]).map((t) => t.id), ["z"]);
});
