import { test } from "node:test";
import assert from "node:assert/strict";
import { LAST_DONE_NOTE, planWords, workManagementOn } from "./workManagement.js";
import { movedTarget } from "./redirects.js";

test("work management is on unless the server turns it off (either name)", () => {
  assert.equal(workManagementOn({}), true);
  assert.equal(workManagementOn(undefined), true);
  assert.equal(workManagementOn({ work_management: true }), true);
  assert.equal(workManagementOn({ work_management: false }), false);
  // The earlier name, from a server before the rename.
  assert.equal(workManagementOn({ maintenance_work_orders: false }), false);
  assert.equal(workManagementOn({ work_management: true, maintenance_work_orders: false }), true);
});

test("a task's next date is planned, not due, in a hypothetical plan", () => {
  assert.equal(planWords(true).next, "Next due");
  assert.equal(planWords(false).next, "Next planned");
  assert.doesNotMatch(LAST_DONE_NOTE, /work order|overdue|due\b/i);
});

test("with work management off, Maintenance's work-order addresses open on Packages", () => {
  const row = { path: "/maintenance", to: "/maintenance/work-orders" };
  assert.equal(movedTarget(row), "/maintenance/work-orders");
  assert.equal(movedTarget(row, { workOrders: false }), "/maintenance/packages");
  const rcm = { path: "/old", to: "/maintenance/rcm" };
  assert.equal(movedTarget(rcm, { workOrders: false }), rcm.to);
});
