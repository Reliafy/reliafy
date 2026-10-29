import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, filterOpen, flatten, levelSet } from "./assetTree.js";
import { graftRcm } from "./explorerRcm.js";
import {
  canIsolate, crumbAction, depthWords, inBranch, isolateCoversAll, isolateDisplay, isolateKey, isolateOpen, isolatePath, levelMatches,
  levelOfDepth, parseDepth, parseIsolate, resolveIsolate, writeIsolate,
} from "./treeIsolate.js";

// A plant with two lines, each with a pump and its seal; a second site; an
// engine fitted nowhere that carries an alternator position.
const DATA = {
  positions: [
    { id: "plant", name: "Plant", parent_id: null, location_id: "site" },
    { id: "lineA", name: "Line A", parent_id: "plant" },
    { id: "pumpA", name: "Pump A", parent_id: "lineA", status: { overdue: 2 }, not_analysed: true },
    { id: "sealA", name: "Seal A", parent_id: "pumpA", status: { open_work: 1 } },
    { id: "lineB", name: "Line B", parent_id: "plant", location_id: "shed" },
    { id: "pumpB", name: "Pump B", parent_id: "lineB", status: { overdue: 5 }, not_analysed: true },
    { id: "sealB", name: "Seal B", parent_id: "pumpB" },
    { id: "other", name: "Other plant", parent_id: null },
    { id: "alt", name: "Alternator", parent_id: null, carried_by: { id: "bench", name: "Engine B" } },
  ],
  locations: [
    { id: "site", name: "Site", parent_id: null },
    { id: "shed", name: "Shed", parent_id: "site" },
    { id: "far", name: "Far site", parent_id: null },
  ],
  spares: [{ id: "sp", name: "Spare seal", location_id: "shed" }],
  unhomed: [{ id: "bench", name: "Engine B" }],
};
const names = (d, list) => list.map((v) => d.rows.get(v.key).ref.name);

test("what can be pinned: positions, locations, items with something inside; nothing in Flat", () => {
  const pos = buildDisplay(DATA, "positions");
  assert.equal(canIsolate(pos.rows.get("lineA"), "positions"), true);
  assert.equal(canIsolate(pos.rows.get("sealA"), "positions"), true); // a position with nothing inside still can
  assert.equal(canIsolate(pos.rows.get("G:loose"), "positions"), false); // the pane's own heading
  assert.equal(canIsolate(pos.rows.get("bench"), "positions"), true); // an item carrying a position
  assert.equal(canIsolate(null, "positions"), false);
  const loc = buildDisplay(DATA, "locations");
  assert.equal(canIsolate(loc.rows.get("site"), "locations"), true);
  assert.equal(canIsolate(loc.rows.get("sp"), "locations"), false); // a spare with nothing inside
  const flat = buildDisplay(DATA, "flat");
  assert.equal(canIsolate(flat.rows.get("lineA"), "flat"), false);
  const items = buildDisplay(DATA, "items");
  assert.equal(canIsolate(items.rows.get("bench"), "items"), false); // items are leaves when arranged by item
  // RCM rows can be isolated too (not a reference row); and their position.
  const rcm = graftRcm(pos, { positions: [{ id: "pumpA", functions: [{ id: "fn1", text: "Pump", failures: [{ id: "ff1", text: "No flow", modes: [{ id: "m1", text: "Seal" }] }] }] }] });
  assert.equal(canIsolate(rcm.rows.get("fn1"), "positions"), true);
  assert.equal(canIsolate(rcm.rows.get("ff1"), "positions"), true);
  assert.equal(canIsolate(rcm.rows.get("m1"), "positions"), true);
  assert.equal(canIsolate({ type: "cause", kids: [] }, "positions"), false);
  assert.equal(canIsolate(rcm.rows.get("pumpA"), "positions"), true);
});

test("an address's pin: kept when it's a row that can be pinned here, else null", () => {
  const pos = buildDisplay(DATA, "positions");
  assert.equal(isolateKey(pos, "positions", "lineB"), "lineB");
  assert.equal(isolateKey(pos, "positions", "gone"), null); // deleted or retired: not in the tree
  assert.equal(isolateKey(pos, "positions", "G:loose"), null);
  assert.equal(isolateKey(pos, "positions", null), null);
  assert.equal(isolateKey(pos, "positions", "site"), null); // a location isn't a row when arranged by positions
  assert.equal(isolateKey(buildDisplay(DATA, "flat"), "flat", "lineB"), null);
});

