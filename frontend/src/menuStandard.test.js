import { test } from "node:test";
import assert from "node:assert/strict";
import { MAX_ITEMS, buildMenu, counted, focusMenu, isAdd, menuProblems, rowLink, standardMenu, tidy } from "./menuStandard.js";

const labels = (items) => items.map((it) => (it.separator ? "———" : it.label));

test("three sections: the general top, the contextual middle, one red item last after a line", () => {
  const m = buildMenu({
    general: { open: { id: "open" }, rename: { id: "rename" }, move: "It stays put.", focus: { id: "focus", items: [{ id: "isolate:all", label: "Focus here" }] },
      pin: { id: "pin" }, copy: { id: "row-copy-link" } },
    adds: [{ id: "a", label: "Add task…" }],
    actions: [{ id: "b", label: "Optimise…" }],
    destroy: { id: "tree-delete", kind: "delete" },
  });
  assert.deepEqual(labels(m), ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link", "———", "Add task…", "Optimise…", "———", "Delete…"]);
  assert.equal(m[2].disabled, true);
  assert.equal(m[2].reason, "It stays put.");
  assert.equal(m.at(-1).danger, true);
  assert.deepEqual(menuProblems(m), []);
});

test("a line between adds and actions only when the middle has more than four", () => {
  const four = buildMenu({ adds: [{ id: "1", label: "Add a" }, { id: "2", label: "Add b" }], actions: [{ id: "3", label: "c" }, { id: "4", label: "d" }] });
  assert.ok(!four.some((it) => it.separator));
  const five = buildMenu({ adds: [{ id: "1", label: "Add a" }, { id: "2", label: "Add b" }], actions: [{ id: "3", label: "c" }, { id: "4", label: "d" }, { id: "5", label: "e" }] });
  assert.deepEqual(labels(five), ["Add a", "Add b", "———", "c", "d", "e"]);
});

test("at most ten at the top level: the middle's overflow folds into More ›, a submenu's items inline", () => {
  const items = [
    { id: "tree-rename", label: "Rename…" }, { id: "tree-move", label: "Move to…" },
    { id: "isolate:all", label: "Focus models" }, { id: "isolate", label: "Focus to a depth", items: [{ id: "isolate:1", label: "1 level" }] },
    { id: "pin", label: "Pin this branch" },
    { id: "life", label: "Life model", add: true, items: [{ id: "fit", label: "Fit a life model…" }] },
    { id: "rbd", label: "RBD", add: true, items: [{ id: "b", label: "Build from what's inside…" }] },
    { id: "pred", label: "Prediction", add: true, items: [{ id: "p", label: "Add a prediction (parts count)…" }] },
    { id: "mission-new", label: "Add a mission…" },
    { separator: true },
    { id: "tree-delete", label: "Delete…", danger: true },
  ];
  const m = standardMenu(items, { general: { open: { id: "row-open" }, copy: { id: "row-copy-link" } } });
  assert.deepEqual(labels(m), ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link", "———", "Life model", "RBD", "More", "———", "Delete…"]);
  const more = m.find((it) => it.id === "more");
  assert.deepEqual(labels(more.items), ["Add a prediction (parts count)…", "———", "Add a mission…"]);
  assert.deepEqual(labels(m.find((it) => it.id === "focus").items), ["What", "Focus models", "———", "Depth", "1 level"]);
  assert.ok(m.filter((it) => !it.separator).length <= MAX_ITEMS);
  assert.deepEqual(menuProblems(m), []);
});

test("a builder's old menu is sorted: Open and Rename up top with one name, Delete last, red, after a line", () => {
  const m = standardMenu([
    { id: "add-std", label: "Add a performance standard…" },
    { id: "add-fail", label: "Add functional failure" },
    { id: "open", label: "Open…" },
    { id: "rename", label: "Edit description" },
    { id: "delete", label: "Delete function…", danger: true },
    { id: "isolate:all", label: "Focus failure modes" },
    { id: "focus-clear", label: "Clear focus" },
  ]);
  assert.deepEqual(labels(m), ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link", "———",
    "Add a performance standard…", "Add functional failure", "———", "Delete…"]);
  assert.deepEqual(labels(m[3].items), ["Focus failure modes", "———", "Clear focus"]);
  for (const i of [2, 4, 5]) assert.ok(m[i].disabled && m[i].reason, m[i].label);
  assert.deepEqual(menuProblems(m), []);
});

test("Retire, Unlink and Remove from keep their kind; a second red item isn't red", () => {
  assert.equal(standardMenu([{ id: "remove-task", label: "Retire the task…", danger: true }]).at(-1).label, "Retire…");
  assert.equal(standardMenu([{ id: "model-unlink", label: "Unlink…" }]).at(-1).label, "Unlink…");
  assert.equal(standardMenu([{ id: "remove-task", label: "Remove from this failure mode…", danger: true }]).at(-1).label, "Remove from this failure mode…");
  const two = standardMenu([{ id: "x", label: "Delete a…", danger: true }, { id: "y", label: "Delete b…", danger: true }]);
  assert.equal(two.filter((it) => it.danger).length, 1);
});

test("a group of middle items in one submenu (Add ›), and an area's menu with no row slots", () => {
  const m = standardMenu([
    { id: "meas-add-point", label: "Add a measuring point…" }, { id: "meas-add-setting", label: "Add a setting…" },
    { id: "plan-open", label: "Operating plan…" },
  ], { skip: ["open", "rename", "move", "focus", "pin", "copy"], group: { id: "meas-add", label: "Add", add: true, test: (it) => it.id.startsWith("meas-add-") } });
  assert.deepEqual(labels(m), ["Add", "Operating plan…"]);
  assert.deepEqual(labels(m[0].items), ["Add a measuring point…", "Add a setting…"]);
});

test("the checks: too many, a greyed item with no reason, the red item not last", () => {
  const many = Array.from({ length: 11 }, (_, i) => ({ id: `i${i}`, label: `Item ${i}` }));
  assert.match(menuProblems(many).join(), /11 items/);
  assert.match(menuProblems([{ id: "a", label: "A", disabled: true, title: "why" }]).join(), /no reason/);
  assert.match(menuProblems([{ id: "d", label: "Delete…", danger: true }, { id: "a", label: "A" }]).join(), /isn't last/);
  assert.match(menuProblems([{ id: "a", label: "A" }, { id: "d", label: "Delete…", danger: true }]).join(), /no line/);
});

test("words: counts for several rows, adds, focus, tidy, links", () => {
  assert.equal(counted("Package…", 3), "Package 3 tasks…");
  assert.equal(counted("Package…", 1), "Package…");
  assert.ok(isAdd({ label: "New position inside" }));
  assert.ok(!isAdd({ label: "Add to library…" }));
  assert.ok(!isAdd({ label: "Add 3 tasks to a package…" }));
  assert.equal(focusMenu([]), null);
  assert.deepEqual(labels(tidy([{ separator: true }, { id: "a", label: "A" }, { separator: true }, { separator: true }, { id: "b", label: "B" }, { separator: true }])), ["A", "———", "B"]);
  assert.equal(rowLink("https://x.test/asset-register/explorer?tab=rcm&sel=1", "p9"), "https://x.test/asset-register/explorer?tab=rcm&sel=p9");
});

test("a greyed item folds into More before one that can be used now", () => {
  const actions = [
    { id: "o", label: "Optimise…", disabled: true, reason: "One task at a time." },
    { id: "p", label: "Package 2 tasks…" }, { id: "a", label: "Add 2 tasks to a package…" }, { id: "c", label: "Clear the selection" },
  ];
  const m = buildMenu({ general: { open: "x", rename: "x", move: "x", focus: "x", pin: "x", copy: "x" }, actions, destroy: { id: "r", kind: "retire" } });
  assert.deepEqual(labels(m).slice(7, 10), ["Package 2 tasks…", "Add 2 tasks to a package…", "More"]);
  assert.deepEqual(labels(m.find((it) => it.id === "more").items), ["Optimise…", "Clear the selection"]);
});
