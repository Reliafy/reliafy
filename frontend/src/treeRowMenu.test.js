import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay } from "./assetTree.js";
import { TAB_LEADS, addsFirst, isolateItems, liveKids, lsaLead, moveTargets, showsAddRow, summaryActions, tabMenu, viewOnlyReason, withPin } from "./treeRowMenu.js";
import { designActions } from "./products.js";
import { measAddActions } from "./explorerMeasurements.js";

const DATA = {
  positions: [
    { id: "pool", name: "Swimming pool", parent_id: null },
    { id: "circ", name: "Circulation", parent_id: "pool" },
    { id: "pump", name: "Filter pump", parent_id: "circ", item: { id: "u1", name: "Pump unit" } },
    { id: "valve", name: "Valve", parent_id: "circ", status: { open_work: 2 } },
    { id: "skim", name: "Skimmer", parent_id: "circ" },
    { id: "turbo", name: "Turbo slot", parent_id: "eng", carried_by: { id: "eng", name: "Engine" } },
  ],
  locations: [
    { id: "site", name: "Site", parent_id: null },
    { id: "shed", name: "Pump shed", parent_id: "site" },
    { id: "store", name: "Store", parent_id: "site" },
  ],
  spares: [], unhomed: [],
};

const ids = (items) => items.map((i) => i.id);
const ITEM_ROW = { key: "u1", type: "item", ref: { id: "u1", name: "Pump unit" }, kids: [] };
const opts = (mode, extra = {}) => ({ mode, kidsOf: (k) => liveKids(DATA.positions).get(k) || 0, ...extra });

test("a position's menu: new inside, add failure report, rename, move, delete; Pin goes before Delete", () => {
  const d = buildDisplay(DATA, "positions");
  const skim = summaryActions(d.rows.get("skim"), opts("positions"));
  assert.deepEqual(ids(skim), ["tree-new", "report-new", "event-log", "tree-rename", "tree-move", "tree-export", "tree-delete"]);
  assert.deepEqual(skim.map((i) => i.label), ["New position inside", "Add failure report…", "Log an event…", "Rename…", "Move to…", "Export this branch…", "Delete…"]);
  assert.ok(skim.every((i) => !i.disabled));
  assert.equal(skim.at(-1).danger, true);
  assert.deepEqual(ids(withPin(skim, [{ id: "pin", label: "Pin this branch" }])),
    ["tree-new", "report-new", "event-log", "tree-rename", "tree-move", "tree-export", "pin", "tree-delete"]);
  assert.deepEqual(ids(withPin([{ id: "tree-rename" }], [{ id: "pin" }])), ["tree-rename", "pin"]);
  // Locations: a position's place there is where it is, so no Move.
  assert.deepEqual(ids(summaryActions({ key: "skim", type: "pos", ref: DATA.positions[4], kids: [] }, opts("locations"))),
    ["tree-new", "report-new", "event-log", "tree-rename", "tree-export", "tree-delete"]);
});

test("Delete is never greyed for what's inside: a delete takes it all (and Undo brings it back)", () => {
  const d = buildDisplay(DATA, "positions");
  const del = (key) => summaryActions(d.rows.get(key), opts("positions")).find((i) => i.id === "tree-delete");
  for (const key of ["pump", "circ", "pool", "valve", "skim"]) {
    assert.equal(del(key).disabled, undefined, key);
    assert.equal(del(key).danger, true);
  }
  // A position an item carries moves with the item.
  const turbo = summaryActions({ key: "turbo", type: "pos", ref: DATA.positions[5], kids: [] }, opts("positions"));
  assert.match(turbo.find((i) => i.id === "tree-move").reason, /moves with it/);
});

