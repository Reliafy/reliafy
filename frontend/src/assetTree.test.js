import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ARRANGEMENTS, ancestorsOf, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, findByPrefix, flatten, insideWords, levelSet, loadTreeState, markersOf, pinnedRows, saveTreeState,
  statusWords, windowOf,
} from "./assetTree.js";

// A house and a truck whose engine carries a turbo slot, plus an engine on the
// bench carrying an alternator slot; a store with a spare.
const DATA = {
  positions: [
    { id: "house", name: "House", parent_id: null, location_id: "site" },
    { id: "zone10", name: "Zone 10", parent_id: "house", position_class: "Solenoid" },
    { id: "zone2", name: "Zone 2", parent_id: "house", item: { id: "i2", name: "Valve", serial: "V-77", status: { overdue: 1 } },
      status: { overdue: 2 }, location: { id: "site", name: "Site", inherited: true } },
    { id: "pool", name: "pool pump", parent_id: "house", location_id: "shed", status: { open_work: 1, alarms: 1 } },
    { id: "seal", name: "Shaft seal", parent_id: "pool", status: { overdue: 1, next_due: "2026-01-01" } },
    { id: "truck", name: "Truck 14", parent_id: null, item: { id: "eng", name: "Engine" } },
    { id: "turbo", name: "Turbo", parent_id: "truck", carried_by: { id: "eng", name: "Engine" }, status: { open_work: 1 } },
    { id: "alt", name: "Alternator", parent_id: null, carried_by: { id: "bench", name: "Engine B" } },
  ],
  locations: [
    { id: "site", name: "Site", parent_id: null },
    { id: "shed", name: "Shed", parent_id: "site" },
    { id: "store", name: "Store A", parent_id: null },
  ],
  spares: [{ id: "sp", name: "Spare seal", serial: "S-1", location_id: "store" }],
  unhomed: [{ id: "bench", name: "Engine B" }, { id: "junk", name: "Old pump" }],
};

const names = (d, keys) => keys.map((k) => d.rows.get(k).ref.name);

test("arranged by positions: natural order, carried positions under their item's position", () => {
  const d = buildDisplay(DATA, "positions");
  assert.deepEqual(names(d, d.roots), ["House", "Truck 14", "On items fitted nowhere"]);
  assert.deepEqual(names(d, d.rows.get("house").kids), ["pool pump", "Zone 2", "Zone 10"]);
  assert.deepEqual(d.rows.get("truck").kids, ["turbo"]);
  assert.deepEqual(names(d, d.rows.get("G:loose").kids), ["Engine B"]);
  assert.deepEqual(d.rows.get("bench").kids, ["alt"]);
  // Every position once.
  assert.equal([...d.rows.values()].filter((r) => r.type === "pos").length, DATA.positions.length);
});

test("roll-ups: a row's own status plus everything inside it", () => {
  const d = buildDisplay(DATA, "positions");
  const house = d.rows.get("house");
  assert.deepEqual({ ...house.sum }, { overdue: 3, open_work: 1, alarms: 1, next_due: "2026-01-01", positions: 4, empty: 1, not_analysed: 0 });
  assert.equal(house.own.overdue, 0);
  assert.equal(insideWords(house), "4 positions · 1 empty");
  assert.deepEqual(markersOf(house).map((m) => [m.kind, m.text, m.label]), [
    ["overdue", "3", "3 overdue tasks inside"],
    ["open", "1", "1 open work order inside"],
    ["alarm", "!", "1 reading past an alarm limit inside"],
  ]);
  assert.deepEqual(markersOf(d.rows.get("zone2")).map((m) => m.label), ["2 overdue tasks"]);
  assert.deepEqual(statusWords(d.rows.get("pool")).map((w) => w.text),
    ["1 open work order", "1 reading past an alarm limit", "1 overdue inside"]);
});

