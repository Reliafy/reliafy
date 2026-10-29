import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay } from "./assetTree.js";
import { isolateItems, liveKids, moveTargets, retireBlock, summaryActions, viewOnlyReason, withPin } from "./treeRowMenu.js";

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
const opts = (mode, extra = {}) => ({ mode, kidsOf: (k) => liveKids(DATA.positions).get(k) || 0, ...extra });

test("a position's menu: new inside, rename, move, retire; Pin goes before Retire", () => {
  const d = buildDisplay(DATA, "positions");
  const skim = summaryActions(d.rows.get("skim"), opts("positions"));
  assert.deepEqual(ids(skim), ["tree-new", "tree-rename", "tree-move", "tree-retire"]);
  assert.deepEqual(skim.map((i) => i.label), ["New position inside", "Rename…", "Move to…", "Retire…"]);
  assert.ok(skim.every((i) => !i.disabled));
  assert.equal(skim.at(-1).danger, true);
  assert.deepEqual(ids(withPin(skim, [{ id: "pin", label: "Pin this branch" }])),
    ["tree-new", "tree-rename", "tree-move", "pin", "tree-retire"]);
  assert.deepEqual(ids(withPin([{ id: "tree-rename" }], [{ id: "pin" }])), ["tree-rename", "pin"]);
  // Flat: the same. Locations: a position's place there is where it is, so no Move.
  assert.deepEqual(ids(summaryActions(buildDisplay(DATA, "flat").rows.get("skim"), opts("flat"))),
    ["tree-new", "tree-rename", "tree-move", "tree-retire"]);
  assert.deepEqual(ids(summaryActions({ key: "skim", type: "pos", ref: DATA.positions[4], kids: [] }, opts("locations"))),
    ["tree-new", "tree-rename", "tree-retire"]);
});

test("Retire is greyed with the reason when the tree already shows the server would refuse", () => {
  const d = buildDisplay(DATA, "positions");
  const retire = (key) => summaryActions(d.rows.get(key), opts("positions")).find((i) => i.id === "tree-retire");
  assert.match(retire("pump").reason, /Something is fitted here/);
  assert.equal(retire("pump").disabled, true);
  assert.match(retire("circ").reason, /^3 positions are inside it\. Move or retire them first\.$/);
  assert.match(retire("pool").reason, /^A position is inside it\. Move or retire it first\.$/);
  assert.match(retire("valve").reason, /open work orders/);
  assert.equal(retire("skim").disabled, undefined);
  assert.equal(retireBlock({ ref: {} }, 0), null);
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
  assert.ok(items.every((i) => i.disabled && /View only/.test(i.reason)));
  const withPinned = withPin(items, [{ id: "pin", label: "Pin this branch" }]);
  assert.equal(withPinned.find((i) => i.id === "pin").disabled, undefined);
});

test("locations: new inside, rename, move (no retiring a location); items: rename; headings: nothing", () => {
  const d = buildDisplay(DATA, "locations");
  assert.deepEqual(summaryActions(d.rows.get("shed"), opts("locations")).map((i) => i.label),
    ["New location inside", "Rename…", "Move to…"]);
  const items = buildDisplay(DATA, "items");
  assert.deepEqual(ids(summaryActions(items.rows.get("u1"), opts("items"))), ["tree-rename"]);
  assert.deepEqual(summaryActions(items.rows.get("G:fitted"), opts("items")), []);
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
  assert.equal(items[0].label, "Isolate");
  assert.deepEqual(items[0].items.map((i) => [i.id, i.label]), [
    ["isolate:1", "With 1 level open"], ["isolate:2", "With 2 levels open"], ["isolate:3", "With 3 levels open"], ["isolate:all", "With everything open"],
  ]);
  assert.deepEqual(isolateItems({ key: "m", kids: [] }, { can: true }), [{ id: "isolate:1", label: "Isolate" }]);
  assert.deepEqual(isolateItems({ key: "a", kids: ["b"] }, { can: false }), []);
  // Before Retire, with Pin this branch after it.
  const skim = summaryActions({ key: "a", type: "pos", kids: ["b"], ref: {} }, { mode: "positions" });
  assert.deepEqual(withPin(skim, [...items, { id: "pin" }]).map((i) => i.id), ["tree-new", "tree-rename", "tree-move", "isolate", "pin", "tree-retire"]);
});
