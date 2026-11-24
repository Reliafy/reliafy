import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { asPositionRow, explorerRowMenu, isHeadingRow } from "./explorerMenu.js";
import { focusMenu, menuProblems } from "./menuStandard.js";
import { buildDisplay, panelRow } from "./assetTree.js";
import { canPin } from "./treePin.js";
import { canIsolate, focusKinds, isolateKindOpen, levelsBelow } from "./treeIsolate.js";
import { isolateItems, maintenanceLead, summaryActions, withPin } from "./treeRowMenu.js";
import { openInItem } from "./explorerTasks.js";
import { rowActions as rcmRowActions, opensWide } from "./explorerRcm.js";
import { rowActions as fmeaRowActions } from "./explorerFmea.js";
import { measAddActions } from "./explorerMeasurements.js";
import { MODEL_POSITION_ITEMS } from "./explorerModels.js";

// A higher position (one with positions under it) has a position's menu at every depth, on every
// tab (Derryn, 23 Nov 2026: "it should share as much as possible the same menu for the lower
// items… It should also have focus"). The owner's House tree, opened at a place: House > Outdoor &
// grounds > Garden tap, House > Climate control > Bedroom air conditioner, the two tops above the
// place sent as `ancestors` (shown as via rows).
const DATA = {
  positions: [
    { id: "tap", name: "Garden tap", parent_id: null, via: "out" },
    { id: "ac", name: "Bedroom air conditioner", parent_id: null, via: "clim" },
    { id: "filter", name: "Filter", parent_id: "ac" },
  ],
  ancestors: [
    { id: "house", name: "House", parent_id: null },
    { id: "out", name: "Outdoor & grounds", parent_id: "house" },
    { id: "clim", name: "Climate control", parent_id: "house" },
  ],
  locations: [],
};
const d = buildDisplay(DATA, "positions");
const labels = (items) => items.map((it) => (it.separator ? "———" : it.heading ? `[${it.label}]` : it.label));
const GENERAL = ["Open", "Rename…", "Move to…", "Focus", "Pin this branch", "Copy link"];
const enabled = (m, label) => {
  const it = m.find((x) => x.label === label);
  assert.ok(it, `${label} is in the menu`);
  return !it.disabled;
};

// The Explorer's own steps for a row (AssetExplorer rowMenu: panelRow first, then the tab's list).
const pin = (r) => (canPin(r) ? [{ id: "pin", label: "Pin this branch" }] : []);
const focus = (r, tab) => isolateItems(r, { can: canIsolate(r, "positions", canPin), levels: levelsBelow(d, r.key), kinds: focusKinds(tab, d, r.key) });
const tree = (r) => summaryActions(panelRow(r), { mode: "positions" });
const TABS = {
  summary: (r) => withPin(summaryActions(r, { mode: "positions" }), [...focus(r, "summary"), ...pin(r)]),
  operations: (r) => [{ id: "plan-open", label: "Operating plan…" }, { separator: true },
    ...summaryActions(r, { mode: "positions" }).filter((it) => MODEL_POSITION_ITEMS.includes(it.id)), ...focus(r, "operations"), ...pin(r)],
  maintenance: (r) => [...maintenanceLead(r), ...openInItem(r), { id: "mtask-draft", label: "Package the tasks…" }, { separator: true },
    ...summaryActions(r, { mode: "positions" }).filter((it) => MODEL_POSITION_ITEMS.includes(it.id)), ...focus(r, "maintenance"), ...pin(r)],
  measurements: (r) => withPin([...measAddActions(r), { separator: true }, ...summaryActions(r, { mode: "positions" })], [...focus(r, "measurements"), ...pin(r)]),
  rcm: (r) => withPin(rcmRowActions(r, {}), [...focus(r, "rcm"), ...pin(r)]),
  fmea: (r) => withPin(fmeaRowActions(r, {}), [...focus(r, "fmea"), ...pin(r)]),
  models: (r) => [{ id: "model-life", label: "Life model", add: true, items: [{ id: "model-attach-fit", label: "Fit a life model…" }] },
    { separator: true }, ...summaryActions(r, { mode: "positions" }).filter((it) => MODEL_POSITION_ITEMS.includes(it.id)), ...focus(r, "models"), ...pin(r)],
};
const menuOn = (tab, raw) => explorerRowMenu(raw, TABS[tab](panelRow(raw)), { tree: tree(raw) });

test("a position above the place opened (a via row) is a position: its row reads as one", () => {
  const house = d.rows.get("house");
  assert.equal(house.type, "group"); // drawn muted, as context
  assert.equal(isHeadingRow(house), false);
  assert.equal(asPositionRow(house).type, "pos");
  assert.equal(panelRow(house).type, "pos");
  assert.equal(canPin(house), true);
  assert.equal(canIsolate(house, "positions", canPin), true);
  assert.equal(opensWide(house), true);
});

for (const tab of Object.keys(TABS)) {
  test(`${tab}: a position with positions under it gets the whole position menu, enabled, at every depth`, () => {
    for (const key of ["house", "clim", "ac"]) {
      const m = menuOn(tab, d.rows.get(key));
      assert.deepEqual(menuProblems(m), [], `${tab} ${key}`);
      assert.deepEqual(labels(m).slice(0, 6), GENERAL, `${tab} ${key}: the general section`);
      for (const l of ["Open", "Rename…", "Focus", "Pin this branch", "Copy link"]) assert.ok(enabled(m, l), `${tab} ${key}: ${l}`);
      assert.equal(m.at(-1).label, "Delete…", `${tab} ${key}: Delete… last`);
      assert.ok(!m.at(-1).disabled, `${tab} ${key}: Delete… enabled`);
      // Not one item says it's a heading.
      assert.ok(!JSON.stringify(m).includes("A heading for the rows"), `${tab} ${key}`);
    }
  });
}

