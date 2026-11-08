import test from "node:test";
import assert from "node:assert/strict";
import {
  STATES, branchQuery, latestNote, limitsText, needsAttention, placeOf, pointChip, pointHref, pointMenu, pointState,
  VIEW_PARAMS, measurementAddress, nextReadingOn, pointPagePath, pointSubline, pointsCsv, readMeasurementsQuery, readingDue, recentValues, recordedBy, rowAction, sortPoints, stateText,
  channelChip, channelMenu, channelPlace, channelSubline, channelValues, isFed, measurementRows, rowNeedsAttention,
  isSetting, kindWord, rangeText, withUnit,
} from "./measurementsTab.js";

const TODAY = "2026-11-07";
const cond = (over = {}) => ({
  id: "p", name: "pH", kind: "condition", unit: "", source: "manual", status: "ok",
  alarm_above: 7.8, alarm_below: 7.0, reading: 7.4, read_at: "2026-11-06", readings: [], ...over,
});
// A manual trail: newest first, as the server sends it.
const trail = (days) => days.map(([at, value], i) => ({ id: `r${i}`, at, on: at, value, status: "ok" })).reverse();

test("pointState: past alarm, near a limit, OK, no limits, no reading", () => {
  assert.equal(pointState(cond({ status: "high", reading: 8.1 }), TODAY), STATES.past);
  assert.equal(pointState(cond({ status: "low", reading: 6.8 }), TODAY), STATES.past);
  // Band 7.0–7.8: within 0.08 of either limit is near.
  assert.equal(pointState(cond({ reading: 7.75 }), TODAY), STATES.near);
  assert.equal(pointState(cond({ reading: 7.05 }), TODAY), STATES.near);
  assert.equal(pointState(cond({ reading: 7.4 }), TODAY), STATES.ok);
  // One limit: a tenth of the limit's size.
  assert.equal(pointState(cond({ alarm_below: null, alarm_above: 10, reading: 9.2 }), TODAY), STATES.near);
  assert.equal(pointState(cond({ alarm_below: null, alarm_above: 10, reading: 8 }), TODAY), STATES.ok);
  // Heading for the limit within 30 days.
  assert.equal(pointState(cond({ projected_alarm: "2026-11-20" }), TODAY), STATES.near);
  assert.equal(pointState(cond({ projected_alarm: "2027-03-01" }), TODAY), STATES.ok);
  assert.equal(pointState(cond({ kind: "counter", alarm_above: null, alarm_below: null, reading: 1200 }), TODAY), STATES.nolimit);
  assert.equal(pointState(cond({ reading: null }), TODAY), STATES.none);
  assert.equal(pointState(null), STATES.none);
});

test("the state and the limits in words", () => {
  assert.equal(stateText(cond({ status: "high", reading: 8.1 }), TODAY), "Past alarm: above 7.8");
  assert.equal(stateText(cond({ status: "low", reading: 6.8 }), TODAY), "Past alarm: below 7");
  assert.equal(stateText(cond({ projected_alarm: "2026-11-20" }), TODAY), "Near limit: reaches it about 2026-11-20");
  assert.equal(stateText(cond(), TODAY), "OK");
  assert.equal(limitsText(cond({ unit: "ppm", alarm_below: 1, alarm_above: 3 })), "Alarm below 1 ppm or above 3 ppm");
  assert.equal(limitsText(cond({ alarm_below: null, alarm_above: null, kind: "counter" })), "Counts use");
  assert.equal(limitsText(cond({ alarm_below: null, alarm_above: null })), "No limits");
});

test("recent values come oldest first, struck-out readings left out, a feed's order kept", () => {
  const readings = trail([["2026-11-01", 7.1], ["2026-11-03", 7.2], ["2026-11-05", 7.3]]);
  readings[1] = { ...readings[1], status: "voided" };
  assert.deepEqual(recentValues({ readings }).map((r) => r.value), [7.1, 7.3]);
  const feed = [{ at: "2026-11-01T00:00:00Z", value: 1 }, { at: "2026-11-02T00:00:00Z", value: 2 }];
  assert.deepEqual(recentValues({ readings: feed }).map((r) => r.value), [1, 2]);
});

