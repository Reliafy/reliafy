import { test } from "node:test";
import assert from "node:assert/strict";
import {
  assetOf, nextGutter,
  ARRANGEMENTS, CHIPS, CHIP_MARK, chipsFor, ancestorsOf, arrangementFor, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, findByPrefix, flatten, insideWords, levelSet, loadTreeState, markersOf, TREE_ROW_MARKERS, pinnedRows, saveTreeState,
  classKey, scopedArrangeQuery, scopedArrangements, statusWords, structuralRow, windowOf,
} from "./assetTree.js";
import { scopeHasClasses, scopeTree } from "./products.js";
import { addressTab } from "./explorerTabs.js";

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
  assert.deepEqual({ ...house.sum }, { overdue: 3, open_work: 1, alarms: 1, open_reports: 0, next_due: "2026-01-01", positions: 4, empty: 1, not_analysed: 0 });
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

test("open failure reports roll up like open work: a marker with the count, the status in words, the chip", () => {
  const data = {
    ...DATA,
    positions: DATA.positions.map((p) => (p.id === "seal" ? { ...p, status: { ...p.status, open_reports: 2 } }
      : p.id === "pool" ? { ...p, status: { ...p.status, open_reports: 1 } } : p)),
  };
  const d = buildDisplay(data, "positions");
  const house = d.rows.get("house");
  assert.equal(house.sum.open_reports, 3);
  assert.equal(house.own.open_reports, 0);
  assert.deepEqual(markersOf(house).find((m) => m.kind === "report"), { kind: "report", text: "3", label: "3 open failure reports inside", inside: true });
  assert.deepEqual(markersOf(d.rows.get("seal")).map((m) => [m.kind, m.text, m.label]),
    [["overdue", "1", "1 overdue task"], ["report", "2", "2 open failure reports"]]);
  assert.deepEqual(statusWords(d.rows.get("pool")).map((w) => [w.kind, w.text]), [
    ["open", "1 open work order"], ["alarm", "1 reading past an alarm limit"], ["report", "1 open failure report"],
    ["overdue", "1 overdue inside"], ["report", "2 open failure reports inside"],
  ]);
  const chip = CHIPS.find((c) => c.id === "reports");
  assert.equal(chip.label, "Open reports");
  assert.ok(chip.test(d.rows.get("pool")) && !chip.test(house));
  // Nothing to mark: no marker (the "at most three" that show are the ones present).
  assert.ok(!markersOf(d.rows.get("zone10")).some((m) => m.kind === "report"));
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

test("the arrangement from the address, else the last one used; the Explorer's addresses", () => {
  assert.deepEqual(ARRANGEMENTS.map((a) => a.label), ["Positions", "Locations", "Classes"]);
  assert.equal(arrangementOf("classes", "positions"), "classes");
  assert.equal(arrangementOf(null, "classes"), "classes");
  assert.equal(explorerPath("classes"), "/asset-register/explorer?arrange=classes");
  // By-position tabs keep the positions tree; one tree on show has Classes only where it's an asset's.
  assert.equal(arrangementFor({ param: "classes", rcm: true }), "positions");
  assert.equal(arrangementFor({ param: "classes", scoped: true }), "positions");
  assert.equal(arrangementFor({ param: "classes", scoped: true, classes: true }), "classes");
  assert.equal(arrangementFor({ param: "classes", scoped: true, classes: true, rcm: true }), "positions");
  assert.equal(arrangementFor({ param: null, remembered: "classes" }), "classes");
  assert.equal(arrangementOf("locations", "positions"), "locations");
  assert.equal(arrangementOf(null, "locations"), "locations");
  assert.equal(arrangementOf("nonsense", null), "positions");
  // Items and Flat are gone: an old address (or a saved state) asking for one opens by positions.
  assert.equal(arrangementOf("items", "locations"), "positions");
  assert.equal(arrangementOf("flat", null), "positions");
  assert.equal(arrangementOf(null, "items"), "positions");
  assert.equal(arrangementOf(null, "flat"), "positions");
  assert.equal(explorerPath(), "/asset-register/explorer?arrange=positions");
  assert.equal(explorerPath("locations", { sel: "l 1", place: "" }), "/asset-register/explorer?arrange=locations&sel=l+1");
});

test("switching arrangements keeps the same thing picked where it can", () => {
  const pos = buildDisplay(DATA, "positions");
  const loc = buildDisplay(DATA, "locations");
  // A position: itself.
  assert.equal(carryOver(pos.rows.get("zone2"), "locations"), "zone2");
  assert.equal(carryOver(loc.rows.get("pool"), "positions"), "pool");
  // An item: itself (in Positions, the position it's fitted to, if any).
  assert.equal(carryOver(loc.rows.get("sp"), "locations"), "sp");
  assert.equal(carryOver(loc.rows.get("bench"), "positions"), "bench"); // its row among the items fitted nowhere
  assert.equal(carryOver({ type: "item", key: "i2", ref: { fitted_to: { id: "zone2" } } }, "positions"), "zone2");
  // A location: itself in Locations; in Positions the position above
  // everything at that place and the places inside it (so its RCM tab opens
  // there); a heading never.
  assert.equal(carryOver(loc.rows.get("site"), "locations"), "site");
  assert.equal(carryOver(loc.rows.get("site"), "positions"), null);
  const ctx = { display: loc, positions: DATA.positions };
  assert.equal(carryOver(loc.rows.get("site"), "positions", ctx), "house"); // the shed inside it holds the pool pump
  assert.equal(carryOver(loc.rows.get("shed"), "positions", ctx), "pool");
  assert.equal(carryOver(loc.rows.get("store"), "positions", ctx), null);
  // Two trees at one place: the root with the most positions there.
  const two = { positions: [
    { id: "a", name: "Plant", parent_id: null, location_id: "site" }, { id: "a1", name: "Line", parent_id: "a" },
    { id: "b", name: "Annex (sample)", parent_id: null, location_id: "site" },
  ], locations: [{ id: "site", name: "Site", parent_id: null }] };
  const twoLoc = buildDisplay(two, "locations");
  assert.equal(carryOver(twoLoc.rows.get("site"), "positions", { display: twoLoc, positions: two.positions }), "a");
  assert.equal(carryOver(loc.rows.get("G:nohome"), "positions"), null);
  assert.equal(carryOver(null, "locations"), null);
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
  saveTreeState("ws1", { mode: "locations", open: { positions: new Set(["a", "b"]) }, selected: { positions: "b" }, width: 400, collapsed: true }, storage);
  const back = loadTreeState("ws1", storage);
  assert.equal(back.mode, "locations");
  // A saved arrangement the Explorer no longer has (Items, Flat): none remembered.
  saveTreeState("ws3", { mode: "flat", open: {}, width: 300 }, storage);
  assert.equal(loadTreeState("ws3", storage).mode, null);
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
  // Locations have none of their own.
  assert.ok(!computeFilter(buildDisplay(data, "locations"), { chips: ["unanalysed"] }).match.has("site"));
  // The chip's tooltip says what analysed means (the server's rule), in words.
  const chip = CHIPS.find((c) => c.id === "unanalysed");
  assert.match(chip.title, /at least one function, every function has a functional failure, every functional failure has failure modes or is caused by other failures on its tree/);
  assert.match(chip.title, /no functions of its own is not analysed/);
});

test("the markers' key: every marker a position can carry has its Show only filter, with the same look", () => {
  const data = { ...DATA, positions: DATA.positions.map((p) => (p.id === "seal" ? { ...p, not_analysed: true } : p)) };
  const d = buildDisplay(data, "positions");
  const kinds = new Set();
  for (const r of d.rows.values()) for (const m of markersOf(r, { rcm: true })) kinds.add(m.kind);
  assert.ok(kinds.size >= 3);
  const keyed = new Set(Object.values(CHIP_MARK).map((m) => m.kind));
  for (const k of kinds) assert.ok(keyed.has(k), `no key for the ${k} marker`);
  for (const id of Object.keys(CHIP_MARK)) assert.ok(CHIPS.some((c) => c.id === id), `${id} is a Show only filter`);
});

test("the scrollbar's gutter only grows, so a measure that flips can't loop", () => {
  assert.equal(nextGutter(0, 15), 15);
  assert.equal(nextGutter(15, 0), 15); // the bar went (a short list): the room stays
  assert.equal(nextGutter(15, 14), 15);
  assert.equal(nextGutter(0, NaN), 0);
  // Measures that alternate with whatever width was set settle at once.
  let kept = 0;
  const renders = [];
  for (const m of [15, 0, 15, 0, 16, 15, 0]) {
    const next = nextGutter(kept, m);
    renders.push(next !== kept);
    kept = next;
  }
  assert.deepEqual(renders, [true, false, false, false, true, false, false]);
});

test("a product's page by Locations: its layout's rows, positions placed there, the rest not placed yet", () => {
  const data = {
    positions: [
      { id: "d", name: "Quad", parent_id: null, design: { rev: "C" } },
      { id: "prop", name: "Propulsion", parent_id: "d", in_design: true },
      { id: "m1", name: "Motor 1", parent_id: "prop", location_id: "arm", in_design: true },
      { id: "m2", name: "Motor 2", parent_id: "prop", location_id: "elsewhere", in_design: true },
      { id: "bat", name: "Battery", parent_id: "d", location_id: "bay", in_design: true },
    ],
    locations: [
      { id: "arm", name: "Forward left arm", parent_id: null, design_of: "d", in_design: true },
      { id: "body", name: "Centre body", parent_id: null, design_of: "d", in_design: true },
      { id: "bay", name: "Battery bay", parent_id: "body", design_of: "d", in_design: true },
    ],
    spares: [{ id: "sp", name: "Spare", location_id: "site" }],
    unhomed: [{ id: "junk", name: "Old pump" }],
    scope: { kind: "design", id: "d", name: "Quad" },
  };
  const d = buildDisplay(data, "locations");
  assert.deepEqual(names(d, d.roots), ["Centre body", "Forward left arm", "Not placed in the layout"]);
  assert.deepEqual(names(d, d.rows.get("arm").kids), ["Motor 1"]);
  assert.deepEqual(names(d, d.rows.get("body").kids), ["Battery bay"]);
  assert.deepEqual(names(d, d.rows.get("bay").kids), ["Battery"]);
  // The product itself and what isn't placed at one of its locations (Motor 2's place isn't on show):
  // no workspace items here.
  assert.deepEqual(names(d, d.rows.get("G:nohome").kids), ["Quad"]);
  assert.deepEqual(names(d, d.rows.get("prop").kids), ["Motor 2"]);
  assert.ok(!d.rows.has("junk") && !d.rows.has("sp"));
  assert.equal([...d.rows.values()].filter((r) => r.type === "pos").length, data.positions.length);
  // An item built from it: the same, named for the item.
  const unit = buildDisplay({ ...data, scope: { kind: "unit", id: "d", name: "Quad · 0007" } }, "locations");
  assert.equal(unit.rows.get("G:nohome").ref.name, "Not placed on the item");
  // By positions nothing changes.
  assert.deepEqual(names(buildDisplay(data, "positions"), buildDisplay(data, "positions").roots), ["Quad"]);
});

test("one tree on show (a product's page, an item's tree) has the Positions / Locations switch: by positions unless its address says Locations", () => {
  assert.equal(arrangementFor({ scoped: true }), "positions");
  assert.equal(arrangementFor({ scoped: true, param: "locations" }), "locations");
  // Never what's remembered for the whole register.
  assert.equal(arrangementFor({ scoped: true, remembered: "locations" }), "positions");
  assert.equal(arrangementFor({ scoped: true, param: "locations", rcm: true }), "positions");
  assert.equal(arrangementFor({ remembered: "locations" }), "locations");
  assert.equal(arrangementFor({ param: "positions", remembered: "locations" }), "positions");
  // A product's page says only Locations; an item's tree (?root=) always says which; a pin goes.
  const page = new URLSearchParams("view=rcm&pin=x");
  assert.equal(scopedArrangeQuery(page, "locations", { ownPage: true }).toString(), "view=rcm&arrange=locations");
  assert.equal(scopedArrangeQuery(new URLSearchParams("arrange=locations"), "positions", { ownPage: true }).toString(), "");
  assert.equal(scopedArrangeQuery(new URLSearchParams("root=b&arrange=positions"), "locations").toString(), "root=b&arrange=locations");
});

test("row markers are switched off (TREE_ROW_MARKERS) but markersOf and the filter data still work", () => {
  // Derryn, 8 Nov 2026: hidden for now. Turning them back on is one line in assetTree.js.
  assert.equal(TREE_ROW_MARKERS, false);
  const d = buildDisplay(DATA, "positions");
  assert.ok(markersOf(d.rows.get("house")).length > 0);
});

test("a product's design offers no chips about operated things; the RCM's own stay", () => {
  const ids = (o) => chipsFor(o).map((c) => c.id);
  assert.deepEqual(ids(), ["overdue", "open", "alarm", "reports", "empty", "unanalysed"]);
  assert.deepEqual(ids({ design: true }), ["unanalysed"]);
  const rcm = ids({ tab: "rcm", design: true });
  assert.ok(rcm.includes("unanalysed") && rcm.includes("undecided") && rcm.includes("hidden"));
  assert.ok(!rcm.some((id) => ["overdue", "open", "alarm", "reports", "empty"].includes(id)));
  assert.ok(ids({ tab: "rcm" }).includes("overdue"));
  assert.ok(ids({ tab: "fmea", design: true }).includes("ap-high"));
});

// The item-class taxonomy as GET /api/maintenance/item-classes gives it, and
// positions whose fitted items are of some of its classes.
const TAXONOMY = [
  { id: "rot", name: "Rotating equipment", children: [
    { id: "pump", name: "Pump", children: [
      { id: "cf", name: "Centrifugal pump", children: [] },
      { id: "pd", name: "Positive displacement pump", children: [] },
    ] },
    { id: "fan", name: "Fan", children: [] },
  ] },
  { id: "elec", name: "Electrical", children: [{ id: "motor", name: "Motor", children: [] }] },
];
const CLASSED = {
  classes: TAXONOMY,
  positions: [
    { id: "station", name: "Riverside pumping station", parent_id: null },
    { id: "p10", name: "Pump 10", parent_id: "station", item: { id: "i10", name: "Unit 10" }, item_class_id: "cf", status: { overdue: 1 } },
    { id: "p2", name: "Pump 2", parent_id: "station", item: { id: "i2", name: "Unit 2" }, item_class_id: "cf" },
    { id: "boost", name: "Booster", parent_id: "station", item: { id: "i3", name: "Unit 3" }, item_class_id: "pump" },
    { id: "m1", name: "Drive motor", parent_id: "p2", item: { id: "i4", name: "Motor 4" }, item_class_id: "motor" },
    { id: "odd", name: "Old slot", parent_id: "station", item: { id: "i5", name: "Unit 5" }, item_class_id: "gone" },
    { id: "empty", name: "Spare bay", parent_id: "station", position_class: "Feed pump" },
  ],
};

test("Classes: the item-class taxonomy, each class opening to its sub-classes and then its positions", () => {
  const d = buildDisplay(CLASSED, "classes");
  // Classes with nothing under them anywhere (Fan, Positive displacement pump) aren't shown; No class is last.
  assert.deepEqual(d.roots, ["cls:rot", "cls:elec", "G:noclass"]);
  assert.deepEqual(names(d, d.roots), ["Rotating equipment", "Electrical", "No class"]);
  assert.deepEqual(d.rows.get("cls:rot").kids, ["cls:pump"]);
  // Sub-classes first, then the class's own positions, A–Z ("Pump 2" before "Pump 10").
  assert.deepEqual(d.rows.get("cls:pump").kids, ["cls:cf", "boost"]);
  assert.deepEqual(d.rows.get("cls:cf").kids, ["p2", "p10"]);
  assert.equal(d.rows.has("cls:fan"), false);
  assert.equal(d.rows.has("cls:pd"), false);
  // A class row counts the positions under it, sub-classes included, and rolls their status up.
  assert.equal(d.rows.get("cls:rot").sum.positions, 3);
  assert.equal(d.rows.get("cls:pump").sum.positions, 3);
  assert.equal(d.rows.get("cls:cf").sum.positions, 2);
  assert.equal(d.rows.get("cls:rot").sum.overdue, 1);
  assert.equal(d.rows.get("cls:cf").type, "cls");
  assert.equal(d.rows.get("cls:cf").ref.name, "Centrifugal pump");
  // Nothing fitted, an item with no class, or a class the taxonomy no longer has: the one last group.
  assert.deepEqual(names(d, d.rows.get("G:noclass").kids), ["Old slot", "Riverside pumping station", "Spare bay"]);
  // Every position appears exactly once, flat under its class (a position inside another has its own class).
  const seen = [...d.rows.values()].filter((r) => r.type === "pos").map((r) => r.key).sort();
  assert.deepEqual(seen, CLASSED.positions.map((p) => p.id).sort());
  assert.equal(d.rows.get("m1").parent, "cls:motor");
  assert.equal(d.positions, 7);
  // Searching keeps the path to each match.
  const f = computeFilter(d, { query: "pump 2" });
  assert.ok(f.match.has("p2") && f.keep.has("cls:cf") && f.keep.has("cls:rot"));
});

test("Classes: a position's Summary counts what's inside it, as in Positions", () => {
  const classes = buildDisplay(CLASSED, "classes");
  const structure = buildDisplay(CLASSED, "positions");
  const listed = classes.rows.get("station");
  // Listed flat under No class, the station has no rows under it in this tree...
  assert.equal(listed.kids.length, 0);
  // ...but its Summary reads its row in the Positions tree: 6 positions inside, 1 overdue inside.
  const { row, display } = structuralRow(structure, listed, classes);
  assert.equal(display, structure);
  assert.equal(row.kids.length, 5);
  assert.equal(insideWords(row), "6 positions · 1 empty");
  assert.deepEqual(statusWords(row).map((w) => w.text), ["1 overdue inside"]);
  // A class's row, or no structure (another arrangement): as it is.
  const cls = classes.rows.get("cls:cf");
  assert.equal(structuralRow(structure, cls, classes).row, cls);
  assert.equal(structuralRow(null, listed, classes).row, listed);
});

test("Classes with no taxonomy loaded or nothing classed: everything is in No class", () => {
  const d = buildDisplay({ positions: CLASSED.positions }, "classes");
  assert.deepEqual(d.roots, ["G:noclass"]);
  assert.equal(d.rows.get("G:noclass").kids.length, 7);
  assert.deepEqual(buildDisplay({ positions: [], classes: TAXONOMY }, "classes").roots, []);
});

test("one asset's tree by Classes: only the classes, counts and No class of the positions inside it", () => {
  // Two stations with pumps of one class; a product's design beside them.
  const data = {
    classes: TAXONOMY,
    positions: [
      { id: "a", name: "Station A", parent_id: null },
      { id: "a1", name: "A pump 1", parent_id: "a", item: { id: "ia1" }, item_class_id: "cf" },
      { id: "a2", name: "A pump 2", parent_id: "a", item: { id: "ia2" }, item_class_id: "cf" },
      { id: "am", name: "A motor", parent_id: "a1", item: { id: "iam" }, item_class_id: "motor" },
      { id: "b", name: "Station B", parent_id: null },
      { id: "b1", name: "B pump 1", parent_id: "b", item: { id: "ib1" }, item_class_id: "cf" },
      { id: "bf", name: "B fan", parent_id: "b", item: { id: "ibf" }, item_class_id: "fan" },
      { id: "bs", name: "B spare bay", parent_id: "b" },
      { id: "d", name: "Drone", parent_id: null, design: { rev: "A" } },
      { id: "d1", name: "Motor mount", parent_id: "d" },
    ],
  };
  // The whole register: every station's pumps under the class.
  const all = buildDisplay(scopeTree(data), "classes");
  assert.equal(all.rows.get("cls:cf").sum.positions, 3);
  assert.deepEqual(all.rows.get("cls:cf").kids, ["a1", "a2", "b1"]);
  // Station B alone: its one pump, its fan, and its own unclassed positions; nothing of Station A.
  const scoped = scopeTree(data, "b");
  const b = buildDisplay(scoped, "classes");
  assert.deepEqual(b.rows.get("cls:cf").kids, ["b1"]);
  assert.equal(b.rows.get("cls:cf").sum.positions, 1);
  assert.equal(b.rows.get("cls:rot").sum.positions, 2);
  assert.equal(b.rows.has("cls:motor"), false); // Station A's motor class has nothing here
  assert.deepEqual(names(b, b.rows.get("G:noclass").kids), ["B spare bay", "Station B"]);
  assert.equal(b.positions, 4);
  assert.ok(![...b.rows.keys()].some((k) => k.startsWith("a")));
  // Station A: two pumps and the motor.
  const a = buildDisplay(scopeTree(data, "a"), "classes");
  assert.equal(a.rows.get("cls:cf").sum.positions, 2);
  assert.ok(a.rows.has("cls:motor"));
  assert.equal(a.rows.has("cls:fan"), false);
  // An asset's tree offers Classes; a product's design doesn't (nothing is fitted there), on its
  // page or opened as a tree; before the tree is read, the address is taken at its word.
  assert.ok(scopeHasClasses(scoped));
  assert.ok(scopeHasClasses(null));
  assert.ok(!scopeHasClasses(scopeTree(data, "d")));
  assert.ok(!scopeHasClasses(scoped, { ownPage: true }));
  assert.ok(!scopeHasClasses(null, { ownPage: true }));
  assert.ok(!scopeHasClasses(scopeTree(data, "gone"))); // a tree that isn't there
  assert.deepEqual(scopedArrangements(true).map((x) => x.value), ["positions", "locations", "classes"]);
  assert.deepEqual(scopedArrangements(false).map((x) => x.value), ["positions", "locations"]);
  // Its address keeps the tree and the arrangement (a reload opens the same).
  assert.equal(scopedArrangeQuery(new URLSearchParams("root=b&arrange=positions"), "classes").toString(), "root=b&arrange=classes");
});

test("switching to and from Classes keeps a position picked; a class only within Classes", () => {
  const cls = buildDisplay(CLASSED, "classes");
  assert.equal(carryOver(cls.rows.get("p2"), "positions"), "p2");
  assert.equal(carryOver(buildDisplay(CLASSED, "positions").rows.get("p2"), "classes"), "p2");
  assert.equal(carryOver(cls.rows.get("cls:cf"), "classes"), "cls:cf");
  assert.equal(carryOver(cls.rows.get("cls:cf"), "positions"), null);
  assert.equal(carryOver(cls.rows.get("cls:cf"), "locations"), null);
  // An item isn't a row in Classes: the position it's fitted to is; a spare has none.
  assert.equal(carryOver({ type: "item", key: "i2", ref: { fitted_to: { id: "p2" } } }, "classes"), "p2");
  assert.equal(carryOver({ type: "item", key: "sp", ref: {} }, "classes"), null);
  assert.equal(carryOver({ type: "loc", key: "site", ref: {} }, "classes"), null);
});

test("a class's row key is the one the address rule knows a class by", () => {
  assert.equal(addressTab("rcm", { arrange: "classes", sel: classKey("pump") }), "condition");
});

test("one asset's tree by Classes: a position its fitted item carries is inside it; a class only another asset uses isn't shown", () => {
  // The tree read nests a carried position (an engine's turbo) in the position its item is fitted to,
  // the same rule the server's class-fleet read uses for ?within=.
  const data = {
    classes: TAXONOMY,
    positions: [
      { id: "a", name: "Station A", parent_id: null },
      { id: "a1", name: "A pump 1", parent_id: "a", item: { id: "ia1" }, item_class_id: "cf" },
      { id: "at", name: "A pump 1 motor", parent_id: "a1", carried_by: { id: "ia1", name: "A unit" }, item: { id: "iam" }, item_class_id: "motor" },
      { id: "b", name: "Station B", parent_id: null },
      { id: "b1", name: "B pump 1", parent_id: "b", item: { id: "ib1" }, item_class_id: "cf" },
      { id: "bf", name: "B fan", parent_id: "b", item: { id: "ibf" }, item_class_id: "fan" },
    ],
  };
  const a = buildDisplay(scopeTree(data, "a"), "classes");
  assert.deepEqual(a.roots, ["cls:rot", "cls:elec", "G:noclass"]);
  assert.deepEqual(a.rows.get("cls:motor").kids, ["at"]);
  assert.deepEqual(a.rows.get("cls:cf").kids, ["a1"]);
  assert.equal(a.rows.get("cls:rot").sum.positions, 1);
  assert.equal(a.rows.has("cls:fan"), false);
  assert.ok(![...a.rows.keys()].some((k) => k.startsWith("b")));
  // Unscoped: every asset, as before.
  const all = buildDisplay(scopeTree(data), "classes");
  assert.equal(all.rows.get("cls:rot").sum.positions, 3);
  assert.ok(all.rows.has("cls:fan"));
});

test("an asset opened by Classes: the place it's at (an asset on the Assets page) or its top position; never another asset's classes", () => {
  // Two places you look after, each with a plant whose pumps are of different classes; a pump at no place.
  const data = {
    classes: TAXONOMY,
    locations: [
      { id: "river", name: "Riverside pumping station", parent_id: null },
      { id: "hall", name: "Pump hall", parent_id: "river" },
      { id: "pool", name: "Backyard pool", parent_id: null },
      { id: "q-bay", name: "Battery bay", parent_id: null, carried_by: "q" },
    ],
    positions: [
      { id: "rp", name: "Riverside plant", parent_id: null, location_id: "hall", location: { id: "hall" } },
      { id: "r1", name: "River pump 1", parent_id: "rp", item: { id: "i1" }, item_class_id: "cf", location: { id: "hall", inherited: true } },
      { id: "r2", name: "River pump 2", parent_id: null, location_id: "river", location: { id: "river" }, item: { id: "i2" }, item_class_id: "cf" },
      { id: "pp", name: "Pool plant", parent_id: null, location_id: "pool", location: { id: "pool" } },
      { id: "p1", name: "Pool pump", parent_id: "pp", item: { id: "i3" }, item_class_id: "pd", location: { id: "pool", inherited: true } },
      { id: "lone", name: "Bench pump", parent_id: null, item: { id: "i4" }, item_class_id: "fan" },
      { id: "lone1", name: "Bench pump seal", parent_id: "lone" },
    ],
  };
  const whole = scopeTree(data);
  const d = buildDisplay(whole, "locations");
  // The asset of a picked row: its top place, whatever arrangement; else its top position.
  assert.equal(assetOf(whole, d.rows.get("hall")), "river");
  assert.equal(assetOf(whole, { type: "pos", key: "r1", ref: whole.positions[1] }), "river");
  assert.equal(assetOf(whole, { type: "pos", key: "p1" }), "pool");
  assert.equal(assetOf(whole, { type: "pos", key: "lone1" }), "lone");
  assert.equal(assetOf(whole, { type: "item", key: "x", ref: { location_id: "hall" } }), "river");
  assert.equal(assetOf(whole, { type: "item", key: "x", ref: {} }), null);
  assert.equal(assetOf(whole, { type: "cls", key: "cls:cf" }), null);
  assert.equal(assetOf(whole, null), null);
  // Riverside by Classes: its two pumps (one set at the station, one inherited from the hall); nothing of the pool.
  const river = scopeTree(data, "river");
  assert.deepEqual(river.scope, { kind: "place", id: "river", name: "Riverside pumping station" });
  assert.ok(scopeHasClasses(river));
  assert.deepEqual(river.locations.map((l) => l.id), ["river", "hall"]);
  const rc = buildDisplay(river, "classes");
  assert.deepEqual(rc.roots, ["cls:rot", "G:noclass"]);
  assert.deepEqual(rc.rows.get("cls:cf").kids, ["r1", "r2"]);
  assert.equal(rc.rows.get("cls:rot").sum.positions, 2);
  assert.equal(rc.rows.has("cls:pd"), false);
  assert.equal(rc.rows.has("cls:fan"), false);
  assert.deepEqual(names(rc, rc.rows.get("G:noclass").kids), ["Riverside plant"]);
  // The pool by Classes: its one pump.
  const pc = buildDisplay(scopeTree(data, "pool"), "classes");
  assert.deepEqual(pc.rows.get("cls:pd").kids, ["p1"]);
  assert.equal(pc.rows.has("cls:cf"), false);
  // An asset at no place: its top position's tree, as before.
  const lc = buildDisplay(scopeTree(data, "lone"), "classes");
  assert.deepEqual(lc.rows.get("cls:fan").kids, ["lone"]);
  assert.equal(lc.rows.has("cls:cf"), false);
  // A built item's own layout isn't a place you look after: not a root of this kind.
  assert.equal(scopeTree(data, "q-bay").positions.length, 0);
  // By Locations, the place's own layout and what's there.
  const rl = buildDisplay(river, "locations");
  assert.deepEqual(rl.roots, ["river"]);
  assert.ok(rl.rows.has("r1") && !rl.rows.has("p1") && !rl.rows.has("pool"));
});

// An asset is self-contained (14 Nov 2026): a link naming a row opens that row's asset alone.
test("arrivalRoot, arrivalNamed, opensAsset and rcmPositionOf: what opens one asset on its own", async () => {
  const { arrivalRoot, arrivalNamed, assetOfId, opensAsset, rcmPositionOf } = await import("./assetTree.js");
  const data = {
    locations: [
      { id: "anthony", name: "96 Anthony Street", parent_id: null },
      { id: "kitchen", name: "Kitchen", parent_id: "anthony" },
      { id: "farm", name: "Farm", parent_id: null },
    ],
    positions: [
      { id: "hws", name: "Hot water", parent_id: null, location_id: "kitchen", location: { id: "kitchen" } },
      { id: "elem", name: "Element", parent_id: "hws", location: { id: "kitchen", inherited: true } },
      { id: "pump", name: "Bore pump", parent_id: null, location_id: "farm", location: { id: "farm" } },
      { id: "boat", name: "Boat", parent_id: null },
      { id: "motor", name: "Outboard", parent_id: "boat" },
    ],
    spares: [{ id: "spare", name: "Spare element", location_id: "kitchen" }],
  };
  const q = (s) => new URLSearchParams(s);
  // By id: a position (its top place, else its top position), a place, a spare at a place.
  assert.equal(assetOfId(data, "elem"), "anthony");
  assert.equal(assetOfId(data, "kitchen"), "anthony");
  assert.equal(assetOfId(data, "spare"), "anthony");
  assert.equal(assetOfId(data, "motor"), "boat");
  assert.equal(assetOfId(data, "nope"), null);
  // A link naming a row lands on its asset; a fit pane's position does too.
  assert.equal(arrivalRoot(data, q("arrange=positions&sel=elem")), "anthony");
  assert.equal(arrivalRoot(data, q("arrange=locations&sel=farm")), "farm");
  assert.equal(arrivalRoot(data, q("tab=models&fit=motor"), "motor"), "boat");
  // Not: one open already, an old ?all=1 link (the Assets list), the positions at no place, nothing named.
  assert.equal(arrivalRoot(data, q("root=farm&sel=elem")), null);
  assert.equal(arrivalRoot(data, q("all=1&sel=elem")), null);
  assert.equal(arrivalRoot(data, q("place=none&sel=boat")), null);
  assert.equal(arrivalRoot(data, q("arrange=positions")), null);
  assert.equal(arrivalRoot(null, q("sel=elem")), null);
  // An RCM row isn't a tree row: named, for the RCM read to place (a class's row never is).
  assert.equal(arrivalNamed(data, q("tab=rcm&sel=fn1")), "fn1");
  assert.equal(arrivalNamed(data, q("tab=rcm&sel=elem")), null);
  assert.equal(arrivalNamed(data, q("sel=cls:pumps")), null);
  assert.equal(arrivalNamed(data, q("all=1&sel=fn1")), null);
  const rcm = { positions: [
    { id: "pump", functions: [{ id: "fn0", failures: [{ id: "ff0", modes: [{ id: "m0" }] }] }] },
    { id: "elem", functions: [{ id: "fn1", failures: [{ id: "ff1", modes: [{ id: "m1" }] }] }] },
  ] };
  assert.equal(rcmPositionOf(rcm, "fn1"), "elem");
  assert.equal(rcmPositionOf(rcm, "m0"), "pump");
  assert.equal(rcmPositionOf(rcm, "T:m1:task9"), "elem");
  assert.equal(rcmPositionOf(rcm, "zzz"), null);
  assert.equal(rcmPositionOf(null, "fn1"), null);
  // On the whole register, an asset's own top row opens it alone: a top place, a top position at
  // no place; not a top position at a place (its asset is the place), nor a row inside, nor Classes.
  const byLoc = buildDisplay(data, "locations");
  const byPos = buildDisplay(data, "positions");
  assert.equal(opensAsset(data, byLoc.rows.get("anthony"), "locations"), true);
  assert.equal(opensAsset(data, byLoc.rows.get("kitchen"), "locations"), false);
  assert.equal(opensAsset(data, byPos.rows.get("boat"), "positions"), true);
  assert.equal(opensAsset(data, byPos.rows.get("hws"), "positions"), false);
  assert.equal(opensAsset(data, byPos.rows.get("motor"), "positions"), false);
  assert.equal(opensAsset(data, byPos.rows.get("boat"), "classes"), false);
  assert.equal(opensAsset(data, null, "positions"), false);
});

test("one place opened on its own: the tree in every arrangement holds nothing of another asset", () => {
  // As GET /api/maintenance/tree?within=anthony sends it, and as scopeTree keeps it.
  const data = {
    locations: [
      { id: "anthony", name: "96 Anthony Street", parent_id: null },
      { id: "kitchen", name: "Kitchen", parent_id: "anthony" },
      { id: "farm", name: "Farm", parent_id: null },
    ],
    positions: [
      { id: "hws", name: "Hot water", parent_id: null, location_id: "kitchen", location: { id: "kitchen" }, item: { id: "i1" }, item_class_id: "heater" },
      { id: "pump", name: "Bore pump", parent_id: null, location_id: "farm", location: { id: "farm" }, item: { id: "i2" }, item_class_id: "heater" },
    ],
    spares: [{ id: "s1", name: "Farm spare", location_id: "farm" }],
    unhomed: [{ id: "u1", name: "Loose item" }],
    classes: [{ id: "heater", name: "Heaters", children: [] }],
  };
  const one = scopeTree(data, "anthony");
  for (const mode of ["positions", "locations", "classes"]) {
    const d = buildDisplay(one, mode);
    const names = [...d.rows.values()].map((r) => r.ref?.name);
    assert.ok(!names.includes("Bore pump") && !names.includes("Farm") && !names.includes("Farm spare") && !names.includes("Loose item"), `${mode}: ${names}`);
    assert.ok(names.includes("Hot water"), mode);
  }
});
