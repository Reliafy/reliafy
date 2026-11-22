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

// ---- column filters, selection and packaging (Derryn, 22 Nov 2026) ----

import {
  TASK_ADD_TO, TASK_CLEAR, TASK_PACKAGE, TASK_COLUMNS, anyFilter, commonHolder, facetValues, filterTasks, filterWords, keepShown,
  packageMisfit, pickTasks, rankPackages, shownTasks, taskRowActions, visitFor,
} from "./explorerTasks.js";
import { flatten } from "./outlineTree.js";

const withRoots = { ...display, roots: ["st"] };
const mower = [
  task("oil", "st", { unit: "hours", interval: 100, trade: "Fitter", kind: "fixed_interval" }),
  task("blade", "p1", { unit: "hours", interval: 50, trade: "Fitter", kind: "fixed_interval" }),
  task("belt", "m1", { unit: "hours", interval: 50, trade: "Electrician", package: { id: "k1", name: "50 h service" }, kind: "on_condition" }),
  task("guard", "p2", { unit: "months", interval: 12, cost: { amount: 60 }, source: "statutory", overdue: true, next_due: "2026-01-01" }),
];

test("a column filter keeps the matching tasks, the way down to them, and the roll-ups follow it", () => {
  const f = { trade: ["Fitter"] };
  assert.equal(anyFilter(f), true);
  assert.equal(anyFilter({ trade: [] }), false);
  const kept = filterTasks(mower, f);
  assert.deepEqual(kept.map((t) => t.id), ["oil", "blade"]);
  const out = graftTasks(withRoots, kept, { prune: true });
  // Pump 2 (no fitter's task at or below it) and the motor leave the tree; the rows stay readable.
  assert.deepEqual(out.rows.get("st").kids, [taskKey("oil"), "p1"]);
  assert.deepEqual(out.rows.get("p1").kids, [taskKey("blade")]);
  assert.equal(rollupText(out.rows.get("st")), "2 tasks at and below");
  // Left out, not deleted: the row picked keeps its place for when the filter goes.
  assert.ok(out.rows.has("p2"));
  // No filter: nothing pruned.
  assert.deepEqual(graftTasks(withRoots, mower).rows.get("st").kids, [taskKey("oil"), "p1", "p2"]);
  assert.equal(filterWords(f), "Filtered by Trade");
  assert.equal(filterWords({ unit: ["hours"], interval: ["x"], package: [""] }), "Filtered by Interval, Packaged");
});

test("a filter's values come from the tasks on show in the open tree, counted against the other filters", () => {
  const out = graftTasks(withRoots, mower);
  // Only the station open: its own task and nothing under the closed positions.
  const open = new Set(["st"]);
  const shown = shownTasks(out, flatten(out, open).list);
  assert.deepEqual(shown.map((t) => t.id), ["oil"]);
  const all = shownTasks(out, flatten(out, new Set(["st", "p1", "m1", "p2"])).list);
  assert.equal(all.length, 4);
  const trades = facetValues("trade", all, {});
  assert.deepEqual(trades.map((v) => [v.label, v.count]), [["Electrician", 1], ["Fitter", 2], ["No trade", 1]]);
  // Another column's filter counts against these; a value ticked stays listed.
  const pk = facetValues("package", all, { trade: ["Fitter"], package: ["k1"] });
  assert.deepEqual(pk.map((v) => [v.label, v.count]), [["50 h service", 0], ["In no package", 2]]);
  const units = facetValues("unit", all, {});
  assert.deepEqual(units.map((v) => v.label), ["Operating hours", "Months"]);
  assert.deepEqual(facetValues("due", all, {}).map((v) => v.label), ["Overdue", "No date"]);
  assert.deepEqual(facetValues("from", all, {}).map((v) => v.label), ["RCM", "Added directly: law, regulation or standard"]);
});

