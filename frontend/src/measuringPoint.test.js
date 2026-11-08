import test from "node:test";
import assert from "node:assert/strict";
import {
  READINGS_INTRO, canEditReadings, chartData, chartTime, dayText, numberText, pageState, pointDates, pointMeta, readingChip,
  readingDate, readingMenu, readingRows, trendText, valueHeading, pointMoveChoices, rangeFact, settingChangeRows, settingSummary, spanText } from "./measuringPoint.js";

const TODAY = "2026-11-07";
const point = (over = {}) => ({
  id: "p", name: "Bearing vibration", kind: "condition", unit: "mm/s", source: "manual", status: "ok",
  alarm_above: 7.1, alarm_below: null, reading: 3.2, read_at: "2026-11-06", readings: [], ...over,
});

test("dates read on one line, to the precision they're known", () => {
  assert.equal(dayText("2026-10-18"), "18 Oct 2026");
  assert.equal(dayText(""), "");
  assert.equal(readingDate({ on: "2026-10-18", at: "2026-10-18", precision: "day" }), "18 Oct 2026");
  assert.equal(readingDate({ on: "2026-10-18", when: "2026-10-18 10:14", precision: "minute" }), "18 Oct 2026, 10:14");
  assert.equal(readingDate({ on: "2026-10-01", when: "2026-10", precision: "month" }), "Oct 2026");
  assert.equal(readingDate({ on: "2026-01-01", when: "2026", precision: "year" }), "2026");
  // A feed's reading: an instant only.
  assert.equal(readingDate({ at: "2026-11-01T08:30:00+00:00" }), "1 Nov 2026, 08:30");
  assert.equal(readingDate({ at: "2026-11-01T00:00:00Z" }), "1 Nov 2026");
});

test("values to four significant figures, the unit in the heading only", () => {
  assert.equal(numberText(3.14159), "3.142");
  assert.equal(numberText(1250), "1250");
  assert.equal(numberText(null), "—");
  assert.equal(valueHeading(point()), "Value (mm/s)");
  assert.equal(valueHeading(point({ unit: "" })), "Value");
});

test("readings rows: newest first, struck-out ones marked with a chip and what happened", () => {
  const readings = [
    { id: "r3", on: "2026-11-06", at: "2026-11-06", value: 3.2, note: "After greasing", status: "correction",
      replaces: { id: "r2", at: "2026-11-06", value: 32 }, reason: "decimal point" },
    { id: "r2", on: "2026-11-06", at: "2026-11-06", value: 32, status: "replaced", voided_on: "2026-11-06",
      void_reason: "decimal point", replaced_by: { id: "r3", at: "2026-11-06", value: 3.2 } },
    { id: "r1", on: "2026-10-18", at: "2026-10-18", value: 2.9, status: "voided", voided_on: "2026-10-19", void_reason: "entered twice" },
    { id: "r0", on: "2026-10-11", at: "2026-10-11", value: 2.8, status: "ok", note: "  " },
  ];
  const rows = readingRows(point({ readings }));
  assert.deepEqual(rows.map((r) => r.id), ["r3", "r2", "r1", "r0"]);
  assert.deepEqual(rows.map((r) => r.struck), [false, true, true, false]);
  assert.deepEqual(rows.map((r) => r.chip?.label ?? null), ["Correction", "Replaced", "Void", null]);
  assert.equal(rows[2].date, "18 Oct 2026");
  assert.equal(rows[2].detail, "voided 19 Oct 2026: entered twice");
  assert.equal(rows[0].note, "After greasing");
  assert.equal(rows[3].note, "");
  // A feed's readings come oldest first; the table still shows the newest first.
  const feed = readingRows(point({ source: "automated", readings: [{ at: "2026-11-01T00:00:00Z", value: 1 }, { at: "2026-11-02T00:00:00Z", value: 2 }] }));
  assert.deepEqual(feed.map((r) => r.value), ["2", "1"]);
  assert.equal(readingChip({ status: "ok" }), null);
});