test("pinned: the branch is the one top row, everything above and beside it gone", () => {
  const whole = buildDisplay(DATA, "positions");
  const d = isolateDisplay(whole, "lineA");
  assert.deepEqual(d.roots, ["lineA"]);
  assert.deepEqual([...d.rows.keys()].sort(), ["lineA", "pumpA", "sealA"]);
  assert.equal(d.rows.get("lineA").parent, null);
  assert.equal(d.rows.get("lineA").depth, 0);
  assert.equal(d.rows.get("sealA").depth, 2);
  assert.equal(d.whole, whole);
  assert.equal(d.isolated, "lineA");
  // The whole display is left as it was.
  assert.equal(whole.rows.get("lineA").depth, 1);
  assert.equal(whole.rows.get("lineA").parent, "plant");
  // Everything open: only the branch is drawn.
  const { list } = flatten(d, levelSet(d, Infinity));
  assert.deepEqual(names(d, list), ["Line A", "Pump A", "Seal A"]);
  assert.deepEqual(list.map((v) => v.depth), [0, 1, 2]);
  assert.equal(list[0].size, 1);
  // Not a row: null.
  assert.equal(isolateDisplay(whole, "nope"), null);
});

test("pinned: the levels count from the pinned row", () => {
  const d = isolateDisplay(buildDisplay(DATA, "positions"), "plant");
  // Level 1: the pinned row alone, closed; level 2: what's directly inside it.
  assert.deepEqual(names(d, flatten(d, levelSet(d, 1)).list), ["Plant"]);
  assert.deepEqual(names(d, flatten(d, levelSet(d, 2)).list), ["Plant", "Line A", "Line B"]);
  assert.deepEqual(names(d, flatten(d, levelSet(d, 3)).list), ["Plant", "Line A", "Pump A", "Line B", "Pump B"]);
  const deep = isolateDisplay(buildDisplay(DATA, "positions"), "lineB");
  assert.deepEqual(names(deep, flatten(deep, levelSet(deep, 2)).list), ["Line B", "Pump B"]);
  // Whether what's open is a level, counted from the pinned row.
  assert.equal(levelMatches(deep, levelSet(deep, 2), 2), true);
  assert.equal(levelMatches(deep, new Set(["lineB", "pumpB"]), 2), false);
  assert.equal(levelMatches(deep, new Set(["lineB", "pumpB"]), 3), true);
  // Rows outside the branch that are open don't count.
  assert.equal(levelMatches(deep, new Set(["plant", "lineA", "lineB"]), 2), true);
});

test("pinned: the counts and the roll-ups are the branch's", () => {
  const whole = buildDisplay(DATA, "positions");
  const d = isolateDisplay(whole, "lineB");
  assert.equal(d.positions, 3);
  assert.equal(d.notAnalysed, 1);
  assert.equal(d.rows.get("lineB").sum.overdue, 5); // what's inside the pinned row
  assert.equal(whole.positions, DATA.positions.length);
  // Locations: the places, their positions and their spares.
  const loc = isolateDisplay(buildDisplay(DATA, "locations"), "site");
  assert.deepEqual([loc.locations, loc.items], [2, 1]);
  assert.ok(loc.rows.has("lineB") && loc.rows.has("sp"));
  assert.ok(!loc.rows.has("far"));
  // An item that carries positions.
  const it = isolateDisplay(whole, "bench");
  assert.deepEqual([it.items, it.positions], [1, 1]);
});

test("pinned: the search and the filters look inside the branch only", () => {
  const d = isolateDisplay(buildDisplay(DATA, "positions"), "lineA");
  const f = computeFilter(d, { query: "pump" });
  assert.deepEqual([...f.match], ["pumpA"]); // Pump B is outside the branch
  assert.deepEqual(names(d, flatten(d, filterOpen(f), f).list), ["Line A", "Pump A"]);
  assert.equal(computeFilter(d, { query: "other plant" }).match.size, 0);
  const overdue = computeFilter(d, { chips: ["overdue"] });
  assert.deepEqual([...overdue.match], ["pumpA"]);
  const unanalysed = computeFilter(d, { chips: ["unanalysed"] });
  assert.deepEqual([...unanalysed.match], ["pumpA"]);
});

test("pinned on the RCM tab: the branch keeps its positions' functions, failures and modes", () => {
  const rcm = {
    positions: [
      { id: "pumpA", functions: [{ id: "fnA", text: "Pump water", failures: [{ id: "ffA", text: "No flow", modes: [{ id: "mA", text: "Seal leaks" }] }] }] },
      { id: "pumpB", functions: [{ id: "fnB", text: "Pump oil", failures: [] }] },
    ],
  };
  const whole = graftRcm(buildDisplay(DATA, "positions"), rcm);
  const d = isolateDisplay(whole, "lineA");
  assert.ok(d.rows.has("fnA") && d.rows.has("ffA") && d.rows.has("mA"));
  assert.ok(!d.rows.has("fnB"));
  assert.equal(d.rows.get("fnA").depth, 2);
  assert.equal(d.rows.get("pumpA").rcmKids, 1);
  assert.deepEqual([...computeFilter(d, { query: "pump" }).match].sort(), ["fnA", "pumpA"]);
});

