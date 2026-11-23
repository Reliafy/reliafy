import { test } from "node:test";
import assert from "node:assert/strict";
import { areaMenu, explorerRowMenu } from "./explorerMenu.js";
import { menuProblems } from "./menuStandard.js";
import { isolateItems, summaryActions, withAssetMoves } from "./treeRowMenu.js";
import { openInItem, packageRowActions, refRowActions, taskRowActions } from "./explorerTasks.js";
import { rowActions as rcmRowActions } from "./explorerRcm.js";
import { rowActions as fmeaRowActions } from "./explorerFmea.js";
import { missionRowActions } from "./explorerMissions.js";
import { rowActions as modelRowActions } from "./explorerModels.js";
import { measAddActions } from "./explorerMeasurements.js";

const labels = (items) => items.map((it) => (it.separator ? "———" : it.label));
const top = (items) => labels(items).slice(0, 6);
const GENERAL = ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link"];
const POS = { key: "p1", type: "pos", ref: { id: "p1", name: "Feed pump" }, kids: ["p2"] };
const pin = [{ id: "pin", label: "Pin this branch" }];
const focus = isolateItems(POS, { can: true, levels: 3, noun: "tasks" });
const tree = summaryActions(POS, { mode: "positions" });
const check = (name, m) => {
  assert.deepEqual(menuProblems(m), [], name);
  assert.deepEqual(top(m), GENERAL, `${name}: the general section`);
  return m;
};

test("a position on the Summary tab: general, the tree's adds and its own (the rest under More), Delete… last", () => {
  const items = [...withAssetMoves(summaryActions(POS, { mode: "positions" }), POS, { root: "p0" }), ...focus, ...pin];
  const m = check("summary", explorerRowMenu(POS, items, { tree }));
  assert.deepEqual(labels(m), [...GENERAL, "———", "New position inside", "Add failure report…", "More", "———", "Delete…"]);
  assert.deepEqual(labels(m.find((it) => it.id === "more").items), ["Log an event…", "Make this its own asset…", "Export this branch…"]);
  assert.deepEqual(labels(m.find((it) => it.id === "focus").items), ["What", "Focus tasks", "———", "Depth", "1 level", "2 levels", "3 levels"]);
});

test("a position on the Maintenance and Models tabs gets Move to… and Delete… too", () => {
  const maint = check("maintenance", explorerRowMenu(POS, [{ id: "maint-add-task", label: "Add task…" }, { id: "mtask-forecast", label: "Forecast…" },
    { id: "mtask-draft", label: "Package the tasks…" }, { separator: true }, { id: "tree-rename", label: "Rename…" }, ...focus, ...pin], { tree }));
  assert.deepEqual(labels(maint), [...GENERAL, "———", "Add task…", "Forecast…", "Package the tasks…", "———", "Delete…"]);
  assert.equal(maint[2].disabled, undefined);
});

test("a position on the Monitoring tab: its four adds in Add ›", () => {
  const m = check("monitoring", explorerRowMenu(POS, [...measAddActions(POS), { id: "plan-open", label: "Operating plan…" }, ...tree, ...focus, ...pin], { tree }));
  assert.equal(m[7].label, "Add");
  assert.equal(m[7].items.length, 4);
  assert.equal(m.at(-1).label, "Delete…");
});

test("a position on the RCM tab: Rename… and Move to… come back, Delete… after a line", () => {
  const m = check("rcm", explorerRowMenu(POS, rcmRowActions(POS), { tree }));
  assert.deepEqual(labels(m).slice(7), ["Add function", "Import worksheet…", "Export CSV", "———", "Delete…"]);
  check("fmea", explorerRowMenu(POS, fmeaRowActions(POS), { tree }));
});

