import test from "node:test";
import assert from "node:assert/strict";
import {
  checkValue, kindLabel, measurementsCsv, parseSort, rowMenu, rowState, savedText, searchRows,
  sortRows, tableRows,
} from "./measurementsTable.js";

const TODAY = "2026-11-09";
const trail = (days) => days.map(([at, value], i) => ({ id: `r${i}`, at, on: at, value, status: "ok" })).reverse();
const pt = (over = {}) => ({
  id: "p", name: "Pressure", kind: "condition", unit: "kPa", source: "manual", status: "ok",
  alarm_above: 200, alarm_below: 50, reading: 120, read_at: "2026-11-08", readings: [], tag: "",
  position: { id: "pos1", name: "Filter" }, ...over,
});

test("kind in a word: Condition, Setting, Counter, Fed", () => {
  assert.equal(kindLabel(pt()), "Condition");
  assert.equal(kindLabel(pt({ kind: "setting" })), "Setting");
  assert.equal(kindLabel(pt({ kind: "counter" })), "Counter");
  assert.equal(kindLabel(pt({ source: "automated" })), "Fed");
  assert.equal(kindLabel({ kind: "channel" }), "Fed");
});

test("state: Needs attention, Due, No reading, OK; a setting says when it was set", () => {
  assert.equal(rowState(pt({ status: "high", reading: 210 }), TODAY).label, "Needs attention");
  assert.equal(rowState(pt({ status: "high", reading: 210 }), TODAY).tone, "danger");
  assert.equal(rowState(pt({ reading: 195 }), TODAY).label, "Needs attention"); // near the 200 limit
  const weekly = trail([["2026-10-01", 120], ["2026-10-08", 121], ["2026-10-15", 119], ["2026-10-22", 120]]);
  assert.equal(rowState(pt({ readings: weekly, read_at: "2026-10-22" }), TODAY).label, "Due");
  assert.equal(rowState(pt({ reading: null, read_at: null }), TODAY).label, "No reading");
  assert.equal(rowState(pt(), TODAY).label, "OK");
  assert.equal(rowState(pt({ kind: "setting", reading: 28, unit: "°C", read_at: "2026-10-01T09:00:00" }), TODAY).label, "Set 1 Oct 2026");
  assert.equal(rowState(pt({ kind: "setting", reading: null, read_at: null }), TODAY).label, "Not set");
  assert.equal(rowState({ kind: "channel", bands: [{ name: "1x", status: "high" }], latest: { value: 1 } }, TODAY).label, "Needs attention");
});

test("rows from points and channels: place, value, sparkline, next due, whether it can be recorded here", () => {
  const weekly = trail([["2026-10-01", 120], ["2026-10-08", 121], ["2026-10-15", 119], ["2026-10-22", 120]]);
  const rows = tableRows([
    pt({ readings: weekly, read_at: "2026-10-22" }),
    pt({ id: "s", name: "Heater setpoint", kind: "setting", unit: "°C", reading: 28, alarm_above: null, alarm_below: null }),
    pt({ id: "f", name: "Flow", source: "automated", tag: "sensor.flow" }),
    pt({ id: "i", name: "Hours", kind: "counter", position: null, item: { id: "it1", name: "Pump 7" }, alarm_above: null, alarm_below: null }),
  ], [{ id: "c1", name: "Plug", unit: "W", tag: "smoke.plug", position: { id: "pos2", name: "Pump" }, latest: { t: "2026-11-08T10:00:00Z", value: 400 }, recent: [{ t: "2026-11-07T10:00:00Z", value: 390 }, { t: "2026-11-08T10:00:00Z", value: 400 }], bands: [] }],
  TODAY, new Map([["it1", "Bay 2"]]));
  const by = Object.fromEntries(rows.map((r) => [r.key, r]));
  assert.equal(by.p.due, "2026-11-02");
  assert.deepEqual(by.p.values.map((v) => v.value), [120, 121, 119, 120]);
  assert.equal(by.s.step, true);
  assert.equal(by.s.due, null);
  assert.equal(by.f.canRecord, false);
  assert.equal(by.p.canRecord, true);
  assert.equal(by.i.place.name, "Bay 2 (on Pump 7)");
  assert.equal(by["channel:c1"].kind, "Fed");
  assert.equal(by["channel:c1"].value, 400);
  assert.equal(by["channel:c1"].place.id, "pos2");
});