test("arranged by locations: placed positions, spares, then the places inside; no home last", () => {
  const d = buildDisplay(DATA, "locations");
  assert.deepEqual(names(d, d.roots), ["Site", "Store A", "No home yet"]);
  // The pool pump is set at the shed, so it's there, not under the house.
  assert.deepEqual(names(d, d.rows.get("site").kids), ["House", "Shed"]);
  assert.deepEqual(names(d, d.rows.get("house").kids), ["Zone 2", "Zone 10"]);
  assert.deepEqual(names(d, d.rows.get("shed").kids), ["pool pump"]);
  assert.deepEqual(names(d, d.rows.get("store").kids), ["Spare seal"]);
  // The truck is at no place; the bench engine (carrying a position) and the
  // old pump are neither fitted nor placed.
  assert.deepEqual(names(d, d.rows.get("G:nohome").kids), ["Truck 14", "Engine B", "Old pump"]);
  assert.equal(d.rows.get("junk").type, "item");
  assert.equal([...d.rows.values()].filter((r) => r.type === "pos").length, DATA.positions.length);
  assert.equal(d.rows.get("site").sum.positions, 5);
});

test("by items: every item once, A to Z, fitted, then kept at a place, then no home", () => {
  const d = buildDisplay(DATA, "items");
  assert.deepEqual(names(d, d.roots), ["Fitted", "At a location, not fitted", "No home yet"]);
  assert.deepEqual(names(d, d.rows.get("G:fitted").kids), ["Engine", "Valve"]);
  assert.deepEqual(names(d, d.rows.get("G:placed").kids), ["Spare seal"]);
  assert.deepEqual(names(d, d.rows.get("G:unhomed").kids), ["Engine B", "Old pump"]);
  assert.equal(d.items, 5);
  assert.equal([...d.rows.values()].filter((r) => r.type === "pos").length, 0); // no "Elsewhere" group
  // What the panel says: the position it's fitted to, where that is; the place a spare is kept.
  const valve = d.rows.get("i2");
  assert.deepEqual(valve.ref.fitted_to, { id: "zone2", name: "Zone 2" });
  assert.deepEqual(valve.ref.place, { id: "site", name: "Site" });
  assert.deepEqual(d.rows.get("sp").ref.place, { id: "store", name: "Store A" });
  // The item's own status, not its position's.
  assert.equal(valve.own.overdue, 1);
  assert.equal(d.rows.get("G:fitted").sum.overdue, 1);
  // Found by serial; with the items list, by class, make and model too.
  assert.deepEqual([...computeFilter(d, { query: "v-77" }).match], ["i2"]);
  assert.deepEqual([...computeFilter(d, { query: "s-1" }).match], ["sp"]);
  const list = [
    { id: "i2", name: "Valve", item_class: { id: "c", name: "Solenoid valve" }, manufacturer_entry: { name: "Hunter" }, model: "PGV-101" },
    { id: "new", name: "Brand new spare", serial: "N-1", fitted_to: null, location: null },
  ];
  const e = buildDisplay(DATA, "items", list);
  assert.deepEqual([...computeFilter(e, { query: "hunter pgv" }).match], ["i2"]);
  assert.deepEqual([...computeFilter(e, { query: "solenoid valve" }).match], ["i2"]);
  // An item the tree hasn't caught up with yet still shows.
  assert.deepEqual(names(e, e.rows.get("G:unhomed").kids), ["Brand new spare", "Engine B", "Old pump"]);
  // Nothing at all: no groups.
  assert.equal(buildDisplay({ positions: [], locations: [] }, "items").roots.length, 0);
});

test("the arrangement from the address, else the last one used; the Explorer's addresses", () => {
  assert.deepEqual(ARRANGEMENTS.map((a) => a.label), ["Positions", "Locations", "Items", "Flat"]);
  assert.equal(arrangementOf("items", "locations"), "items");
  assert.equal(arrangementOf(null, "locations"), "locations");
  assert.equal(arrangementOf("nonsense", null), "positions");
  assert.equal(explorerPath(), "/asset-register/explorer?arrange=positions");
  assert.equal(explorerPath("items", { sel: "i 1", place: "" }), "/asset-register/explorer?arrange=items&sel=i+1");
});

