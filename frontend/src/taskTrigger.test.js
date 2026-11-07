import test from "node:test";
import assert from "node:assert/strict";
import { asksInterval, pointLabel, taskDueText, triggerBody, triggerState, triggerWhy } from "./taskTrigger.js";
import { everyText, onEventOnly, taskLine, triggerText, whenText } from "./rcmWorksheet.js";
import { positionRcmRows } from "./rcmImport.js";

const RAIN = { kind: "reading", point_id: "p1", above: 120, with_interval: false, text: "120 mm on POOL-RAIN" };

test("a task's trigger reads into the form and back", () => {
  assert.deepEqual(triggerState({ trigger: null }), {
    mode: "interval", by: "reading", pointId: "", side: "above", limit: "", eventType: "", note: "", withInterval: false,
  });
  const st = triggerState({ trigger: RAIN });
  assert.equal(st.mode, "event");
  assert.equal(st.limit, "120");
  assert.deepEqual(triggerBody(st), { kind: "reading", point_id: "p1", above: 120 });
  assert.deepEqual(triggerBody({ ...st, side: "below", withInterval: true }),
    { kind: "reading", point_id: "p1", below: 120, with_interval: true });
  const named = triggerState({ trigger: { kind: "event", event_type: "Lightning strike", note: "" } });
  assert.deepEqual(triggerBody({ ...named, eventType: "  Lightning   strike " }), { kind: "event", event_type: "Lightning strike" });
  assert.equal(triggerBody(triggerState({})), null);
});

test("what the trigger form still needs", () => {
  const st = triggerState({});
  assert.equal(triggerWhy(st), "");
  assert.equal(triggerWhy({ ...st, mode: "event" }), "Pick the measuring point to watch.");
  assert.equal(triggerWhy({ ...st, mode: "event", pointId: "p1" }), "Enter the limit: a number.");
  assert.equal(triggerWhy({ ...st, mode: "event", pointId: "p1", limit: "120" }), "");
  assert.equal(triggerWhy({ ...st, mode: "event", by: "name" }), "Name the event, e.g. Lightning strike.");
  assert.equal(asksInterval(st), true);
  assert.equal(asksInterval({ ...st, mode: "event" }), false);
  assert.equal(asksInterval({ ...st, mode: "event", withInterval: true }), true);
  assert.equal(pointLabel({ name: "POOL-RAIN", unit: "mm", on: { name: "Aquatic centre" } }), "POOL-RAIN (mm) · on Aquatic centre");
});

test("the worksheet says on event in place of the interval", () => {
  const task = { name: "Re-dose", interval: 1, unit: "months", trigger: RAIN };
  assert.equal(onEventOnly(task), true);
  assert.equal(triggerText(RAIN), "on event: 120 mm on POOL-RAIN");
  assert.equal(whenText({ interval: 1, interval_unit: "months", trigger: RAIN }), "on event: 120 mm on POOL-RAIN");
  assert.equal(whenText({ interval: 6, interval_unit: "months", trigger: { ...RAIN, with_interval: true } }),
    "6 months or on event: 120 mm on POOL-RAIN");
  assert.equal(whenText({ interval: 6, interval_unit: "months" }), "6 months");
  assert.equal(everyText(task), "on event: 120 mm on POOL-RAIN");
  assert.equal(everyText({ interval: 2, unit: "weeks" }), "every 2 weeks");
  assert.equal(taskLine(task), "Re-dose · on event: 120 mm on POOL-RAIN");
});

test("the CSV writes on event in the interval column as text", () => {
  const ws = { positions: [{ name: "Pool", depth: 0, functions: [], unassigned: [{
    text: "Out of balance after rain", decision: { outcome: "on_condition", task: "Re-dose", interval: 1,
      interval_unit: "months", trigger: RAIN,
      tasks: [{ id: "t1", text: "Re-dose", interval: 1, unit: "months", trigger: RAIN },
        { id: "t2", text: "Inspect", interval: 12, unit: "months", trigger: { kind: "event", event_type: "Lightning strike", text: "Lightning strike" } }] },
  }] }] };
  const [header, first, second] = positionRcmRows(ws);
  const at = header.indexOf("Interval");
  assert.ok(at > 0);
  assert.equal(first[at], "on event: 120 mm on POOL-RAIN");
  assert.equal(first[at + 1], "");
  assert.equal(second[at], "on event: Lightning strike");
});

test("a task waiting for its event says so in the Work list", () => {
  const fmt = (d) => `[${d}]`;
  assert.equal(taskDueText({ next_due: "2026-12-01" }, fmt), "Next due [2026-12-01]");
  assert.equal(taskDueText({ on_event: true, trigger: RAIN }, fmt), "Waiting for the event: 120 mm on POOL-RAIN");
  assert.equal(taskDueText({ on_event: true, trigger: RAIN, open_work_order: { id: "w" } }, fmt), "Raised: its work order is open");
  assert.equal(taskDueText({}, fmt, "By use"), "By use");
});