test("Maintenance: a higher position keeps Add task…, Open in › and Package the tasks…", () => {
  const m = menuOn("maintenance", d.rows.get("house"));
  assert.deepEqual(labels(m), [...GENERAL, "———", "Add task…", "Open in", "Package the tasks…", "———", "Delete…"]);
  assert.ok(m.every((it) => !it.disabled || it.label === "Move to…"));
});

test("a position above the place opened: Move to… greyed with why (its other branches aren't sent); one in the place: enabled", () => {
  const house = menuOn("summary", d.rows.get("house")).find((it) => it.label === "Move to…");
  assert.equal(house.disabled, true);
  assert.match(house.reason, /above the place opened/);
  assert.ok(enabled(menuOn("summary", d.rows.get("ac")), "Move to…"));
});

test("a pure heading row (No class, No home yet) has no menu, not a list of greyed items", () => {
  const g = { key: "G:noclass", type: "group", ref: { name: "No class" }, kids: ["a"] };
  assert.deepEqual(explorerRowMenu(g, [{ id: "pin", label: "Pin this branch" }]), []);
});

// ---- Focus ›: What and Depth -------------------------------------------------------------------

test("Focus ›: two sections, each under its label, a line between; the depths only as deep as it goes", () => {
  const f = focusMenu(isolateItems(d.rows.get("house"), { can: true, levels: levelsBelow(d, "house"), kinds: [{ id: "tasks", label: "tasks" }] }));
  assert.deepEqual(labels(f.items), ["[What]", "Focus tasks", "———", "[Depth]", "1 level", "2 levels", "3 levels"]);
  assert.equal(levelsBelow(d, "house"), 3);
  // A row with nothing inside: one item, no labels.
  assert.deepEqual(labels(focusMenu(isolateItems(d.rows.get("filter"), { can: true })).items), ["Focus here"]);
  // Clear focus after a line.
  const on = focusMenu(isolateItems(d.rows.get("clim"), { can: true, focused: true, levels: 2 }));
  assert.deepEqual(labels(on.items), ["[What]", "Focus here", "———", "[Depth]", "1 level", "2 levels", "———", "Clear focus"]);
  assert.deepEqual(menuProblems([on]), []);
});

test("menuProblems: a section label with nothing under it", () => {
  assert.match(menuProblems([{ heading: true, label: "Depth" }, { separator: true }, { id: "x", label: "X" }]).join(), /“Depth” has nothing under it/);
});

test("focusKinds: the tab's kinds inside the row; isolateKindOpen opens the way to them and leaves them closed", () => {
  const rows = new Map([
    ["p", { key: "p", type: "pos", parent: null, kids: ["f", "q"] }],
    ["f", { key: "f", type: "fn", parent: "p", kids: ["m"] }],
    ["m", { key: "m", type: "mode", parent: "f", kids: ["t"] }],
    ["t", { key: "t", type: "task", parent: "m", kids: [] }],
    ["q", { key: "q", type: "pos", parent: "p", kids: [] }],
  ]);
  const rd = { rows: rows, roots: ["p"] };
  assert.deepEqual(focusKinds("rcm", rd, "p").map((k) => k.label), ["functions", "failure modes", "tasks"]);
  assert.deepEqual(focusKinds("fmea", rd, "p").map((k) => k.label), ["functions", "failure modes"]);
  assert.deepEqual(focusKinds("maintenance", rd, "p"), []);
  assert.deepEqual([...isolateKindOpen(rd, new Set(), "p", ["fn"])].sort(), ["p"]);
  assert.deepEqual([...isolateKindOpen(rd, new Set(), "p", ["mode"])].sort(), ["f", "p"]);
  assert.deepEqual([...isolateKindOpen(rd, new Set(["q"]), "p", ["task"])].sort(), ["f", "m", "p"]);
});

// ---- Double-click opens the details across the table: one rule --------------------------------

test("a double-click on a work package opens its details across the table, with Back to table", () => {
  assert.equal(opensWide({ type: "mpkg" }), true);
  const src = readFileSync(new URL("./views/AssetExplorer.jsx", import.meta.url), "utf8");
  assert.match(src, /if \(isPackageRow\(r\)( \|\| isPackageExtra\(r\))?\) return openPackageView\(r\.ref\.pkg, \{ wide: true \}\)/);
  assert.match(src, /<PackageSide [^>]*\n\s*expanded=\{wideDetails\} onExpand=\{expandDetails\} onCollapse=\{collapseDetails\}/);
  const side = readFileSync(new URL("./components/TaskTreeTable.jsx", import.meta.url), "utf8");
  const pkg = side.slice(side.indexOf("export function PackageSide"));
  assert.match(pkg, /expanded && onCollapse\) onCollapse\(\); else onClose\(\)/);
  assert.match(pkg, /aria-label="Back to table"/);
  // TreePane asks the one rule, not its own list of kinds.
  assert.match(readFileSync(new URL("./components/TreePane.jsx", import.meta.url), "utf8"), /onDoubleClick: table && !phone && table\.onOpen && opensWide\(r\)/);
});
