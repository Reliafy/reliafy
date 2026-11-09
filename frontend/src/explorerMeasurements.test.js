import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay, computeFilter, filterOpen, flatten, rowText } from "./assetTree.js";
import { positionOf } from "./explorerRcm.js";
import {
  MEAS_ADDS, MEAS_CHIPS, graftMeasurements, isMeasRow, measAddActions, measKey, measurementAsk, openForMeasurements, rollupText,
} from "./explorerMeasurements.js";

const TODAY = "2026-11-09";
const DATA = {
  positions: [
    { id: "pool", name: "Pool", parent_id: null },
    { id: "filter", name: "Filter", parent_id: "pool", item: { id: "pump7", name: "Pump 7" } },
    { id: "heater", name: "Solar heater", parent_id: "pool" },
  ],
  locations: [], spares: [], unhomed: [],
};
const pt = (id, name, over = {}) => ({
  id, name, kind: "condition", unit: "kPa", source: "manual", status: "ok", alarm_above: 200, alarm_below: null,
  reading: 120, read_at: "2026-11-08", readings: [], tag: "", position: { id: "filter", name: "Filter" }, ...over,
});
const POINTS = {
  points: [
    pt("gauge", "Filter pressure", { tag: "PT-101" }),
    pt("temp", "Water temperature", { unit: "°C", alarm_above: 30, reading: 33, status: "high", position: { id: "heater", name: "Solar heater" } }),
    pt("setp", "Heater setpoint", { kind: "setting", unit: "°C", alarm_above: null, reading: 28, position: { id: "heater", name: "Solar heater" } }),
    pt("hours", "Run hours", { kind: "counter", unit: "hours", alarm_above: null, position: null, item: { id: "pump7", name: "Pump 7" } }),
  ],
  channels: [{ id: "plug", name: "Pump power", unit: "W", position: { id: "filter", name: "Filter" }, latest: { t: "2026-11-08T10:00:00Z", value: 400 }, recent: [], bands: [] }],
  consumables: [{ key: "pool:part:salt", position: { id: "pool", name: "Pool" }, name: "Pool salt", unit: "kg", listing_id: "l1", part: null,
    uses: [{ id: "u1", on: "2026-11-01", qty: 20, cost: null, note: "", work_order: null }], lsa: [] }],
};

test("the ids to ask for: every position, and the items fitted to them", () => {
  const ask = measurementAsk(buildDisplay(DATA, "positions"));
  assert.deepEqual(ask.positionIds.sort(), ["filter", "heater", "pool"]);
  assert.deepEqual(ask.itemIds, ["pump7"]);
  assert.equal(ask.fittedAt.get("pump7"), "filter");
});

test("each position's measurement rows hang under it, worst first, before the positions inside", () => {
  const base = buildDisplay(DATA, "positions");
  const ask = measurementAsk(base);
  const d = graftMeasurements(base, POINTS, TODAY, ask.fittedAt);
  assert.deepEqual(base.rows.get("pool").kids, ["filter", "heater"]); // the tree it came from is left as it was
  assert.deepEqual(d.rows.get("pool").kids, [measKey("consumable:pool:part:salt"), "filter", "heater"]);
  assert.deepEqual(d.rows.get("heater").kids, [measKey("temp"), measKey("setp")]); // needs attention first
  // A fitted item's counter hangs under the position it's fitted to.
  assert.ok(d.rows.get("filter").kids.includes(measKey("hours")));
  assert.ok(d.rows.get("filter").kids.includes(measKey("channel:plug")));
  const temp = d.rows.get(measKey("temp"));
  assert.equal(isMeasRow(temp), true);
  assert.equal(temp.depth, d.rows.get("heater").depth + 1);
  assert.equal(temp.ref.mkind, "condition");
  assert.equal(d.rows.get(measKey("setp")).ref.mkind, "setting");
  assert.equal(d.rows.get(measKey("channel:plug")).ref.mkind, "channel");
  assert.equal(d.rows.get(measKey("consumable:pool:part:salt")).ref.mkind, "consumable");
  assert.equal(positionOf(temp), "heater");
  assert.match(rowText(d.rows.get(measKey("gauge"))), /pt-101/);
});

test("a position rolls up its own rows open, and everything inside it closed", () => {
  const base = buildDisplay(DATA, "positions");
  const ask = measurementAsk(base);
  const d = graftMeasurements(base, POINTS, TODAY, ask.fittedAt);
  assert.deepEqual(d.rows.get("heater").msum, { n: 2, attention: 1 });
  assert.equal(rollupText(d.rows.get("heater"), true), "2 points · 1 needs attention");
  assert.equal(rollupText(d.rows.get("pool"), true), "1 point");
  assert.equal(rollupText(d.rows.get("pool"), false), "6 points · 1 needs attention");
  assert.equal(rollupText({ msum: { n: 0, attention: 0 }, mall: { n: 0, attention: 0 } }), "");
});

test("the Needs attention chip and a search open the way down to the matches", () => {
  const base = buildDisplay(DATA, "positions");
  const ask = measurementAsk(base);
  const d = graftMeasurements(base, POINTS, TODAY, ask.fittedAt);
  assert.equal(MEAS_CHIPS[0].tab, "measurements");
  const f = computeFilter(d, { chips: ["attention"] });
  assert.deepEqual([...f.match], [measKey("temp")]);
  const { list } = flatten(d, filterOpen(f), f, null);
  assert.deepEqual(list.map((v) => v.key), ["pool", "heater", measKey("temp")]);
  const s = computeFilter(d, { query: "pt-101" });
  assert.deepEqual([...s.match], [measKey("gauge")]);
  assert.deepEqual(openForMeasurements(d, "heater"), ["heater", "pool"]);
});

test("a position's adds on this tab: a measuring point, a setting, a consumable, a sensor channel", () => {
  const pos = { key: "pool", type: "pos", ref: { name: "Pool" } };
  assert.deepEqual(measAddActions(pos).map((a) => a.label),
    ["Add a measuring point…", "Add a setting…", "Add a consumable…", "Add a sensor channel…"]);
  assert.deepEqual(measAddActions(pos).map((a) => a.id), MEAS_ADDS.map((a) => a.id));
  // View only: greyed with the reason.
  assert.deepEqual(measAddActions(pos, { viewOnly: "View only." })[0], { ...MEAS_ADDS[0], disabled: true, reason: "View only." });
  // Only a position: a measurement row keeps its own menu.
  assert.deepEqual(measAddActions({ key: "M:x", type: "meas", ref: {} }), []);
  assert.deepEqual(measAddActions(null), []);
});