test("a hand-read point is due when never read, or when it's been longer than usual since the last", () => {
  const weekly = trail([["2026-10-01", 7.1], ["2026-10-08", 7.2], ["2026-10-15", 7.3], ["2026-10-22", 7.2]]);
  assert.equal(readingDue(cond({ readings: weekly }), "2026-10-27"), false); // 5 days on a 7-day round
  assert.equal(readingDue(cond({ readings: weekly }), TODAY), true); // 16 days
  assert.equal(readingDue(cond({ reading: null }), TODAY), true);
  assert.equal(readingDue(cond({ readings: weekly.slice(0, 2) }), TODAY), false); // too few to know the round
  assert.equal(readingDue(cond({ source: "automated", reading: null }), TODAY), false);
  // Due again half as long again as its usual round after the last: 7 days → 10.5 → 11 days on.
  assert.equal(nextReadingOn(cond({ readings: weekly })), "2026-11-02");
  assert.equal(nextReadingOn(cond({ readings: weekly.slice(0, 2) })), null);
  assert.equal(nextReadingOn(cond({ kind: "setting", readings: weekly })), null); // a setting is never due
  assert.equal(nextReadingOn(cond({ source: "automated", readings: weekly })), null);
  assert.equal(needsAttention(cond({ readings: weekly }), TODAY), true);
  assert.equal(needsAttention(cond({ readings: weekly }), "2026-10-27"), false);
});

test("sortPoints: past alarm, near, due, OK, no limits, never read; then by place and name", () => {
  const weekly = trail([["2026-10-01", 7.1], ["2026-10-08", 7.2], ["2026-10-15", 7.3]]);
  const pts = [
    cond({ id: "none", name: "Turbidity", reading: null, source: "automated" }),
    cond({ id: "ok-b", name: "pH", position: { id: "b", name: "Spa" } }),
    cond({ id: "ok-a", name: "pH", position: { id: "a", name: "Main pool" } }),
    cond({ id: "counter", name: "Pump hours", kind: "counter", alarm_above: null, alarm_below: null, reading: 900 }),
    cond({ id: "due", name: "Chlorine", readings: weekly }),
    cond({ id: "near", name: "pH", reading: 7.77 }),
    cond({ id: "past", name: "Temperature", status: "high", reading: 40 }),
  ];
  assert.deepEqual(sortPoints(pts, TODAY).map((p) => p.id), ["past", "near", "due", "ok-a", "ok-b", "counter", "none"]);
});

test("who recorded it, and where the point is", () => {
  // The note isn't part of it (it can run to a paragraph): latestNote gives it, for a mark.
  const noted = cond({ readings: [{ value: 1, note: " read at the work order ", status: "ok" }] });
  assert.equal(recordedBy(noted), "by hand");
  assert.equal(latestNote(noted), "read at the work order");
  assert.equal(latestNote(cond()), "");
  assert.equal(latestNote(cond({ source: "automated", readings: [{ value: 1, note: "x" }] })), "");
  assert.equal(recordedBy(cond()), "by hand");
  assert.equal(recordedBy(cond({ source: "automated", tag: "sensor.pool_ph" })), "feed: sensor.pool_ph");
  assert.equal(recordedBy(cond({ derived: { from: "c1" } })), "from a signal channel");
  assert.equal(placeOf(cond({ position: { id: "a", name: "Main pool" } })), "Main pool");
  assert.equal(placeOf(cond({ item: { id: "i1", name: "Pump #2" } }), new Map([["i1", "Filter pump"]])), "Filter pump (on Pump #2)");
  assert.equal(placeOf(cond({ item: { id: "i1", name: "Pump #2" } })), "Pump #2");
});

test("branchQuery asks for the branch's positions, its items and the items fitted there", () => {
  const rows = new Map([
    ["p1", { key: "p1", type: "pos", ref: { name: "Pool", item: null } }],
    ["p2", { key: "p2", type: "pos", ref: { name: "Filter pump", item: { id: "i1", name: "Pump #2" } } }],
    ["i9", { key: "i9", type: "item", ref: { name: "Spare pump" } }],
  ]);
  const q = branchQuery({ rows }, { pos: new Set(["p1", "p2"]), loc: new Set(), item: new Set(["i9"]) });
  assert.deepEqual(q.positionIds, ["p1", "p2"]);
  assert.deepEqual(q.itemIds.sort(), ["i1", "i9"]);
  assert.equal(q.fittedAt.get("i1"), "Filter pump");
});

test("the tab's address: the filter and the open point", () => {
  assert.deepEqual(readMeasurementsQuery(new URLSearchParams("tab=measurements&only=attention&readings=x1")),
    { attention: true, readings: "x1", point: null, channel: null });
  assert.deepEqual(readMeasurementsQuery(new URLSearchParams("tab=measurements&point=p1")), { attention: false, readings: null, point: "p1", channel: null });
  assert.deepEqual(readMeasurementsQuery(new URLSearchParams("tab=measurements&channel=c1")), { attention: false, readings: null, point: null, channel: "c1" });
  assert.deepEqual(VIEW_PARAMS, ["point", "channel", "readings"]);
});

