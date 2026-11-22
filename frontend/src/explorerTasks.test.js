import { test } from "node:test";
import assert from "node:assert/strict";
import { forecastItem, graftTasks, isTaskRow, openForTasks, rollupText, taskCell, taskKey } from "./explorerTasks.js";

// A small tree: Station › Pump 1 › Motor, Station › Pump 2 (by positions), and a place.
const row = (key, type, parent, kids, depth, name) => [key, { key, type, parent, kids, depth, ref: { name } }];
const display = {
  rows: new Map([
    row("st", "pos", null, ["p1", "p2"], 0, "Station"),
    row("p1", "pos", "st", ["m1"], 1, "Pump 1"),
    row("m1", "pos", "p1", [], 2, "Motor"),
    row("p2", "pos", "st", [], 1, "Pump 2"),
  ]),
};
const task = (id, on, extra = {}) => ({ id, name: `Task ${id}`, subject: { id: on, name: on }, interval: 1, unit: "months", ...extra });

test("each position's tasks hang under it, and every level counts the tasks at and below it", () => {
  const out = graftTasks(display, [task("a", "st"), task("b", "m1", { overdue: true }), task("c", "m1"), task("x", "elsewhere")]);
  // Tasks first under their position, then the positions inside it.
  assert.deepEqual(out.rows.get("st").kids, [taskKey("a"), "p1", "p2"]);
  assert.deepEqual(out.rows.get("m1").kids, [taskKey("b"), taskKey("c")]);
  const b = out.rows.get(taskKey("b"));
  assert.ok(isTaskRow(b));
  assert.equal(b.parent, "m1");
  assert.equal(b.depth, 3);
  assert.equal(b.ref.position_id, "m1");
  // A task on a position not in the tree (another asset) isn't shown.
  assert.equal(out.rows.has(taskKey("x")), false);
  assert.deepEqual(out.rows.get("st").tall, { tasks: 3, overdue: 1 });
  assert.deepEqual(out.rows.get("p1").tall, { tasks: 2, overdue: 1 });
  assert.deepEqual(out.rows.get("p1").tsum, { tasks: 0, overdue: 0 });
  // The display given is left as it is.
  assert.deepEqual(display.rows.get("st").kids, ["p1", "p2"]);
});

test("a level's roll-up says what's at and below it, its own first when open", () => {
  const out = graftTasks(display, [task("a", "st"), task("b", "m1", { overdue: true }), task("c", "m1")]);
  assert.equal(rollupText(out.rows.get("st")), "3 tasks at and below · 1 overdue");
  assert.equal(rollupText(out.rows.get("st"), true), "1 here · 3 tasks at and below · 1 overdue");
  // A level with no tasks of its own still counts the ones below.
  assert.equal(rollupText(out.rows.get("p1"), true), "2 tasks at and below · 1 overdue");
  assert.equal(rollupText(out.rows.get("m1")), "2 tasks here · 1 overdue");
  assert.equal(rollupText(out.rows.get("p2")), "No tasks here or below");
});

test("cells, the way down, and Forecast… on a position only (never a design's)", () => {
  assert.equal(taskCell({ cost: { amount: 45, source: "typed" } }, "cost").text, "$45");
  assert.equal(taskCell({ cost: { amount: null } }, "cost").blank, "Not set");
  assert.deepEqual(taskCell({ next_due: "2026-12-01", overdue: true }, "due").overdue, true);
  assert.equal(taskCell({ package: { id: "k", name: "Weekly" } }, "package").text, "Weekly");
  assert.deepEqual(openForTasks(display, "m1"), ["m1", "p1", "st"]);
  assert.equal(forecastItem({ type: "pos" }).length, 1);
  assert.equal(forecastItem({ type: "loc" }).length, 0);
  assert.equal(forecastItem({ type: "pos" }, { design: true }).length, 0);
});

test("a position shown above a place's positions (a via row) counts the tasks under it", () => {
  const d = { rows: new Map([
    ["h", { key: "h", type: "group", parent: null, kids: ["p"], depth: 0, ref: { name: "House", via: true } }],
    ["p", { key: "p", type: "pos", parent: "h", kids: [], depth: 1, ref: { name: "Pool" } }],
  ]) };
  const out = graftTasks(d, [task("a", "p")]);
  assert.equal(rollupText(out.rows.get("h")), "1 task at and below");
});
