import { test } from "node:test";
import assert from "node:assert/strict";
import { positionWorkSubject, taskDoneBody, taskDoneText, workDoneBody, workDoneRows } from "./workDone.js";
import { WORK_ORDERS_OFF_NOTE, workOrdersOn } from "./workOrdersFlag.js";
import { defaultCloseKind, defaultFailed, closeTarget } from "./maintenanceSubjects.js";
import { movedTarget } from "./redirects.js";

test("work orders are on unless the server turns them off", () => {
  assert.equal(workOrdersOn({}), true);
  assert.equal(workOrdersOn(undefined), true);
  assert.equal(workOrdersOn({ maintenance_work_orders: true }), true);
  assert.equal(workOrdersOn({ maintenance_work_orders: false }), false);
  assert.match(WORK_ORDERS_OFF_NOTE, /turned off/);
});

test("a position reads as a breakdown's work order in the what-was-done form", () => {
  const p = {
    id: "p1", name: "Pump A", fitted: { item: { name: "Pump", serial: "N1" } },
    failure_modes: [{ id: "f1", text: "Bearing worn" }], class_failure_modes: [], parts_list: [{ id: "pt" }],
  };
  const wo = positionWorkSubject(p);
  // Nothing picked and "did it fail?" unanswered: nothing is recorded by default.
  assert.equal(defaultCloseKind(wo), "");
  assert.equal(defaultFailed(wo), null);
  const t = closeTarget(wo, "");
  assert.equal(t.name, "Pump A");
  assert.deepEqual(t.failure_modes, p.failure_modes);
  assert.deepEqual(t.suggested_parts, p.parts_list);
  assert.equal(t.fitted.item.serial, "N1");
  assert.equal(positionWorkSubject(null), null);
});

test("what was done is sent with where, never a package's not_done", () => {
  const body = workDoneBody("p1", { actions: [{ kind: "repair" }], on: "2026-11-20", notes: "", readings: [], not_done: [] });
  assert.deepEqual(body, { position_id: "p1", actions: [{ kind: "repair" }], on: "2026-11-20", notes: "", readings: [] });
});

test("a task done: its id and day, and what it says after", () => {
  assert.deepEqual(taskDoneBody({ id: "t1" }, "2026-11-01"), { task_id: "t1", on: "2026-11-01" });
  assert.deepEqual(taskDoneBody({ id: "t1" }, ""), { task_id: "t1" });
  assert.equal(taskDoneText({ on: "2026-11-01", task: { next_due: "2027-05-01" } }),
    "Recorded as done on 2026-11-01. Next due 2027-05-01.");
});

test("with work orders off, Maintenance's own address opens on Packages", () => {
  const row = { path: "/maintenance", to: "/maintenance/work-orders" };
  assert.equal(movedTarget(row), "/maintenance/work-orders");
  assert.equal(movedTarget(row, { workOrders: false }), "/maintenance/packages");
  const rcm = { path: "/old", to: "/maintenance/rcm" };
  assert.equal(movedTarget(rcm, { workOrders: false }), rcm.to);
});

test("work done history: closed ones only, newest first, in plain words", () => {
  const rows = workDoneRows([
    { id: "a", status: "closed", closed: "2026-10-01", title: "Bearing", type: "corrective", done: [{ kind: "replace" }] },
    { id: "b", status: "open", opened: "2026-11-01", title: "Hidden" },
    { id: "c", status: "cancelled", closed: "2026-11-02", title: "Dup" },
    { id: "d", status: "closed", closed: "2026-11-10", title: "Grease", type: "preventive" },
  ]);
  assert.deepEqual(rows.map((r) => [r.id, r.on, r.what, r.kind]),
    [["d", "2026-11-10", "", "Planned task"], ["a", "2026-10-01", "Replaced", "Repair or replacement"]]);
  assert.deepEqual(workDoneRows(null), []);
});