test("the row's one state chip: the worst state, with the detail in its tooltip", () => {
  const weekly = trail([["2026-10-01", 7.1], ["2026-10-08", 7.2], ["2026-10-15", 7.3], ["2026-10-22", 7.2]]);
  const past = pointChip(cond({ status: "high", reading: 8.1, alarm_work_order: { id: "w1", number: 12 } }), TODAY);
  assert.deepEqual([past.label, past.tone], ["Past alarm", "danger"]);
  assert.equal(past.title, "Past alarm: above 7.8. Alarm below 7 or above 7.8. Work order #12 open");
  const near = pointChip(cond({ projected_alarm: "2026-11-20" }), TODAY);
  assert.deepEqual([near.label, near.tone], ["Near limit", "warning"]);
  assert.match(near.title, /reaches it about 2026-11-20/);
  const due = pointChip(cond({ readings: weekly, read_at: "2026-10-22" }), TODAY);
  assert.deepEqual([due.label, due.tone], ["Due", "warning"]);
  assert.match(due.title, /Last read 16 days ago/);
  assert.deepEqual([pointChip(cond(), TODAY).label, pointChip(cond(), TODAY).tone], ["OK", "success"]);
  assert.equal(pointChip(cond(), TODAY).title, "Inside its limits. Alarm below 7 or above 7.8");
  const counter = pointChip(cond({ kind: "counter", alarm_above: null, alarm_below: null, reading: 900 }), TODAY);
  assert.deepEqual([counter.label, counter.tone], ["No limits", "neutral"]);
  assert.equal(pointChip(cond({ alarm_above: null, alarm_below: null }), TODAY).label, "No limits");
  // Never read: a hand-read point is due its first reading; a feed's is waiting.
  assert.deepEqual([pointChip(cond({ reading: null }), TODAY).label, pointChip(cond({ reading: null }), TODAY).tone], ["Never read", "warning"]);
  const feed = pointChip(cond({ reading: null, source: "automated", tag: "sensor.ph" }), TODAY);
  assert.deepEqual([feed.label, feed.tone], ["Never read", "neutral"]);
  assert.match(feed.title, /Waiting for its feed \(sensor\.ph\)/);
});

test("the muted line under a point's name: the place only for a branch", () => {
  const p = cond({ unit: "ppm", position: { id: "a", name: "Main pool" } });
  assert.equal(pointSubline(p), "condition · ppm");
  assert.equal(pointSubline(p, { branch: true }), "Main pool · condition · ppm");
  assert.equal(pointSubline(cond({ kind: "counter", unit: "hours" })), "counter · hours");
  assert.equal(pointSubline(cond()), "condition");
});