test("inside the branch or not, and what a crumb above it does", () => {
  const whole = buildDisplay(DATA, "positions");
  assert.equal(inBranch(whole, "sealA", "lineA"), true);
  assert.equal(inBranch(whole, "lineA", "lineA"), true);
  assert.equal(inBranch(whole, "sealB", "lineA"), false);
  assert.equal(inBranch(whole, "plant", "lineA"), false);
  assert.equal(inBranch(whole, "unknown", "lineA"), false);
  const d = isolateDisplay(whole, "pumpA");
  assert.equal(crumbAction(d, whole, "positions", "pumpA"), "select");
  assert.equal(crumbAction(d, whole, "positions", "lineA"), "isolate");
  assert.equal(crumbAction(d, whole, "positions", "plant"), "isolate");
  assert.equal(crumbAction(null, whole, "positions", "plant"), "select"); // nothing pinned
  const alt = isolateDisplay(whole, "alt");
  assert.equal(crumbAction(alt, whole, "positions", "bench"), "isolate");
  assert.equal(crumbAction(alt, whole, "positions", "G:loose"), "show-all"); // the pane's own heading
});

test("the pinned row's path, from the top of the whole tree", () => {
  const pos = buildDisplay(DATA, "positions");
  assert.equal(isolatePath(pos, "sealA"), "Plant › Line A › Pump A › Seal A");
  assert.equal(isolatePath(pos, "plant"), "Plant");
  assert.equal(isolatePath(pos, "nope"), "");
  const loc = buildDisplay(DATA, "locations");
  assert.equal(isolatePath(loc, "shed"), "Site › Shed");
});

test("a crumb at the whole tree's one top row un-pins instead of pinning everything", () => {
  // One top row (a pool with everything inside it).
  const one = buildDisplay({
    positions: [
      { id: "pool", name: "Swimming pool", parent_id: null },
      { id: "circ", name: "Circulation", parent_id: "pool" },
      { id: "pump", name: "Filter pump", parent_id: "circ" },
    ],
    locations: [],
  }, "positions");
  assert.deepEqual(one.roots, ["pool"]);
  const pinned = isolateDisplay(one, "pump");
  assert.equal(isolateCoversAll(one, "pool"), true);
  assert.equal(isolateCoversAll(one, "circ"), false);
  assert.equal(crumbAction(pinned, one, "positions", "pool"), "show-all");
  assert.equal(crumbAction(pinned, one, "positions", "circ"), "isolate");
  // Several top rows: pinning one of them still hides the others, so it moves the pin.
  const whole = buildDisplay(DATA, "positions");
  assert.equal(isolateCoversAll(whole, "plant"), false);
  assert.equal(crumbAction(isolateDisplay(whole, "pumpA"), whole, "positions", "plant"), "isolate");
  assert.equal(isolateCoversAll(null, "plant"), false);
});

test("the address: ?isolate= with its depth, old ?pin= links, and writing it back", () => {
  const p = (q) => parseIsolate(new URLSearchParams(q));
  assert.deepEqual(p("isolate=lineA&depth=2"), { id: "lineA", depth: 2, legacy: false });
  assert.deepEqual(p("isolate=lineA&depth=all"), { id: "lineA", depth: "all", legacy: false });
  assert.deepEqual(p("isolate=lineA"), { id: "lineA", depth: null, legacy: false });
  assert.deepEqual(p("isolate=lineA&depth=9"), { id: "lineA", depth: null, legacy: false }); // not a depth offered
  assert.deepEqual(p("pin=lineA"), { id: "lineA", depth: null, legacy: true }); // an old pin link: what's open stays
  assert.deepEqual(p("pin=old&isolate=new&depth=1"), { id: "new", depth: 1, legacy: false });
  assert.deepEqual(p("arrange=positions"), { id: null, depth: null, legacy: false });
  assert.equal(parseDepth("3"), 3);
  assert.equal(parseDepth("0"), null);
  // Round trip.
  for (const depth of [1, 2, 3, "all", null]) {
    const q = writeIsolate(new URLSearchParams("arrange=positions&pin=x"), "pumpA", depth);
    assert.equal(q.get("pin"), null);
    assert.deepEqual(parseIsolate(q), { id: "pumpA", depth, legacy: false });
    assert.equal(q.get("arrange"), "positions");
  }
  const off = writeIsolate(new URLSearchParams("isolate=a&depth=2&pin=b&sel=c"), null);
  assert.equal(off.toString(), "sel=c");
  assert.equal(depthWords(1), "1 level open");
  assert.equal(depthWords(3), "3 levels open");
  assert.equal(depthWords("all"), "everything open");
  assert.equal(depthWords(2, { open: false }), "2 levels");
  assert.deepEqual([1, 2, 3, "all"].map(levelOfDepth), [2, 3, 4, Infinity]);
});