test("switching arrangements keeps the same thing picked where it can", () => {
  const pos = buildDisplay(DATA, "positions");
  const items = buildDisplay(DATA, "items");
  const loc = buildDisplay(DATA, "locations");
  // A position: itself, or in Items the item fitted there.
  assert.equal(carryOver(pos.rows.get("zone2"), "items"), "i2");
  assert.equal(carryOver(pos.rows.get("zone10"), "items"), null);
  assert.equal(carryOver(pos.rows.get("zone2"), "locations"), "zone2");
  // An item: itself, or in Positions and Flat the position it's fitted to.
  assert.equal(carryOver(items.rows.get("i2"), "positions"), "zone2");
  assert.equal(carryOver(items.rows.get("i2"), "flat"), "zone2");
  assert.equal(carryOver(items.rows.get("sp"), "locations"), "sp");
  assert.equal(carryOver(items.rows.get("bench"), "positions"), "bench"); // its row among the items fitted nowhere
  assert.equal(carryOver(items.rows.get("sp"), "flat"), null);
  // A location only in Locations; a heading never.
  assert.equal(carryOver(loc.rows.get("site"), "locations"), "site");
  assert.equal(carryOver(loc.rows.get("site"), "items"), null);
  assert.equal(carryOver(items.rows.get("G:fitted"), "positions"), null);
  assert.equal(carryOver(null, "items"), null);
});

test("flat: every position, A to Z, nothing inside anything", () => {
  const d = buildDisplay(DATA, "flat");
  assert.equal(d.roots.length, DATA.positions.length);
  assert.equal(d.rows.get(d.roots[0]).ref.name, "Alternator");
  assert.ok([...d.rows.values()].every((r) => r.kids.length === 0));
});

test("levels open the tree to a depth; flatten draws what's open", () => {
  const d = buildDisplay(DATA, "positions");
  assert.deepEqual([...levelSet(d, 1)], []);
  assert.deepEqual(flatten(d, levelSet(d, 1)).list.map((v) => v.key), ["house", "truck", "G:loose"]);
  const two = flatten(d, levelSet(d, 2)).list;
  assert.deepEqual(two.map((v) => v.key), ["house", "pool", "zone2", "zone10", "truck", "turbo", "G:loose", "bench"]);
  assert.deepEqual(two[1], { key: "pool", depth: 1, pos: 1, size: 3 });
  assert.equal(flatten(d, levelSet(d, Infinity)).list.length, d.rows.size);
});

test("the filter keeps the path to each match, and shows what's inside a match", () => {
  const d = buildDisplay(DATA, "positions");
  const f = computeFilter(d, { query: "seal" });
  assert.deepEqual([...f.match], ["seal"]);
  assert.deepEqual([...f.keep].sort(), ["house", "pool", "seal"]);
  assert.deepEqual(flatten(d, filterOpen(f), f).list.map((v) => v.key), ["house", "pool", "seal"]);
  const onPool = computeFilter(d, { query: "pool" });
  assert.deepEqual(flatten(d, new Set(["house", "pool"]), onPool).list.map((v) => v.key), ["house", "pool", "seal"]);
  assert.deepEqual([...computeFilter(d, { chips: ["overdue"] }).match].sort(), ["seal", "zone2"]);
  assert.deepEqual([...computeFilter(d, { chips: ["empty"] }).match], ["zone10"]);
  assert.equal(computeFilter(d, { query: "  " }), null);
  // An item's serial and name count; nothing matches: nothing drawn.
  assert.deepEqual([...computeFilter(d, { query: "valve" }).match], ["zone2"]);
  const none = computeFilter(d, { query: "zzz" });
  assert.equal(flatten(d, new Set(), none).list.length, 0);
});

