import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, filterOpen, flatten, levelSet } from "./assetTree.js";
import { graftRcm } from "./explorerRcm.js";
import { canPin, crumbAction, inBranch, levelMatches, pinDisplay, pinTarget } from "./treePin.js";

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
  assert.equal(canPin(pos.rows.get("lineA"), "positions"), true);
  assert.equal(canPin(pos.rows.get("sealA"), "positions"), true); // a position with nothing inside still can
  assert.equal(canPin(pos.rows.get("G:loose"), "positions"), false); // the pane's own heading
  assert.equal(canPin(pos.rows.get("bench"), "positions"), true); // an item carrying a position
  assert.equal(canPin(null, "positions"), false);
  const loc = buildDisplay(DATA, "locations");
  assert.equal(canPin(loc.rows.get("site"), "locations"), true);
  assert.equal(canPin(loc.rows.get("sp"), "locations"), false); // a spare with nothing inside
  const flat = buildDisplay(DATA, "flat");
  assert.equal(canPin(flat.rows.get("lineA"), "flat"), false);
  const items = buildDisplay(DATA, "items");
  assert.equal(canPin(items.rows.get("bench"), "items"), false); // items are leaves when arranged by item
  // RCM rows can't be pinned; their position can.
  const rcm = graftRcm(pos, { positions: [{ id: "pumpA", functions: [{ id: "fn1", text: "Pump", failures: [] }] }] });
  assert.equal(canPin(rcm.rows.get("fn1"), "positions"), false);
  assert.equal(canPin(rcm.rows.get("pumpA"), "positions"), true);
});

test("an address's pin: kept when it's a row that can be pinned here, else null", () => {
  const pos = buildDisplay(DATA, "positions");
  assert.equal(pinTarget(pos, "positions", "lineB"), "lineB");
  assert.equal(pinTarget(pos, "positions", "gone"), null); // deleted or retired: not in the tree
  assert.equal(pinTarget(pos, "positions", "G:loose"), null);
  assert.equal(pinTarget(pos, "positions", null), null);
  assert.equal(pinTarget(pos, "positions", "site"), null); // a location isn't a row when arranged by positions
  assert.equal(pinTarget(buildDisplay(DATA, "flat"), "flat", "lineB"), null);
});

test("pinned: the branch is the one top row, everything above and beside it gone", () => {
  const whole = buildDisplay(DATA, "positions");
  const d = pinDisplay(whole, "lineA");
  assert.deepEqual(d.roots, ["lineA"]);
  assert.deepEqual([...d.rows.keys()].sort(), ["lineA", "pumpA", "sealA"]);
  assert.equal(d.rows.get("lineA").parent, null);
  assert.equal(d.rows.get("lineA").depth, 0);
  assert.equal(d.rows.get("sealA").depth, 2);
  assert.equal(d.whole, whole);
  assert.equal(d.pinned, "lineA");
  // The whole display is left as it was.
  assert.equal(whole.rows.get("lineA").depth, 1);
  assert.equal(whole.rows.get("lineA").parent, "plant");
  // Everything open: only the branch is drawn.
  const { list } = flatten(d, levelSet(d, Infinity));
  assert.deepEqual(names(d, list), ["Line A", "Pump A", "Seal A"]);
  assert.deepEqual(list.map((v) => v.depth), [0, 1, 2]);
  assert.equal(list[0].size, 1);
  // Not a row: null.
  assert.equal(pinDisplay(whole, "nope"), null);
});

test("pinned: the levels count from the pinned row", () => {
  const d = pinDisplay(buildDisplay(DATA, "positions"), "plant");
  // Level 1: the pinned row alone, closed; level 2: what's directly inside it.
  assert.deepEqual(names(d, flatten(d, levelSet(d, 1)).list), ["Plant"]);
  assert.deepEqual(names(d, flatten(d, levelSet(d, 2)).list), ["Plant", "Line A", "Line B"]);
  assert.deepEqual(names(d, flatten(d, levelSet(d, 3)).list), ["Plant", "Line A", "Pump A", "Line B", "Pump B"]);
  const deep = pinDisplay(buildDisplay(DATA, "positions"), "lineB");
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
  const d = pinDisplay(whole, "lineB");
  assert.equal(d.positions, 3);
  assert.equal(d.notAnalysed, 1);
  assert.equal(d.rows.get("lineB").sum.overdue, 5); // what's inside the pinned row
  assert.equal(whole.positions, DATA.positions.length);
  // Locations: the places, their positions and their spares.
  const loc = pinDisplay(buildDisplay(DATA, "locations"), "site");
  assert.deepEqual([loc.locations, loc.items], [2, 1]);
  assert.ok(loc.rows.has("lineB") && loc.rows.has("sp"));
  assert.ok(!loc.rows.has("far"));
  // An item that carries positions.
  const it = pinDisplay(whole, "bench");
  assert.deepEqual([it.items, it.positions], [1, 1]);
});

test("pinned: the search and the filters look inside the branch only", () => {
  const d = pinDisplay(buildDisplay(DATA, "positions"), "lineA");
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
  const d = pinDisplay(whole, "lineA");
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
  const d = pinDisplay(whole, "pumpA");
  assert.equal(crumbAction(d, whole, "positions", "pumpA"), "select");
  assert.equal(crumbAction(d, whole, "positions", "lineA"), "pin");
  assert.equal(crumbAction(d, whole, "positions", "plant"), "pin");
  assert.equal(crumbAction(null, whole, "positions", "plant"), "select"); // nothing pinned
  const alt = pinDisplay(whole, "alt");
  assert.equal(crumbAction(alt, whole, "positions", "bench"), "pin");
  assert.equal(crumbAction(alt, whole, "positions", "G:loose"), "unpin"); // the pane's own heading
});