test("clicking a row, and its ⋯ menu", () => {
  const read = cond({ position: { id: "a", name: "Pool" }, readings: [{ id: "r1", at: "2026-11-01", value: 7.2, status: "ok" }] });
  assert.equal(rowAction(read), "history");
  assert.equal(rowAction(cond({ readings: [] })), "record");
  assert.equal(rowAction(cond({ source: "automated", item: { id: "i1", name: "Pump" } })), "open");
  assert.equal(rowAction(cond({ source: "automated" })), null);
  assert.equal(pointHref(read), "/asset-register/positions/a");
  assert.equal(pointHref(cond({ item: { id: "i1" } })), "/asset-register/items/i1");
  assert.deepEqual(pointMenu(read).map((i) => i.id), ["page", "record", "history", "limits", "open", "move"]);
  assert.equal(pointMenu(read)[0].label, "Open");
  // A counter has no limits, but Edit… changes its kind; a feed's point can't be read by hand (greyed, with the reason).
  assert.deepEqual(pointMenu(cond({ kind: "counter" })).map((i) => i.id), ["page", "record", "limits", "move"]);
  assert.equal(pointMenu(cond({ kind: "counter" }))[2].label, "Edit…");
  assert.equal(pointMenu(read)[3].label, "Edit limits…");
  const feed = pointMenu(cond({ source: "automated", tag: "sensor.ph", alarm_work_order: { id: "w", number: 4 } }));
  assert.deepEqual(feed.map((i) => i.id), ["page", "record", "limits", "work-order", "move"]);
  assert.equal(feed[1].disabled, true);
  assert.equal(feed[1].reason, "Read by a feed (sensor.ph)");
  assert.equal(feed[3].label, "Open work order #4");
  assert.equal(pointMenu(read).find((i) => i.id === "open").label, "Open its position");
  assert.equal(pointMenu(cond({ item: { id: "i1" } })).find((i) => i.id === "open").label, "Open its item");
  // A point opens in the Explorer's Measurements tab, its position picked; an item's by locations.
  assert.equal(pointPagePath(read), "/asset-register/explorer?arrange=positions&sel=a&tab=measurements&point=p");
  assert.equal(pointPagePath(cond({ item: { id: "i1" } })), "/asset-register/explorer?arrange=locations&sel=i1&tab=measurements&point=p");
  // A bare id: the old address, which finds the place and comes back.
  assert.equal(pointPagePath("p 1"), "/asset-register/points/p%201");
  assert.equal(measurementAddress({ id: "c1", item: { id: "i1", fitted_to: { id: "f1" } } }, "channel", { bands: true }),
    "/asset-register/explorer?arrange=positions&sel=f1&tab=measurements&channel=c1#bands");
  // Move…: a position's point; an item's travels with the item, a band stays with its channel.
  assert.deepEqual(pointMenu(read).at(-1), { id: "move", label: "Move…" });
  assert.equal(pointMenu(cond({ item: { id: "i1" } })).at(-1).reason, "An item's point travels with the item");
  assert.equal(pointMenu(cond({ derived: true, position: { id: "a" } })).at(-1).disabled, true);
});

test("pointsCsv: one row per point shown, where it is, its latest reading, limits and state", () => {
  const points = [
    cond({ name: "pH", unit: "", position: { id: "a", name: "Pool" }, reading: 8.1, status: "high" }),
    cond({ id: "c", name: "=Run hours", kind: "counter", unit: "h", alarm_above: null, alarm_below: null, reading: null, read_at: null,
      item: { id: "i1", name: "Pump 7" }, source: "feed" }),
  ];
  const lines = pointsCsv(points, TODAY, new Map([["i1", "Bay 2"]])).split("\n");
  assert.equal(lines[0], "Point,Where,Kind,Unit,Latest reading,Read on,Source,Alarm below,Alarm above,State");
  assert.equal(lines[1], "pH,Pool,condition,,8.1,2026-11-06,by hand,7,7.8,Past alarm");
  // A name a spreadsheet would read as a formula is kept as text; no reading leaves the cells blank.
  assert.equal(lines[2], "'=Run hours,Bay 2 (on Pump 7),counter,h,,,,,,Never read");
  assert.equal(pointsCsv([], TODAY).split("\n").length, 1);
});

// A signal channel as GET /api/maintenance/points sends it in `channels`.
const chan = (over = {}) => ({
  id: "c", kind: "channel", name: "Pump power", unit: "W", tag: "plug.power", stat: "value", axis: "value",
  position: { id: "pos", name: "Filter pump" }, item: null,
  latest: { t: "2026-11-06T10:00:00Z", value: 650 },
  recent: [{ t: "2026-11-05T10:00:00Z", value: 610 }, { t: "2026-11-06T10:00:00Z", value: 650 }],
  bands: [{ point_id: "b", name: "Power level", status: "ok", alarm_above: 900 }], attention: false, ...over,
});

test("channelChip: Needs attention when a band is past its alarm, else OK, no bands or no data yet", () => {
  assert.equal(channelChip(chan()).label, "OK");
  assert.equal(channelChip(chan()).tone, "success");
  const past = channelChip(chan({ bands: [{ name: "Power level", status: "high" }, { name: "1x", status: "ok" }] }));
  assert.deepEqual([past.key, past.label, past.tone], ["attention", "Needs attention", "danger"]);
  assert.match(past.title, /Power level/);
  assert.equal(channelChip(chan({ bands: [] })).label, "No bands");
  assert.equal(channelChip(chan({ latest: null, recent: [] })).label, "No data yet");
  assert.match(channelChip(chan({ latest: null })).title, /plug\.power/);
});