test("each reading's ⋯ menu: Correct… and Void, greyed with the reason once struck out", () => {
  assert.deepEqual(readingMenu({ status: "ok" }).map((i) => [i.id, i.label, !!i.disabled]), [["correct", "Correct…", false], ["void", "Void", false]]);
  const voided = readingMenu({ status: "voided" });
  assert.ok(voided.every((i) => i.disabled && i.reason === "Voided already"));
  assert.match(readingMenu({ status: "replaced" })[0].reason, /replaced it/);
  assert.equal(canEditReadings(point()), true);
  assert.equal(canEditReadings(point({ source: "automated" })), false);
  assert.equal(canEditReadings(point({ derived: { from: "c", rule: "rms" } })), false);
});

test("the page's state chip: OK, Needs attention, No reading", () => {
  assert.equal(pageState(point(), TODAY).label, "OK");
  assert.equal(pageState(point({ status: "high", reading: 7.5 }), TODAY).label, "Needs attention");
  assert.equal(pageState(point({ status: "high", reading: 7.5 }), TODAY).tone, "danger");
  assert.equal(pageState(point({ reading: 6.9 }), TODAY).tone, "warning"); // near the 7.1 limit
  const none = pageState(point({ reading: null, read_at: null }), TODAY);
  assert.equal(none.label, "No reading");
  assert.match(none.title, /first reading/);
});

test("rate or trend in words, and the dates a point has", () => {
  assert.equal(trendText(point({ kind: "counter", unit: "hours", rate_per_day: 12.5 })).text, "12.5 hours a day");
  assert.equal(trendText(point({ kind: "counter", unit: "hours", rate_per_day: 12 })).label, "Rate");
  assert.equal(trendText(point({ kind: "counter", unit: "hours", rate_per_day: 12, rate_per_hour: 0.5 })).text, "0.5 hours an hour");
  assert.deepEqual(trendText(point({ trend_per_day: 0.05 })), { label: "Trend", text: "+0.05 mm/s a day", detail: "over the last few readings" });
  assert.equal(trendText(point({ trend_per_day: -0.2 })).text, "−0.2 mm/s a day");
  assert.equal(trendText(point({ trend_per_day: null })), null);
  assert.equal(pointDates(point({ projected_alarm: "2027-01-10" })).reachesLimit, "2027-01-10");
  const weekly = [["2026-10-22", 3.1], ["2026-10-15", 3.0], ["2026-10-08", 2.9], ["2026-10-01", 2.8]]
    .map(([at, value], i) => ({ id: `r${i}`, at, on: at, value, status: "ok" }));
  assert.equal(pointDates(point({ readings: weekly })).nextReading, "2026-11-02");
  assert.equal(pointDates(point({ reading: null, readings: [] })).nextReading, null);
});

test("chart data: the readings that count, oldest first, with the limit lines", () => {
  const readings = [
    { id: "b", at: "2026-11-02", on: "2026-11-02", value: 3.1, status: "ok" },
    { id: "v", at: "2026-11-01", on: "2026-11-01", value: 30, status: "voided" },
    { id: "a", at: "2026-10-25", on: "2026-10-25", value: 2.9, status: "ok" },
  ];
  const d = chartData(point({ readings, alarm_below: 0.5 }));
  assert.deepEqual(d.points.map((p) => p.y), [2.9, 3.1]);
  assert.deepEqual(d.limits.map((l) => l.label), ["Alarm above 7.1", "Alarm below 0.5"]);
  assert.deepEqual(chartData(point({ alarm_above: null })).limits, []);
  // Time on the axis without a time zone: local time to the minute, else the day; a feed's instant as written.
  assert.equal(chartTime({ on: "2026-10-18", when: "2026-10-18 10:14", at: "2026-10-18T00:14:00+00:00" }), "2026-10-18 10:14");
  assert.equal(chartTime({ on: "2026-10-01", when: "2026-10", precision: "month" }), "2026-10-01");
  assert.equal(chartTime({ at: "2026-11-01T08:30:00+00:00" }), "2026-11-01 08:30:00");
});

test("what the point is, and the intro line in plain words", () => {
  assert.equal(pointMeta(point()), "Condition · read by hand · mm/s");
  assert.equal(pointMeta(point({ kind: "counter", unit: "hours", source: "automated", tag: "sensor.hours" })), "Counter · fed by sensor.hours · hours");
  assert.doesNotMatch(READINGS_INTRO, /Struck-out readings stay here/);
  assert.match(READINGS_INTRO, /voided reading stays listed/);
});