test("pinned ancestors, the drawn window, type-ahead and the path up", () => {
  const d = buildDisplay(DATA, "positions");
  const { list, index } = flatten(d, levelSet(d, Infinity));
  // Scrolled a row down: the seal shows under the house and the pool pump, pinned.
  assert.deepEqual(pinnedRows(d, list, index, 0, 30), []);
  assert.deepEqual(pinnedRows(d, list, index, 31, 30, 4), ["house", "pool"]);
  assert.deepEqual(pinnedRows(d, list, index, 31, 30, 1), ["house"]);
  // Further down, past the pool pump's branch: only the house.
  assert.deepEqual(pinnedRows(d, list, index, 61, 30, 4), ["house"]);
  assert.deepEqual(windowOf(8000, 30 * 1000, 600, 30), [992, 1028]);
  assert.equal(findByPrefix(d, list, 0, "z"), "zone2");
  assert.equal(findByPrefix(d, list, index.get("zone2"), "z"), "zone10");
  assert.equal(findByPrefix(d, list, 0, "q"), null);
  assert.deepEqual(ancestorsOf(d, "seal"), ["house", "pool"]);
});

test("8,000 positions build, open and draw quickly", () => {
  const positions = [];
  for (let a = 0; a < 20; a++) {
    positions.push({ id: `a${a}`, name: `Area ${a}`, parent_id: null });
    for (let b = 0; b < 20; b++) {
      positions.push({ id: `a${a}b${b}`, name: `System ${b}`, parent_id: `a${a}` });
      for (let c = 0; c < 19; c++) {
        positions.push({ id: `a${a}b${b}c${c}`, name: `Unit ${c}`, parent_id: `a${a}b${b}`, status: { overdue: c % 7 === 0 ? 1 : 0 } });
      }
    }
  }
  const t0 = performance.now();
  const d = buildDisplay({ positions }, "positions");
  const all = levelSet(d, Infinity);
  const { list } = flatten(d, all);
  const took = performance.now() - t0;
  assert.equal(list.length, 8020);
  assert.equal(d.rows.get("a0").sum.overdue, 20 * 3);
  assert.ok(took < 500, `${took} ms`);
});

test("remembered per workspace, and still works when storage throws", () => {
  const box = new Map();
  const storage = { getItem: (k) => box.get(k) ?? null, setItem: (k, v) => box.set(k, v) };
  saveTreeState("ws1", { mode: "items", open: { positions: new Set(["a", "b"]) }, selected: { positions: "b" }, width: 400, collapsed: true }, storage);
  const back = loadTreeState("ws1", storage);
  assert.equal(back.mode, "items");
  assert.equal(loadTreeState("ws2", storage).mode, null);
  assert.deepEqual([...back.open.positions], ["a", "b"]);
  assert.deepEqual(back.selected, { positions: "b" });
  assert.equal(back.width, 400);
  assert.equal(back.collapsed, true);
  assert.equal(loadTreeState("ws2", storage).width, 320);
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadTreeState("ws1", broken).collapsed, false);
  assert.doesNotThrow(() => saveTreeState("ws1", { open: {}, width: 300 }, broken));
  assert.equal(clampWidth(100, 1440), 220);
  assert.equal(clampWidth(2000, 1000), 600);
});

test("Not analysed: the chip finds positions with no RCM yet; the quiet marker counts them inside", () => {
  const data = { ...DATA, positions: DATA.positions.map((p) => (["zone10", "seal"].includes(p.id) ? { ...p, not_analysed: true } : p)) };
  const d = buildDisplay(data, "positions");
  const f = computeFilter(d, { chips: ["unanalysed"] });
  assert.deepEqual([...f.match].sort(), ["seal", "zone10"]);
  assert.ok(f.keep.has("house") && f.keep.has("pool"));
  const house = d.rows.get("house");
  assert.equal(house.sum.not_analysed, 2);
  // Quiet: shown only when asked for (the RCM tab open, or the chip on).
  assert.ok(!markersOf(house).some((m) => m.kind === "rcm"));
  assert.deepEqual(markersOf(house, { rcm: true }).find((m) => m.kind === "rcm"),
    { kind: "rcm", text: "2", label: "2 positions not analysed yet inside", inside: true });
  assert.deepEqual(markersOf(d.rows.get("zone10"), { rcm: true }).map((m) => [m.kind, m.text]), [["rcm", "○"]]);
  // Items have none.
  assert.equal(computeFilter(buildDisplay(data, "items"), { chips: ["unanalysed"] }).match.size, 0);
});
