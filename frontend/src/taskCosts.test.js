import test from "node:test";
import assert from "node:assert/strict";
import { costChangedText, taskCostLine } from "./taskCosts.js";
import { TASK_COST_FIELD, taskCostWords } from "./rcmIntervals.js";
import { hereCount, whereNote as positionNote, wherePath } from "./subtree.js";
import { MAINTENANCE_COLUMNS, TASK_COLUMNS, maintenanceOrder, cellText, costFoot, costWhere, fromText, money, searchTasks, sortTasks } from "./lsaTab.js";

const typed = { amount: 180, source: "typed", typed: 180, lsa: { amount: 120, complete: true, missing_rates: [], missing_prices: [] } };
const lsa = { amount: 449.5, source: "lsa", typed: null, lsa: { amount: 449.5, labour_cost: 325, materials_cost: 124.5, complete: false, missing_rates: [], missing_prices: ["Gasket"] } };
const none = { amount: null, source: null, typed: null, lsa: { amount: null, complete: false, missing_rates: ["Fitter"], missing_prices: [] } };

test("the RCM's line for a task says its cost and where it came from", () => {
  assert.equal(taskCostLine({ name: "Check the seal", cost: { amount: 40, source: "typed", complete: true } }), "Check the seal: $40 each time (typed on the task).");
  assert.equal(taskCostLine({ name: "Grease", cost: { amount: 12, source: "lsa", complete: false } }), "Grease: $12 each time (from its LSA, partly priced).");
  assert.equal(taskCostLine({ name: "Grease", cost: { amount: null, source: null } }), "Grease: no cost yet.");
  assert.match(costChangedText({ task: "Check the seal", now: 65, used: 40 }), /now costs \$65 each time; the saved calculation used \$40\. The decision keeps its figures/);
});

test("each calculator takes the task's own cost in its own input, and says where it came from", () => {
  assert.deepEqual(TASK_COST_FIELD, { pf: "inspection_cost", ff: "test_cost", fixed: "planned_cost" });
  assert.match(taskCostWords({ amount: 40, source: "typed" }), /\$40 \(typed on the task, on its Maintenance tab\)/);
  assert.match(taskCostWords({ amount: 40, source: "lsa" }), /from its LSA/);
  assert.match(taskCostWords(null), /no cost yet\. Set it once on its Maintenance tab/);
});

test("the Maintenance tab's columns: where each task came from and its cost", () => {
  assert.ok(MAINTENANCE_COLUMNS.every((id) => TASK_COLUMNS.some((c) => c.id === id)));
  // Drawn in the Maintenance order, any other column chosen after them.
  assert.deepEqual(maintenanceOrder(TASK_COLUMNS.filter((c) => ["mode", "task", "cost", "kind", "interval"].includes(c.id))).map((c) => c.id),
    ["task", "interval", "cost", "kind", "mode"]);
  const rcm = { name: "Check the seal", modes: [{ text: "Seal leaks" }, { text: "Seal wears" }], cost: typed };
  const direct = { name: "Inspect the guard", source: "statutory", reference: "AS 4024", modes: [], cost: none };
  const both = { name: "Grease", source: "oem", modes: [{ text: "Bearing seizes" }], cost: lsa };
  assert.equal(fromText(rcm), "RCM: Seal leaks +1");
  assert.equal(fromText({ ...rcm, source: "rcm", modes: [] }), "RCM");
  assert.equal(fromText(direct), "Added directly: law, regulation or standard (AS 4024)");
  assert.equal(fromText(both), "Added directly: maker's recommendation · prevents Bearing seizes");
  assert.equal(cellText(rcm, "cost"), "$180");
  assert.equal(cellText(direct, "cost"), "");
  assert.equal(money(1250), "$1,250");
  // Sorted by cost, the tasks with none go last whichever way.
  assert.deepEqual(sortTasks([direct, both, rcm], [{ col: "cost", dir: 1 }]).map((t) => t.name), ["Check the seal", "Grease", "Inspect the guard"]);
  assert.deepEqual(sortTasks([direct, both, rcm], [{ col: "cost", dir: -1 }]).map((t) => t.name), ["Grease", "Check the seal", "Inspect the guard"]);
  assert.deepEqual(searchTasks([rcm, direct], "added directly").map((t) => t.name), ["Inspect the guard"]);
});

test("a cost says where it came from and what's missing", () => {
  assert.equal(costWhere(typed), "Typed on the task.");
  assert.equal(costWhere(lsa), "From its LSA: labour $325, spares and consumables $124.5. Partial: no price for Gasket.");
  assert.equal(costWhere(none), "Not set yet: type what it costs each time, or price its LSA. Its labour needs a rate for Fitter.");
  assert.equal(costFoot([{ cost: typed }, { cost: lsa }]), "$629.5 each time for them all.");
  assert.equal(costFoot([{ cost: typed }, { cost: none }]), "$180 each time for the 1 with a cost; 1 has no cost yet.");
  assert.equal(costFoot([{ cost: none }]), "No costs yet.");
});

test("the Maintenance tab rolls up every task below the row: its own first, then by path", () => {
  const tasks = [
    { id: "d", name: "Grease", subject: { id: "m2", name: "Drive motor", within: "Station › Pump 2" } },
    { id: "b", name: "Check oil", subject: { id: "m1", name: "Drive motor", within: "Station › Pump 1" } },
    { id: "a", name: "Walk round", subject: { id: "station", name: "Station", within: "" } },
    { id: "c", name: "Align", subject: { id: "p1", name: "Pump 1", within: "Station" } },
  ];
  // No sort picked: the row's own task first, then the rest by their path (twins beside their parents).
  assert.deepEqual(sortTasks(tasks, [], { here: "station" }).map((t) => t.id), ["a", "c", "b", "d"]);
  // A sort picked wins; the row's own tasks aren't pinned then.
  assert.deepEqual(sortTasks(tasks, [{ col: "task", dir: 1 }], { here: "p1" }).map((t) => t.id), ["c", "b", "d", "a"]);
  // Each row says where it is; the row's own say so.
  assert.equal(positionNote(tasks[2], "station"), "This position");
  assert.equal(positionNote(tasks[0], "station"), "Station › Pump 2");
  assert.equal(hereCount(tasks, "station"), "1");
  assert.equal(wherePath(tasks[1]), "Station › Pump 1 › Drive motor");
  // The path is searchable: "pump 2" finds the motor inside it.
  assert.deepEqual(searchTasks(tasks, "pump 2").map((t) => t.id), ["d"]);
});