test("a team that's view only: every change greyed with the reason; Pin still works", () => {
  assert.equal(viewOnlyReason(null), null);
  assert.equal(viewOnlyReason({ can_edit: true }), null);
  assert.match(viewOnlyReason({ frozen: true }), /lapsed/);
  assert.match(viewOnlyReason({ can_edit: false }), /needs a Pro plan/);
  const d = buildDisplay(DATA, "positions");
  const items = summaryActions(d.rows.get("skim"), opts("positions", { viewOnly: "View only: editing this team needs a Pro plan." }));
  // Every change greyed; Export this branch… only reads, so it stays.
  assert.ok(items.filter((i) => i.id !== "tree-export").every((i) => i.disabled && /View only/.test(i.reason)));
  assert.equal(items.find((i) => i.id === "tree-export").disabled, undefined);
  const withPinned = withPin(items, [{ id: "pin", label: "Pin this branch" }]);
  assert.equal(withPinned.find((i) => i.id === "pin").disabled, undefined);
});

test("locations: new position here, new inside, rename, move, delete; items: rename (never delete); headings: nothing", () => {
  const d = buildDisplay(DATA, "locations");
  assert.deepEqual(summaryActions(d.rows.get("shed"), opts("locations")).map((i) => i.label),
    ["New position here", "New location inside", "Rename…", "Move to…", "Delete…"]);
  // A product's layout or a place an item carries holds no positions of its own.
  const design = { key: "lay", type: "loc", ref: { name: "Arm", design_of: { id: "p1" } }, kids: [] };
  assert.equal(summaryActions(design, opts("locations"))[0].id, "tree-new");
  // An item row (a spare, or one with no home yet).
  assert.deepEqual(ids(summaryActions(ITEM_ROW, opts("locations"))), ["tree-rename"]);
  assert.deepEqual(summaryActions({ key: "G:nohome", type: "group", ref: { name: "No home yet" }, kids: [] }, opts("locations")), []);
  assert.deepEqual(summaryActions(null), []);
});

test("Move to…: every position or location but the row itself and what's inside it", () => {
  const where = (list) => list.map((t) => `${"-".repeat(t.depth)}${t.id}`);
  // Circulation can't go inside itself, the pump, the valve or the skimmer.
  assert.deepEqual(where(moveTargets(DATA.positions, "circ")), ["pool", "turbo"]);
  // The skimmer can go anywhere else, its own parent included (picking it changes nothing).
  assert.deepEqual(where(moveTargets(DATA.positions, "skim")), ["pool", "-circ", "--pump", "--valve", "turbo"]);
  assert.deepEqual(where(moveTargets(DATA.locations, "site")), []);
  assert.deepEqual(where(moveTargets(DATA.locations, "shed")), ["site", "-store"]);
  assert.deepEqual(moveTargets(null, "x"), []);
});

test("Isolate: a submenu of levels; just Isolate on a row with nothing inside; nothing where it can't", () => {
  const items = isolateItems({ key: "a", kids: ["b"] }, { can: true });
  assert.equal(items.length, 1);
  assert.equal(items[0].label, "Focus");
  assert.deepEqual(items[0].items.map((i) => [i.id, i.label]), [
    ["isolate:1", "With 1 level open"], ["isolate:2", "With 2 levels open"], ["isolate:3", "With 3 levels open"], ["isolate:all", "With everything open"],
  ]);
  assert.deepEqual(isolateItems({ key: "m", kids: [] }, { can: true }), [{ id: "isolate:1", label: "Focus" }]);
  assert.deepEqual(isolateItems({ key: "a", kids: ["b"] }, { can: false }), []);
  // Before Delete, with Pin this branch after it.
  const skim = summaryActions({ key: "a", type: "pos", kids: ["b"], ref: {} }, { mode: "positions" });
  assert.deepEqual(withPin(skim, [...items, { id: "pin" }]).map((i) => i.id), ["tree-new", "report-new", "event-log", "tree-rename", "tree-move", "tree-export", "isolate", "pin", "tree-delete"]);
});