test("Move…: the positions in tree order, the one it's on marked, a search by name, tag or path", () => {
  const positions = [
    { id: "pool", name: "Pool", parent_id: null },
    { id: "water", name: "Pool water", parent_id: "pool" },
    { id: "chlor", name: "Salt chlorinator", parent_id: "pool", tag: "SC-1" },
    { id: "cell", name: "Cell", parent_id: "chlor" },
    { id: "shed", name: "Pump shed", parent_id: null },
  ];
  const all = pointMoveChoices(positions, "", "chlor");
  assert.deepEqual(all.rows.map((r) => [r.name, r.depth]), [["Pool", 0], ["Pool water", 1], ["Salt chlorinator", 1], ["Cell", 2], ["Pump shed", 0]]);
  assert.equal(all.rows.find((r) => r.id === "chlor").here, true);
  assert.equal(all.more, false);
  assert.deepEqual(pointMoveChoices(positions, "sc-1").rows.map((r) => r.id), ["chlor"]);
  // A position above matches everything inside it, each shown with its path.
  const inside = pointMoveChoices(positions, "salt");
  assert.deepEqual(inside.rows.map((r) => r.id), ["chlor", "cell"]);
  assert.deepEqual(inside.rows[1].path, ["Pool", "Salt chlorinator"]);
  assert.equal(pointMoveChoices(positions, "", null, 2).more, true);
});

test("a setting: steps carried on to today, its range, its changes in words", () => {
  const point = { kind: "setting", unit: "%", range_min: 0, range_max: 100, reading: 60,
    readings: [{ id: "b", on: "2026-10-01", value: 60, status: "ok" }, { id: "a", on: "2026-04-01", value: 45, status: "ok" }],
    changes: [
      { reading_id: "b", on: "2026-10-01", when: "2026-10-01", value: 60, from: 45, work_order: { id: "w1", number: 123 }, task: { id: "t", name: "Change-over" } },
      { reading_id: "a", on: "2026-04-01", when: "2026-04-01", value: 45, from: null },
    ] };
  const chart = chartData(point, "2026-11-08");
  assert.equal(chart.step, true);
  assert.deepEqual(chart.points.map((p) => [p.x, p.y]), [["2026-04-01", 45], ["2026-10-01", 60], ["2026-11-08", 60]]);
  assert.deepEqual(chart.range.map((r) => r.value), [100, 0]);
  assert.equal(chartData({ ...point, kind: "condition" }, "2026-11-08").points.length, 2);
  const rows = settingChangeRows(point);
  assert.equal(rows[0].text, "Set to 60% on 1 Oct 2026 (from 45%)");
  assert.equal(rows[0].workOrder.number, 123);
  assert.equal(rows[1].text, "Set to 45% on 1 Apr 2026");
  assert.equal(rows[0].byHand, false);
  assert.equal(rows[1].byHand, true);
  // How long each value held: the latest up to today.
  const held = settingChangeRows(point, "2026-11-08");
  assert.equal(held[0].held, "still set, 38 days so far");
  assert.equal(held[1].held, "held about 6 months");
  assert.equal(settingSummary(point), "Set 2 times since 1 Apr 2026, between 45% and 60%. 60% now, since 1 Oct 2026.");
  assert.equal(settingSummary({ ...point, changes: [point.changes[1]] }), "Set once since 1 Apr 2026, always 45%. 45% now, since 1 Apr 2026.");
  assert.equal(settingSummary({ kind: "setting", changes: [] }), "");
  assert.equal(spanText(1), "1 day");
  assert.equal(spanText(800), "about 2.2 years");
  assert.equal(rangeFact(point).text, "0 to 100%");
  assert.equal(rangeFact({ unit: "%" }).text, "Any value");
  assert.equal(pageState(point, "2026-11-08").label, "Setting");
  assert.equal(trendText(point), null);
  assert.equal(pointMeta({ ...point, source: "manual" }), "Setting · read by hand · %");
});
