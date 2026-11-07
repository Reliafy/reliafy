import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cadenceWords, daysLate, freeTasks, lateText, nextVisit, ordinal, packageRows, packageScope, packageSubline,
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
  assert.equal(packageSubline(pkg({ trade: "Fitter", task_count: 1 })), "Every Saturday · Fitter · 1 task");
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

test("rows: worst first, layers under their top", () => {
  const rows = [
    pkg({ id: "a", name: "Alpha", next_visit: "2026-12-01" }),
    pkg({ id: "b", name: "Bravo", next_visit: "2026-11-21" }),
    pkg({ id: "c", name: "Charlie", open_work_order: { late: true, days_late: 2, visit_on: "2026-11-07" } }),
    pkg({ id: "d", name: "Delta", status: "paused" }),
    pkg({ id: "bl", name: "Bravo monthly", parent: { id: "b", name: "Bravo" }, next_visit: "2026-12-05" }),
    pkg({ id: "orphan", name: "Orphan layer", parent: { id: "gone", name: "Gone" }, next_visit: "2026-11-30" }),
  ];
  const out = packageRows(rows, "2026-11-10");
  assert.deepEqual(out.map((r) => [r.pkg.id, r.depth]), [["c", 0], ["b", 0], ["bl", 1], ["orphan", 0], ["a", 0], ["d", 0]]);
  assert.equal(out[2].top.id, "b");
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