test("Add failure report…: positions only (a report sits at a position), greyed when the team is view only", () => {
  const d = buildDisplay(DATA, "positions");
  const add = summaryActions(d.rows.get("pump"), opts("positions")).find((i) => i.id === "report-new");
  assert.equal(add.label, "Add failure report…");
  assert.equal(add.disabled, undefined);
  assert.ok(!summaryActions(buildDisplay(DATA, "locations").rows.get("shed"), opts("locations")).some((i) => i.id === "report-new"));
  assert.ok(!summaryActions(ITEM_ROW, opts("locations")).some((i) => i.id === "report-new"));
  const viewOnly = summaryActions(d.rows.get("pump"), opts("positions", { viewOnly: "View only: the team's Pro plan has lapsed." }))
    .find((i) => i.id === "report-new");
  assert.equal(viewOnly.disabled, true);
  assert.match(viewOnly.reason, /View only/);
});

test("Log an event…: positions only, greyed when the team is view only", () => {
  const d = buildDisplay(DATA, "positions");
  const log = summaryActions(d.rows.get("pump"), opts("positions")).find((i) => i.id === "event-log");
  assert.equal(log.label, "Log an event…");
  assert.ok(!summaryActions(buildDisplay(DATA, "locations").rows.get("shed"), opts("locations")).some((i) => i.id === "event-log"));
  const viewOnly = summaryActions(d.rows.get("pump"), opts("positions", { viewOnly: "View only." })).find((i) => i.id === "event-log");
  assert.equal(viewOnly.disabled, true);
});

test("New position inside is first on the Summary tab only: another tab's adds come first, then a line", () => {
  const d = buildDisplay(DATA, "positions");
  const skim = summaryActions(d.rows.get("skim"), opts("positions"));
  const pin = [{ id: "isolate:1", label: "Focus" }, { id: "pin", label: "Pin this branch" }];
  // Summary: unchanged (the changes to the tree, Focus and Pin before Delete…).
  assert.equal(skim[0].id, "tree-new");
  assert.deepEqual(ids(tabMenu("summary", skim, { pin })), ["tree-new", "report-new", "event-log", "tree-rename", "tree-move", "tree-export", "isolate:1", "pin", "tree-delete"]);
  // Failure reports: Add failure report… first, a line, then the rest as they were (New position inside kept).
  const reports = tabMenu("reports", skim);
  assert.deepEqual(ids(reports), ["report-new", undefined, "tree-new", "event-log", "tree-rename", "tree-move", "tree-export", "tree-delete"]);
  assert.equal(reports[1].separator, true);
  assert.deepEqual(TAB_LEADS.reports, ["report-new"]);
  // Measurements: its four adds, a line, then the Summary menu.
  const meas = addsFirst(measAddActions(d.rows.get("skim")), skim);
  assert.deepEqual(ids(meas).slice(0, 6), ["meas-add-point", "meas-add-setting", "meas-add-consumable", "meas-add-channel", undefined, "tree-new"]);
  // Pin this branch still goes before Delete….
  assert.deepEqual(ids(withPin(meas, [{ id: "pin", label: "Pin this branch" }])).slice(-2), ["pin", "tree-delete"]);
  assert.deepEqual(addsFirst([], skim), skim);
});