test("click picks one task, Shift-click a range of tasks as drawn, Ctrl-click one more; positions aren't picked", () => {
  const out = graftTasks(withRoots, mower);
  const { list, index } = flatten(out, new Set(["st", "p1", "m1", "p2"]));
  const one = pickTasks(new Set(), list, out, taskKey("oil"), {});
  assert.deepEqual([...one.picked], [taskKey("oil")]);
  const range = pickTasks(one.picked, list, out, taskKey("belt"), { shift: true, anchor: one.anchor });
  assert.deepEqual([...range.picked].sort(), [taskKey("belt"), taskKey("blade"), taskKey("oil")].sort());
  const more = pickTasks(range.picked, list, out, taskKey("guard"), { toggle: true });
  assert.equal(more.picked.size, 4);
  const less = pickTasks(more.picked, list, out, taskKey("oil"), { toggle: true });
  assert.equal(less.picked.has(taskKey("oil")), false);
  // A plain click on a position clears the picks.
  assert.equal(pickTasks(less.picked, list, out, "p1", {}).picked.size, 0);
  // A branch closed: its tasks leave the picks; nothing gone, the same set.
  const closed = flatten(out, new Set(["st"])).index;
  assert.deepEqual([...keepShown(less.picked, closed)], []);
  assert.equal(keepShown(less.picked, index), less.picked);
});

test("a task's menu: Open…, then Package… and Add to package… for the tasks picked, greyed with the reason", () => {
  const r = { ref: { task: mower[0] } };
  const items = taskRowActions(r);
  assert.deepEqual(items.filter((i) => i.id).map((i) => i.label), ["Open…", "Package…", "Add to package…"]);
  const two = taskRowActions(r, { tasks: [mower[0], mower[1]] }).map((i) => i.id).filter(Boolean);
  assert.deepEqual(two, ["mtask-open", TASK_PACKAGE, TASK_ADD_TO, TASK_CLEAR]);
  const inOne = taskRowActions({ ref: { task: mower[2] } }).find((i) => i.id === TASK_PACKAGE);
  assert.equal(inOne.disabled, true);
  assert.match(inOne.reason, /in a package already/);
  const cant = taskRowActions({ ref: { task: { ...mower[0], why_not: "a round: it stays on its own" } } }).find((i) => i.id === TASK_ADD_TO);
  assert.match(cant.reason, /can't join a package: a round/);
  // A product's design (or view only): Open… alone.
  assert.equal(taskRowActions(r, { canPackage: false }).length, 1);
});

test("Add to package…: the packages that fit first, the same interval before the rest; one that can't says why", () => {
  const out = graftTasks(withRoots, mower);
  const pk = (id, every, unit, on = "st", extra = {}) => ({ id, name: id, cadence: { every, unit }, subject: { id: on, name: on }, status: "active", ...extra });
  const blade = mower[1];
  assert.equal(packageMisfit(pk("cal", 1, "months"), blade, out), "cal goes by the calendar, and Task blade by operating hours: put it in a package by hours on its position.");
  assert.match(packageMisfit(pk("h", 50, "hours", "p2"), blade, out), /isn't there or inside it/);
  assert.equal(packageMisfit(pk("h", 50, "hours"), blade, out), null);
  assert.deepEqual(visitFor(pk("h", 50, "hours"), mower[0]), { visit_rule: "nth", every_nth: 2 });
  assert.deepEqual(visitFor(pk("h", 50, "hours"), blade), { visit_rule: "every" });
  const ranked = rankPackages([pk("cal", 1, "months"), pk("h100", 100, "hours"), pk("h50", 50, "hours"), pk("old", 50, "hours", "st", { status: "retired" })], [blade], out);
  assert.deepEqual(ranked.map((x) => [x.pkg.id, !!x.why]), [["h50", false], ["h100", false], ["cal", true]]);
});

test("a new package goes on the lowest position over all its tasks", () => {
  const out = graftTasks(withRoots, mower);
  assert.equal(commonHolder(out, [mower[1], mower[2]]).key, "p1");
  assert.equal(commonHolder(out, [mower[2]]).key, "m1");
  assert.equal(commonHolder(out, [mower[1], mower[3]]).key, "st");
  assert.equal(TASK_COLUMNS.find((c) => c.id === "package").label, "Packaged");
});