test("isolating N levels deep: the branch opens exactly that far below its row, the rest as it was", () => {
  const whole = buildDisplay(DATA, "positions");
  const shown = (key, depth, open = new Set()) => {
    const next = isolateOpen(whole, open, key, depth);
    const d = isolateDisplay(whole, key);
    return names(d, flatten(d, next).list);
  };
  assert.deepEqual(shown("plant", 1), ["Plant", "Line A", "Line B"]);
  assert.deepEqual(shown("plant", 2), ["Plant", "Line A", "Pump A", "Line B", "Pump B"]);
  assert.deepEqual(shown("plant", 3), ["Plant", "Line A", "Pump A", "Seal A", "Line B", "Pump B", "Seal B"]);
  assert.deepEqual(shown("plant", "all"), shown("plant", 3));
  // Whatever was open before inside the branch: closed beyond the depth.
  assert.deepEqual(shown("plant", 1, new Set(["plant", "lineA", "pumpA"])), ["Plant", "Line A", "Line B"]);
  // Rows outside the branch keep their state (for leaving it).
  const next = isolateOpen(whole, new Set(["other", "lineA", "pumpA"]), "lineB", 1);
  assert.deepEqual([...next].sort(), ["lineA", "lineB", "other", "pumpA"]);
  // The tree's own level: N levels open below the row is level N + 1, counted from it.
  const d = isolateDisplay(whole, "plant");
  assert.equal(levelMatches(d, isolateOpen(whole, new Set(), "plant", 2), levelOfDepth(2)), true);
  // Not a row: what was open, as it was.
  assert.deepEqual([...isolateOpen(whole, new Set(["plant"]), "nope", 2)], ["plant"]);
});

test("isolating on the RCM tab: a function and what's inside it, N levels deep", () => {
  const rcm = {
    positions: [
      { id: "pumpA", functions: [{ id: "fnA", text: "Pump water", failures: [{ id: "ffA", text: "No flow", modes: [{ id: "mA", text: "Seal leaks" }] }] }] },
    ],
  };
  const whole = graftRcm(buildDisplay(DATA, "positions"), rcm);
  const d = isolateDisplay(whole, "fnA");
  assert.deepEqual([...d.rows.keys()].sort(), ["ffA", "fnA", "mA"]);
  assert.equal(d.rows.get("fnA").depth, 0);
  const text = (open) => flatten(d, open).list.map((v) => d.rows.get(v.key).ref.text);
  assert.deepEqual(text(isolateOpen(whole, new Set(), "fnA", 1)), ["Pump water", "No flow"]);
  assert.deepEqual(text(isolateOpen(whole, new Set(), "fnA", 2)), ["Pump water", "No flow", "Seal leaks"]);
  // The position, isolated 1 level deep: its function shows, closed.
  const pd = isolateDisplay(whole, "pumpA");
  assert.deepEqual(flatten(pd, isolateOpen(whole, new Set(), "pumpA", 1)).list.map((v) => v.key), ["pumpA", "fnA", "sealA"]);
});

test("which row an address isolates: itself, its position on the Summary tab, or wait for the RCM", () => {
  const base = buildDisplay(DATA, "positions");
  const rcm = { positions: [{ id: "pumpA", functions: [{ id: "fnA", text: "Pump water", failures: [] }] }] };
  const withRcm = graftRcm(base, rcm);
  assert.deepEqual(resolveIsolate(base, "positions", "lineA"), { key: "lineA", pending: false });
  assert.deepEqual(resolveIsolate(withRcm, "positions", "fnA"), { key: "fnA", pending: false });
  // The Summary tab has no RCM rows: the function's position, the address unchanged.
  assert.deepEqual(resolveIsolate(base, "positions", "fnA", { rcmWhole: withRcm }), { key: "pumpA", pending: false });
  // The RCM not read yet: maybe one of its rows, so not dropped yet.
  assert.deepEqual(resolveIsolate(base, "positions", "fnA", { waiting: true }), { key: null, pending: true });
  assert.deepEqual(resolveIsolate(base, "positions", "gone", { rcmWhole: withRcm }), { key: null, pending: false });
  assert.deepEqual(resolveIsolate(base, "positions", null), { key: null, pending: false });
  // Flat: nothing isolates.
  assert.deepEqual(resolveIsolate(buildDisplay(DATA, "flat"), "flat", "lineA"), { key: null, pending: false });
});