test("measurementRows: channels sit in the same list as points, worst first, then by place and name", () => {
  const pastPoint = cond({ id: "p1", name: "pH", status: "high", reading: 8.1, position: { id: "pos", name: "Pool" } });
  const okPoint = cond({ id: "p2", name: "Chlorine", position: { id: "pos", name: "Pool" } });
  const okChan = chan({ id: "c1", name: "Pump power" });
  const badChan = chan({ id: "c2", name: "Bearing", bands: [{ name: "1x", status: "high" }] });
  const quietChan = chan({ id: "c3", name: "Spare plug", latest: null, recent: [] });
  const rows = measurementRows([okPoint, pastPoint], [quietChan, okChan, badChan], TODAY);
  assert.deepEqual(rows.map((r) => `${r.kind}:${r.row.id}`),
    // OK rows by place: Filter pump's channel before the Pool's point.
    ["channel:c2", "point:p1", "channel:c1", "point:p2", "channel:c3"]);
  assert.ok(rows.every((r) => r.key));
  assert.notEqual(rows.find((r) => r.row.id === "c1").key, "c1"); // a channel's key can't clash with a point's id
  assert.deepEqual(measurementRows([okPoint], undefined, TODAY).map((r) => r.kind), ["point"]);
  // The attention filter takes both kinds.
  assert.deepEqual(rows.filter((r) => rowNeedsAttention(r, TODAY)).map((r) => r.row.id), ["c2", "p1"]);
});

test("a channel row: Fed, where it is, its subline, recent values and its menu", () => {
  assert.equal(isFed(chan()), true);
  assert.equal(isFed(cond()), false);
  assert.equal(isFed(cond({ source: "automated" })), true);
  assert.equal(isFed(cond({ derived: { from: "c" } })), true);
  assert.equal(channelPlace(chan()), "Filter pump");
  const onItem = chan({ position: null, item: { id: "i", name: "Motor", fitted_to: { id: "p", name: "Filter pump" } } });
  assert.equal(channelPlace(onItem), "Filter pump (on Motor)");
  assert.equal(channelPlace(chan({ position: null, item: { id: "i", name: "Motor", fitted_to: null } })), "Motor");
  assert.equal(channelSubline(chan()), "sensor · W");
  assert.equal(channelSubline(chan({ stat: "rms", axis: "X", unit: "g" }), { branch: true }), "Filter pump · sensor · g · overall RMS (X)");
  assert.deepEqual(channelValues(chan()).map((r) => r.value), [610, 650]);
  assert.deepEqual(channelMenu(chan()).map((i) => i.label), ["Open", "Edit bands…", "Open its position"]);
  assert.deepEqual(channelMenu(onItem).map((i) => i.label), ["Open", "Edit bands…", "Open its item"]);
});

test("pointsCsv adds the channels shown after the points", () => {
  const csv = pointsCsv([cond()], TODAY, new Map(), [chan()]);
  const lines = csv.trim().split(/\r?\n/);
  assert.equal(lines.length, 3);
  assert.match(lines[2], /^Pump power,Filter pump,sensor,W,650,2026-11-06,sensor,,,OK$/);
});

test("a setting: a Setting chip with its value, never due, its range in words", () => {
  const setting = cond({ kind: "setting", unit: "%", alarm_above: null, alarm_below: null, reading: 60, read_at: "2026-10-01",
    range_min: 0, range_max: 100, readings: trail([["2026-01-01", 45], ["2026-04-01", 45], ["2026-10-01", 60]]) });
  assert.equal(isSetting(setting), true);
  assert.equal(kindWord(setting), "setting");
  assert.deepEqual([pointChip(setting, TODAY).label, pointChip(setting, TODAY).tone], ["Setting", "accent"]);
  assert.equal(pointChip(setting, TODAY).title, "Set to 60% since 2026-10-01. Allowed 0 to 100%");
  assert.equal(readingDue(setting, "2030-01-01"), false);
  assert.equal(needsAttention(setting, "2030-01-01"), false);
  assert.equal(pointChip(cond({ kind: "setting", reading: null }), TODAY).label, "Setting");
  assert.equal(limitsText(cond({ kind: "setting", alarm_above: null, alarm_below: null })), "Holds until changed");
  assert.equal(rangeText({ unit: "h", range_max: 24 }), "at most 24 h");
  assert.equal(rangeText({ unit: "h", range_min: 2 }), "at least 2 h");
  assert.equal(withUnit(60, "%"), "60%");
  assert.equal(withUnit(6, "h/day"), "6 h/day");
  assert.equal(pointSubline(setting), "setting · %");
  assert.equal(pointMenu({ ...setting, position: { id: "a" } })[1].label, "Record a change…");
  assert.equal(pointMenu({ ...setting, position: { id: "a" } }).find((i) => i.id === "limits").label, "Edit…");
});