test("RCM rows: one name per action, the red item last", () => {
  for (const type of ["fn", "fail", "mode"]) {
    const r = { key: "x", type, ref: { id: "x", name: "Seal leaks", decision: null }, kids: [] };
    const m = check(type, explorerRowMenu(r, rcmRowActions(r)));
    assert.equal(m.at(-1).label, "Delete…");
    assert.ok(!labels(m).some((l) => /Edit description|Open…/.test(l)), type);
  }
  const task = { key: "t", type: "task", ref: { task: { id: "t" } }, kids: [] };
  assert.equal(explorerRowMenu(task, rcmRowActions(task)).at(-1).label, "Retire…");
  const shared = { key: "t", type: "task", ref: { task: { id: "t", shared_with: 2 } }, kids: [] };
  assert.equal(explorerRowMenu(shared, rcmRowActions(shared)).at(-1).label, "Remove from this failure mode…");
});

test("Maintenance rows: a task Retire…, a package Retire…, a package's task Remove from package…; no Forecast…", () => {
  const t = { key: "mt", type: "mtask", ref: { task: { id: "a", name: "Grease" } }, kids: [] };
  const tm = check("task", explorerRowMenu(t, taskRowActions(t)));
  assert.equal(tm.at(-1).label, "Retire…");
  const p = { key: "mp", type: "mpkg", ref: { pkg: { id: "k", name: "Weekly" } }, kids: [] };
  assert.equal(check("package", explorerRowMenu(p, packageRowActions(p))).at(-1).label, "Retire…");
  const ref = { key: "mr", type: "mpref", ref: { name: "Grease", task: { id: "a" } }, kids: [] };
  assert.equal(check("ref", explorerRowMenu(ref, refRowActions(ref))).at(-1).label, "Remove from package…");
  // Open in › sits in the middle, a submenu of four, and keeps the menu to the standard.
  const withOpen = check("task with Open in", explorerRowMenu(t, [...taskRowActions(t).slice(0, 2), ...openInItem(t), ...taskRowActions(t).slice(2)]));
  assert.equal(withOpen.find((it) => it.id === "open-in").items.length, 4);
  assert.equal(withOpen.at(-1).label, "Retire…");
  // A forecast is the left menu's Spares forecast now (Derryn, 23 Nov 2026): no row offers Forecast….
  for (const menu of [tm, explorerRowMenu(p, packageRowActions(p))]) assert.ok(!labels(menu).some((l) => /forecast/i.test(l)));
});

test("model, mission and phase rows: Unlink… and Delete… are red and last", () => {
  const link = { model_type: "model", role: "fitted", model: { kind: "Weibull", path: "/m/1" } };
  const pm = { key: "L:1", type: "pmodel", ref: { link }, kids: [] };
  const m = check("model", explorerRowMenu(pm, modelRowActions(pm)));
  assert.equal(m.at(-1).label, "Unlink…");
  assert.equal(m.at(-1).danger, true);
  const mission = { key: "MS:1", type: "mission", ref: { mission: { phases: 2 }, rbd: {} }, kids: [] };
  assert.equal(check("mission", explorerRowMenu(mission, missionRowActions(mission))).at(-1).label, "Delete…");
});

test("a heading row has no menu of greyed items: none at all, or only what it can do", () => {
  const g = explorerRowMenu({ key: "g", type: "group", ref: { name: "No class" }, kids: ["a"] }, [...isolateItems({ key: "g", type: "group", kids: ["a"] }, { can: false }), ...pin]);
  assert.deepEqual(g, []);
  // An RCM placeholder keeps its add, and nothing greyed.
  const nofail = explorerRowMenu({ key: "nf", type: "nofail", ref: {}, kids: [] }, [{ id: "add-fail", label: "Add functional failure…" }]);
  assert.deepEqual(labels(nofail), ["Add functional failure…"]);
  assert.ok(!nofail.some((it) => it.disabled));
  const area = areaMenu({ add: { label: "New position" }, focused: true, pinned: true });
  assert.deepEqual(labels(area), ["New position", "Open to a level", "Clear focus", "Show whole tree"]);
  assert.deepEqual(menuProblems(area), []);
});