test("the LSA tab: Package the tasks here… leads a position's and a place's menu (never a design's row)", () => {
  const d = buildDisplay(DATA, "positions");
  const row = d.rows.get("skim");
  const pin = [{ id: "isolate:1", label: "Focus" }, { id: "pin", label: "Pin this branch" }];
  const lead = lsaLead(row);
  assert.deepEqual(lead, [{ id: "lsa-package", label: "Package the tasks here…" }]);
  const menu = tabMenu("lsa", summaryActions(row, opts("positions")), { lead, pin });
  assert.deepEqual(menu.map((i) => i.label || "---"), [
    "Package the tasks here…", "---", "New position inside", "Add failure report…", "Log an event…", "Rename…", "Move to…", "Export this branch…", "Focus", "Pin this branch", "Delete…",
  ]);
  // A place has packages too.
  const shed = buildDisplay(DATA, "locations").rows.get("shed");
  assert.deepEqual(tabMenu("lsa", summaryActions(shed, opts("locations")), { lead: lsaLead(shed), pin }).map((i) => i.label || "---"),
    ["Package the tasks here…", "---", "New position here", "New location inside", "Rename…", "Move to…", "Focus", "Pin this branch", "Delete…"]);
  // View only: greyed with the reason, like every change.
  const off = lsaLead(row, { viewOnly: "View only: the team's Pro plan has lapsed." })[0];
  assert.equal(off.disabled, true);
  assert.match(off.reason, /View only/);
  // A design's row (a design has no packages), an item, a heading: nothing of the tab's own.
  assert.deepEqual(lsaLead(row, { design: true }), []);
  assert.deepEqual(lsaLead(ITEM_ROW), []);
  assert.deepEqual(lsaLead(null), []);
});

test("a tab with nothing of its own for a row: the changes to the tree go last, after Focus and Pin", () => {
  const d = buildDisplay(DATA, "positions");
  const pin = [{ id: "isolate:1", label: "Focus" }, { id: "pin", label: "Pin this branch" }];
  const labels = (items) => items.map((i) => i.label || "---");
  // A design's position on the LSA tab (no failure reports or events in a design).
  const inDesign = designActions(summaryActions(d.rows.get("skim"), opts("positions")), true, { row: d.rows.get("skim") });
  assert.deepEqual(labels(tabMenu("lsa", inDesign, { lead: lsaLead(d.rows.get("skim"), { design: true }), pin })),
    ["Focus", "Pin this branch", "---", "New position inside", "Rename…", "Move to…", "Delete…"]);
  // The product's own row keeps Build an item… first: it isn't a change to the tree.
  const product = { key: "pool", type: "pos", ref: { id: "pool", name: "Quadcopter", design: {} }, kids: ["circ"] };
  assert.deepEqual(labels(tabMenu("lsa", designActions(summaryActions(product, opts("positions")), true, { row: product }), { pin })),
    ["Build an item…", "Focus", "Pin this branch", "---", "New position inside", "Rename…", "Move to…", "Delete…"]);
  // A place on Failure reports has no report to add (a report sits at a position).
  const shed = summaryActions(buildDisplay(DATA, "locations").rows.get("shed"), opts("locations"));
  assert.deepEqual(labels(tabMenu("reports", shed, { pin })), ["Focus", "Pin this branch", "---", "New position here", "New location inside", "Rename…", "Move to…", "Delete…"]);
  // Any other plain-tree tab (Parts and stock, Classes, when they're switched on): the same rule.
  assert.deepEqual(labels(tabMenu("parts", shed, { pin })), ["Focus", "Pin this branch", "---", "New position here", "New location inside", "Rename…", "Move to…", "Delete…"]);
  assert.deepEqual(labels(tabMenu("classes", summaryActions(d.rows.get("skim"), opts("positions")), { pin })),
    ["Add failure report…", "Log an event…", "Export this branch…", "Focus", "Pin this branch", "---", "New position inside", "Rename…", "Move to…", "Delete…"]);
  // No line with nothing on one side of it; an item's Rename… goes last as well.
  assert.deepEqual(labels(tabMenu("reports", shed)), ["New position here", "New location inside", "Rename…", "Move to…", "Delete…"]);
  assert.deepEqual(labels(tabMenu("reports", summaryActions(ITEM_ROW, opts("locations")), { pin })), ["Focus", "Pin this branch", "---", "Rename…"]);
});

test("the tree's last row (+ New position inside …) shows on the Summary tab only", () => {
  assert.equal(showsAddRow("summary"), true);
  assert.equal(showsAddRow(undefined), true); // no tab in the address: Summary
  for (const tab of ["rcm", "fmea", "models", "measurements", "missions", "lsa", "reports"]) {
    assert.equal(showsAddRow(tab), false, tab);
  }
});
