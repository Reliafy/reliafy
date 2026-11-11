import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createDetail, createLabel, createPlan, daysLate, doneText, dueWindow, groupDue, lateText, linesText,
  orderKind, orderTab, ordersPath, ordersSummary, packageMatches, packagePath, packageStatusText, splitOpen,
} from "./maintenanceOrders.js";

const TODAY = "2026-11-10";

test("ordersPath: the Open tab is the page's own address; others and filters go in the query", () => {
  assert.equal(ordersPath(), "/maintenance/work-orders");
  assert.equal(ordersPath("open", { location: "l 1" }), "/maintenance/work-orders?location=l+1");
  assert.equal(ordersPath("due"), "/maintenance/work-orders?tab=due");
  assert.equal(ordersPath("closed", { q: "" }), "/maintenance/work-orders?tab=closed");
  assert.equal(packagePath("p/1"), "/maintenance/packages/p%2F1");
});

test("orderTab and dueWindow fall back to their defaults", () => {
  assert.equal(orderTab("closed"), "closed");
  assert.equal(orderTab("nope"), "open");
  assert.equal(orderTab(null), "open");
  assert.equal(dueWindow("7"), 7);
  assert.equal(dueWindow("45"), 30);
});

test("daysLate follows the server's overdue and a package visit's own count", () => {
  assert.equal(daysLate({ overdue: false, due: "2026-11-01" }, TODAY), null);
  assert.equal(daysLate({ overdue: true, due: "2026-11-06" }, TODAY), 4);
  assert.equal(daysLate({ overdue: true, due: "2026-11-01", days_late: 2 }, TODAY), 2);
  assert.equal(daysLate({ overdue: true, due: null }, TODAY), null);
  assert.equal(lateText(1), "1 day late");
  assert.equal(lateText(4), "4 days late");
  assert.equal(lateText(null), "");
});

test("splitOpen: overdue first, most late first; the rest keep the server's order", () => {
  const rows = [
    { id: "a", number: 1, overdue: true, due: "2026-11-08" },
    { id: "b", number: 2, overdue: false, due: "2026-11-12" },
    { id: "c", number: 3, overdue: true, due: "2026-11-01" },
    { id: "d", number: 4, overdue: false, due: null },
  ];
  const { overdue, open } = splitOpen(rows, TODAY);
  assert.deepEqual(overdue.map((w) => w.id), ["c", "a"]);
  assert.deepEqual(open.map((w) => w.id), ["b", "d"]);
});

test("ordersSummary puts the answer first", () => {
  assert.equal(ordersSummary({ open: [], due: [] }), "No open work orders. Nothing due in the next 30 days.");
  const open = [{ overdue: true, due: "2026-11-06" }, { overdue: false }, { overdue: false }];
  assert.equal(ordersSummary({ open, due: new Array(12), horizon: 30, today: TODAY }),
    "3 open, 1 late by 4 days. 12 due in the next 30 days.");
  const two = [{ overdue: true, due: "2026-11-09" }, { overdue: true, due: "2026-11-03" }];
  assert.equal(ordersSummary({ open: two, today: TODAY }), "2 open, 2 late (the latest by 7 days).");
});

test("groupDue: packages by name, then the tasks in none", () => {
  const rows = [
    { id: "t1", package: { id: "p2", name: "Weekly" } },
    { id: "t2" },
    { id: "t3", package: { id: "p1", name: "Monthly" } },
    { id: "t4", package: { id: "p2", name: "Weekly" } },
  ];
  const groups = groupDue(rows);
  assert.deepEqual(groups.map((g) => g.key), ["p1", "p2", "none"]);
  assert.deepEqual(groups[1].tasks.map((t) => t.id), ["t1", "t4"]);
  assert.equal(groups[2].package, null);
  assert.deepEqual(groupDue([]), []);
});

test("createPlan: one work order per package visit and per loose task", () => {
  const rows = [
    { id: "t1", package: { id: "p1", active: true } },
    { id: "t2", package: { id: "p1", active: true } },
    { id: "t3" },
    { id: "t4", open_work_order: { id: "w" } },
    { id: "t5", package: { id: "p2", active: false }, held: true },
    { id: "t6", package: { id: "p3", active: true }, open_work_order: { id: "w2" } },
  ];
  const plan = createPlan(rows);
  assert.deepEqual(plan, { packages: 1, tasks: 1, total: 2 });
  assert.equal(createLabel(plan), "Create 2 work orders");
  assert.equal(createDetail(plan), "1 package visit, 1 task");
  assert.equal(createLabel({ total: 1 }), "Create 1 work order");
  assert.equal(createDetail({ packages: 0, tasks: 3 }), "3 tasks");
});

test("doneText says what was done", () => {
  assert.equal(doneText({ status: "cancelled", done: [] }), "Cancelled");
  assert.equal(doneText({ status: "closed", done: [{ kind: "inspect", finding: "ok" }] }), "Checked, nothing done");
  assert.equal(doneText({ status: "closed", done: [{ kind: "replace" }, { kind: "repair" }, { kind: "replace" }] }),
    "Replaced, Repaired");
  assert.equal(doneText({ status: "closed", done: [{ kind: "inspect", finding: "found_failed" }] }), "Inspected, found failed");
  assert.equal(doneText({ status: "closed", done: [] }), "Closed");
});

test("linesText and orderKind", () => {
  assert.equal(linesText({ lines_answered: 13, lines_total: 29 }), "13 of 29 lines");
  assert.equal(linesText({ lines_total: 1 }), "0 of 1 line");
  assert.equal(linesText({}), "");
  assert.equal(orderKind({ package: { id: "p" } }), "package");
  assert.equal(orderKind({ type: "preventive" }), "task");
  assert.equal(orderKind({ type: "corrective" }), "hand");
});

test("packageStatusText and packageMatches", () => {
  assert.equal(packageStatusText({ status: "active" }), "Active");
  assert.equal(packageStatusText({ status: "active", open_work_order: { late: true } }), "Visit late");
  assert.equal(packageStatusText({ status: "paused", pause: { text: "paused until 1 Dec 2026" } }), "Paused until 1 Dec 2026");
  assert.equal(packageStatusText({ status: "retired" }), "Retired");
  const p = { name: "Weekly round", subject: { name: "Pump house" }, cadence: { text: "every Saturday" } };
  assert.ok(packageMatches(p, "pump"));
  assert.ok(packageMatches(p, "SATURDAY"));
  assert.ok(packageMatches(p, ""));
  assert.ok(!packageMatches(p, "fan"));
});