test("search over every column, sort worst first by default or by a column, blanks last", () => {
  const rows = tableRows([
    pt({ id: "a", name: "Alpha", reading: 120 }),
    pt({ id: "b", name: "Bravo", status: "high", reading: 250, tag: "PT-101" }),
    pt({ id: "c", name: "Charlie", reading: null, read_at: null, position: { id: "pos2", name: "Heater" } }),
  ], [], TODAY);
  assert.deepEqual(sortRows(rows).map((r) => r.key), ["b", "c", "a"]);
  assert.deepEqual(sortRows(rows, [{ col: "point", dir: -1 }]).map((r) => r.key), ["c", "b", "a"]);
  assert.deepEqual(sortRows(rows, [{ col: "latest", dir: 1 }]).map((r) => r.key), ["a", "b", "c"]);
  assert.deepEqual(searchRows(rows, "pt-101").map((r) => r.key), ["b"]);
  assert.deepEqual(searchRows(rows, "heater no reading").map((r) => r.key), ["c"]);
  assert.deepEqual(searchRows(rows, "attention").map((r) => r.key), ["b"]);
  assert.deepEqual(parseSort("due,-latest,trend,bogus"), [{ col: "due", dir: 1 }, { col: "latest", dir: -1 }]);
});

test("a value typed in place: a number, inside a setting's range, a counter only up", () => {
  assert.deepEqual(checkValue("12,5", pt()), { value: 12.5 });
  assert.equal(checkValue("", pt()).error, "Type a value");
  assert.equal(checkValue("abc", pt()).error, "Not a number");
  const heater = pt({ kind: "setting", unit: "°C", range_min: 10, range_max: 40 });
  assert.equal(checkValue("45", heater).error, "Highest allowed is 40 °C");
  assert.equal(checkValue("5", heater).error, "Lowest allowed is 10 °C");
  assert.match(checkValue("10", pt({ kind: "counter", unit: "h", reading: 20 })).error, /only goes up/);
  assert.equal(savedText(heater, 28), "✓ Set to 28 °C");
  assert.equal(savedText(pt({ kind: "setting", unit: "%" }), 60), "✓ Set to 60%");
  assert.equal(savedText(pt(), 3), "✓ Saved");
});

test("the row's ⋯ menu, and the CSV", () => {
  const [r] = tableRows([pt()], [], TODAY);
  assert.deepEqual(rowMenu(r).map((i) => i.label), ["Open", "Record a reading…", "Edit limits…", "Move…", "Retire…"]);
  const [s] = tableRows([pt({ kind: "setting" })], [], TODAY);
  assert.equal(rowMenu(s)[1].label, "Record a change…");
  const [f] = tableRows([pt({ source: "automated", tag: "x" })], [], TODAY);
  assert.equal(rowMenu(f)[1].disabled, true);
  const [i] = tableRows([pt({ position: null, item: { id: "i1", name: "Pump" } })], [], TODAY);
  assert.equal(rowMenu(i)[3].disabled, true);
  const [c] = tableRows([], [{ id: "c", name: "Plug", bands: [] }], TODAY);
  assert.deepEqual(rowMenu(c).map((x) => x.id), ["page", "bands"]);
  const csv = measurementsCsv([r]).split("\n");
  assert.equal(csv[0], "Position,Point,Tag,Kind,Latest,Unit,When,State,Next due");
  assert.match(csv[1], /^Filter,Pressure,,Condition,120,kPa,2026-11-08,OK,/);
});
