import { test } from "node:test";
import assert from "node:assert/strict";
import {
  nextGutter,
  ARRANGEMENTS, CHIPS, CHIP_MARK, ancestorsOf, arrangementFor, arrangementOf, buildDisplay, carryOver, clampWidth, computeFilter, explorerPath,
  filterOpen, findByPrefix, flatten, insideWords, levelSet, loadTreeState, markersOf, pinnedRows, saveTreeState,
  scopedArrangeQuery, statusWords, windowOf,
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
  assert.deepEqual(ARRANGEMENTS.map((a) => a.label), ["Positions", "Locations"]);
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
  assert.match(chip.title, /at least one function, every function has a functional failure, every functional failure has failure modes or is caused by failures on positions inside it/);
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

test("the counts come apart at their dots, so they wrap between the parts", async () => {
  const { statusParts } = await import("./assetTree.js");
  assert.deepEqual(statusParts("4 positions · 3 not analysed"), ["4 positions", "3 not analysed"]);
  assert.deepEqual(statusParts("12 positions"), ["12 positions"]);
  assert.deepEqual(statusParts(""), []);
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
