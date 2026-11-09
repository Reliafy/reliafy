// The Explorer's Measurements tab (Assets › Explorer, ?tab=measurements): every
// measuring point on the picked row and everything inside it, read from
// GET /api/maintenance/points (the same point views the position page's
// Measurements section shows). Pure functions, tested in measurementsTab.test.js.
//
// A point's state, in plain words: past its alarm limit, near it (within a
// tenth of the way to the limit, or heading there within 30 days at its
// trend), OK, no limits set (a counter, or a condition point with none), or no
// reading yet. A hand-read point is due a reading when it has never been read,
// or when it's been longer since its last reading than half as long again as
// its usual spacing (the middle gap between its recent readings). Points fed
// automatically are never "due": the feed sends them.

import { liveReadings } from "./maintenanceReadings.js";
import { toCsv } from "./csv.js";
import { EXPLORER_PATH } from "./navigation.js";

export const STATES = {
  past: { key: "past", label: "Past alarm", rank: 0 },
  near: { key: "near", label: "Near limit", rank: 1 },
  ok: { key: "ok", label: "OK", rank: 2 },
  nolimit: { key: "nolimit", label: "No limits", rank: 3 },
  none: { key: "none", label: "No reading yet", rank: 4 },
};

// How close counts as near: this share of the gap to the limit (of the band
// between the two limits when there are both, else of the limit's own size).
export const NEAR_SHARE = 0.1;
// Heading for a limit within this many days (the server's projected alarm date).
export const NEAR_DAYS = 30;

const DAY = 86400000;
const dayMs = (text) => {
  if (!text) return NaN;
  const t = Date.parse(text.length <= 10 ? `${text}T00:00:00Z` : text);
  return Number.isNaN(t) ? NaN : t;
};
export const daysBetween = (from, to) => (dayMs(to) - dayMs(from)) / DAY;

const hasLimits = (p) => p?.alarm_above != null || p?.alarm_below != null;

// A setting: a value someone sets (output %, hours a day, a setpoint). It holds
// until the next change, so it's never "due" and has no alarm.
export const isSetting = (p) => p?.kind === "setting";

// What a point is, in one word ("counter", "condition", "setting").
export const kindWord = (p) => (p?.kind === "counter" ? "counter" : isSetting(p) ? "setting" : "condition");

// A value with its unit: "60%" (a percentage goes straight after the number), "6 h".
export const withUnit = (value, unit) => (!unit ? String(value) : unit === "%" ? `${value}%` : `${value} ${unit}`);

// A setting's allowed range in words ("0 to 100%", "at least 2 h", "at most 24 h"), or "".
export function rangeText(point) {
  const lo = point?.range_min, hi = point?.range_max, u = point?.unit || "";
  if (lo != null && hi != null) return `${lo} to ${withUnit(hi, u)}`;
  if (lo != null) return `at least ${withUnit(lo, u)}`;
  if (hi != null) return `at most ${withUnit(hi, u)}`;
  return "";
}

// The point's state against its limits: one of STATES.
export function pointState(point, today = new Date().toISOString().slice(0, 10)) {
  if (!point || point.reading == null) return STATES.none;
  if (point.status === "high" || point.status === "low") return STATES.past;
  if (!hasLimits(point)) return STATES.nolimit;
  const v = Number(point.reading);
  const above = point.alarm_above, below = point.alarm_below;
  const band = above != null && below != null ? Math.abs(above - below) : null;
  const margin = (limit) => NEAR_SHARE * (band ?? (Math.abs(limit) || Math.abs(v) || 1));
  if (above != null && v >= above - margin(above)) return STATES.near;
  if (below != null && v <= below + margin(below)) return STATES.near;
  if (point.projected_alarm) {
    const left = daysBetween(today, point.projected_alarm);
    if (left <= NEAR_DAYS) return STATES.near;
  }
  return STATES.ok;
}

// The words for the state: which limit, for one past or near it.
export function stateText(point, today) {
  const s = pointState(point, today);
  if (s === STATES.past) return point.status === "high" ? `Past alarm: above ${point.alarm_above}` : `Past alarm: below ${point.alarm_below}`;
  if (s === STATES.near && point.projected_alarm && daysBetween(today, point.projected_alarm) <= NEAR_DAYS) {
    return `Near limit: reaches it about ${point.projected_alarm}`;
  }
  return s.label;
}

// The limits in words ("alarm above 7.1 mm/s", "below 1.0 and above 3.0").
export function limitsText(point) {
  const u = point.unit ? ` ${point.unit}` : "";
  const parts = [point.alarm_below != null && `below ${point.alarm_below}${u}`,
    point.alarm_above != null && `above ${point.alarm_above}${u}`].filter(Boolean);
  if (parts.length) return `Alarm ${parts.join(" or ")}`;
  if (isSetting(point)) return rangeText(point) ? `Allowed ${rangeText(point)}` : "Holds until changed";
  return point.kind === "counter" ? "Counts use" : "No limits";
}

// The readings that count, oldest first (the struck-out ones left out).
export function recentValues(point, n = 12) {
  const live = liveReadings(point?.readings).filter((r) => r.value != null);
  // Manual points' trails are newest first; a feed's recent readings oldest first.
  const ordered = live.length > 1 && dayMs(live[0].at) > dayMs(live[live.length - 1].at) ? [...live].reverse() : live;
  return ordered.slice(-n).map((r) => ({ at: r.at, value: Number(r.value) }));
}

// How long a hand-read point can go between readings before one is due:
// half as long again as its usual spacing (at least a day), in days. null
// when it isn't read by hand or has too few readings to know its round.
function allowedGap(point) {
  // A setting holds until it's changed: it's never due a reading.
  if (!point || point.source !== "manual" || point.derived || isSetting(point)) return null;
  const rs = recentValues(point, 7);
  if (rs.length < 3) return null;
  const gaps = rs.slice(1).map((r, i) => daysBetween(rs[i].at, r.at)).filter((g) => g > 0).sort((a, b) => a - b);
  if (!gaps.length) return null;
  const usual = gaps[Math.floor(gaps.length / 2)];
  return { last: rs[rs.length - 1].at, days: Math.max(1, usual * 1.5) };
}

// Is a hand-read point due a reading?
export function readingDue(point, today = new Date().toISOString().slice(0, 10)) {
  if (!point || point.source !== "manual" || point.derived || isSetting(point)) return false;
  if (point.reading == null) return true;
  const gap = allowedGap(point);
  return gap ? daysBetween(gap.last, today) > gap.days : false;
}

// The day a hand-read point's next reading falls due (YYYY-MM-DD), by its
// usual round; null when it has no round yet (or isn't read by hand).
export function nextReadingOn(point) {
  const gap = allowedGap(point);
  if (!gap) return null;
  const t = dayMs(gap.last.slice(0, 10)) + Math.ceil(gap.days) * DAY;
  return Number.isNaN(t) ? null : new Date(t).toISOString().slice(0, 10);
}

// Needs a look: past its alarm, near a limit, or due a reading.
export function needsAttention(point, today) {
  const s = pointState(point, today);
  return s === STATES.past || s === STATES.near || readingDue(point, today);
}

// Who or what recorded the latest reading. The reading's note isn't part of
// it: a note can run to a paragraph, so the row shows only a mark (latestNote)
// and the full note is in the readings history.
export function recordedBy(point) {
  if (point.derived) return "from a signal channel";
  if (point.source === "automated") return point.tag ? `feed: ${point.tag}` : "a feed";
  return "by hand";
}

// The latest reading's note ("" when it has none).
export function latestNote(point) {
  if (!point || point.source !== "manual" || point.derived) return "";
  return (liveReadings(point.readings)[0]?.note || "").trim();
}

// The row's one state chip: the worst of past alarm, near a limit, due a
// reading, OK, no limits, never read. `tone` is a Chip tone; `title` (its
// tooltip) has the detail the row leaves out: which limit, the limits
// themselves, how long since the last reading.
export function pointChip(point, today) {
  if (isSetting(point)) {
    const since = point.read_at ? ` since ${String(point.read_at).slice(0, 10)}` : "";
    return { key: "setting", label: "Setting", tone: "accent",
      title: point.reading != null ? `Set to ${withUnit(point.reading, point.unit)}${since}. ${limitsText(point)}` : "Not set yet: record its value" };
  }
  const s = pointState(point, today);
  const due = readingDue(point, today);
  const limits = point.kind === "counter" && !hasLimits(point) ? "" : limitsText(point);
  const since = point.read_at ? Math.floor(daysBetween(point.read_at.slice(0, 10), today)) : null;
  const sinceText = since != null && since >= 0 ? `Last read ${since === 0 ? "today" : since === 1 ? "yesterday" : `${since} days ago`}` : "";
  const wo = point.alarm_work_order ? `Work order #${point.alarm_work_order.number} open` : "";
  const title = (...parts) => parts.filter(Boolean).join(". ");
  if (s === STATES.past) return { key: "past", label: "Past alarm", tone: "danger", title: title(stateText(point, today), limits, due && "A reading is due", wo) };
  if (s === STATES.near) return { key: "near", label: "Near limit", tone: "warning", title: title(stateText(point, today), limits, due && "A reading is due", wo) };
  if (s === STATES.none) {
    return due
      ? { key: "never", label: "Never read", tone: "warning", title: title("Never read: record its first reading", limits) }
      : { key: "never", label: "Never read", tone: "neutral", title: title(point.derived ? "Nothing from its signal channel yet" : `Waiting for its feed${point.tag ? ` (${point.tag})` : ""}`, limits) };
  }
  if (due) return { key: "due", label: "Due", tone: "warning", title: title("A reading is due: longer than usual since the last", sinceText, limits, wo) };
  if (s === STATES.ok) return { key: "ok", label: "OK", tone: "success", title: title("Inside its limits", limits, wo) };
  return { key: "nolimit", label: "No limits", tone: "neutral",
    title: point.kind === "counter" ? "Counts use: no alarm limits" : "No alarm limits set: edit its limits to be warned" };
}

// The muted line under a point's name: where it is (only when the tab shows
// a branch, so the place varies), what it measures, its unit.
export function pointSubline(point, { branch = false, fittedAt = new Map() } = {}) {
  return [branch && placeOf(point, fittedAt), kindWord(point), point.unit]
    .filter(Boolean).join(" · ");
}

// The measuring point's own page.
// A point or a sensor channel opens inside the Explorer's Measurements tab
// (?tab=measurements&point= or &channel=), the tree still on the left with its
// place picked: its position (a fitted item's channel: the item's position), or
// its item's row arranged by locations. With no place known (a bare id), the
// old address, which reads the point or channel and comes back here.
export function measurementAddress(thing, kind = "point", { bands = false } = {}) {
  const id = typeof thing === "string" ? thing : thing?.id;
  const pos = thing?.position?.id || thing?.item?.fitted_to?.id;
  const sel = pos || thing?.item?.id;
  if (!sel) return `/asset-register/${kind === "channel" ? "channels" : "points"}/${encodeURIComponent(id || "")}${bands ? "#bands" : ""}`;
  const q = new URLSearchParams({ arrange: pos ? "positions" : "locations", sel, tab: "measurements", [kind]: id || "" });
  return `${EXPLORER_PATH}?${q}${bands ? "#bands" : ""}`;
}

// A measuring point's own view (in the Explorer, as above).
export const pointPagePath = (point) => measurementAddress(point, "point");

// The page a point lives on: its position's, or its item's.
export function pointHref(point) {
  if (point.position?.id) return `/asset-register/positions/${point.position.id}`;
  if (point.item?.id) return `/asset-register/items/${point.item.id}`;
  return null;
}

// What clicking a point's row does: its readings history (a hand-read point
// with readings), its first reading (one never read), else its page (a feed's
// readings are kept by the feed).
export function rowAction(point) {
  const manual = point.source === "manual" && !point.derived;
  if (manual) return point.readings?.length ? "history" : "record";
  return pointHref(point) ? "open" : null;
}

// The row's ⋯ menu (RowMenu items): "Open" (the point's own page) first. Recording stays in the menu for a feed's
// point, greyed with the reason, so it can be found and the reason read.
export function pointMenu(point) {
  const manual = point.source === "manual" && !point.derived;
  const record = isSetting(point) ? "Record a change…" : "Record a reading…";
  const items = [
    { id: "page", label: "Open" },
    manual ? { id: "record", label: record }
      : { id: "record", label: record, disabled: true,
        reason: point.derived ? "Worked out from a signal channel" : `Read by a feed${point.tag ? ` (${point.tag})` : ""}` },
  ];
  if (manual && point.readings?.length) items.push({ id: "history", label: "Readings…" });
  // Edit limits… (a condition point), or Edit… (its kind, a setting's range).
  items.push({ id: "limits", label: editLabel(point) });
  if (pointHref(point)) items.push({ id: "open", label: point.position?.id ? "Open its position" : "Open its item" });
  if (point.alarm_work_order) items.push({ id: "work-order", label: `Open work order #${point.alarm_work_order.number}` });
  items.push(pointMoveItem(point));
  return items;
}

// The edit dialog's name: a condition point's limits, else the point (its kind, a setting's range).
export const editLabel = (point) => (point?.kind === "condition" ? "Edit limits…" : "Edit…");

// "Move…": a position's point to another position. An item's point travels
// with the item, and a band or level stays with its signal channel.
export function pointMoveItem(point) {
  if (point.derived) return { id: "move", label: "Move…", disabled: true, reason: "Stays with its signal channel" };
  if (!point.position?.id) return { id: "move", label: "Move…", disabled: true, reason: "An item's point travels with the item" };
  return { id: "move", label: "Move…" };
}

// Where the point is: the position it's on, or for an item's point the
// position the item is fitted to (`fittedAt`: item id → position name).
export function placeOf(point, fittedAt = new Map()) {
  if (point.position) return point.position.name;
  if (point.item) {
    const at = fittedAt.get(point.item.id);
    return at ? `${at} (on ${point.item.name})` : point.item.name;
  }
  return "";
}

// Past alarm first, then near, due, OK, no limits, never read; then by place
// and name.
export function sortPoints(points, today, fittedAt = new Map()) {
  const cmp = (a, b) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
  const rank = (p) => {
    const s = pointState(p, today);
    if (s === STATES.past) return 0;
    if (s === STATES.near) return 1;
    if (readingDue(p, today)) return 2;
    return s.rank + 1;
  };
  return [...points].sort((a, b) => rank(a) - rank(b) || cmp(placeOf(a, fittedAt), placeOf(b, fittedAt)) || cmp(a.name, b.name));
}

// What to ask the server for: the positions in the branch, and the items in
// it (rows of their own) and fitted to its positions (their points travel
// with them). `branch` is explorerTabs.branchOf's {pos, loc, item}.
export function branchQuery(display, branch) {
  const positionIds = [...branch.pos];
  const items = new Set(branch.item);
  const fittedAt = new Map();
  for (const k of branch.pos) {
    const r = display?.rows?.get(k);
    const it = r?.ref?.item;
    if (it?.id) {
      items.add(it.id);
      fittedAt.set(it.id, r.ref.name);
    }
  }
  return { positionIds, itemIds: [...items], fittedAt };
}

// The tab's own address: ?only=attention (the filter), ?readings= (the point
// whose Readings dialog is open), and ?point= or ?channel= (the one open in
// full in the tab, with a link back to the list).
export function readMeasurementsQuery(params) {
  return {
    attention: params.get("only") === "attention",
    readings: params.get("readings") || null,
    point: params.get("point") || null,
    channel: params.get("channel") || null,
    consumable: params.get("consumable") || null,
  };
}

// What leaves the address with the point or channel view: going back to the
// list, another row, or another tab.
export const VIEW_PARAMS = ["point", "channel", "consumable", "readings"];

// ---- signal channels as rows ---------------------------------------------------------

// A row is fed (the "Fed" chip) when nobody reads it by hand: a signal channel,
// a feed's point, or a point worked out from a channel.
export const isFed = (row) => row?.kind === "channel" || row?.source !== "manual" || !!row?.derived;

// The channel's state, from its watch bands and levels: Needs attention when
// any is past its alarm limit, OK when all are inside, else no bands or no
// data yet. The same shape as pointChip.
export function channelChip(ch) {
  const bands = ch?.bands || [];
  const past = bands.filter((b) => b.status === "high" || b.status === "low");
  const names = (bs) => bs.map((b) => b.name).join(", ");
  if (past.length) return { key: "attention", label: "Needs attention", tone: "danger", title: `Past its alarm: ${names(past)}` };
  if (!ch?.latest) {
    return { key: "never", label: "No data yet", tone: "neutral", title: `Waiting for its first snapshot${ch?.tag ? ` (${ch.tag})` : ""}` };
  }
  if (!bands.length) return { key: "nolimit", label: "No bands", tone: "neutral", title: "No watch bands or levels: add one to be warned" };
  return { key: "ok", label: "OK", tone: "success", title: `Inside its limits: ${names(bands)}` };
}

export const channelNeedsAttention = (ch) => channelChip(ch).key === "attention";

// Where the channel is: its position, or the item it's on (and where that's fitted).
export function channelPlace(ch, fittedAt = new Map()) {
  if (ch?.position) return ch.position.name;
  if (ch?.item) {
    const at = ch.item.fitted_to?.name || fittedAt.get(ch.item.id);
    return at ? `${at} (on ${ch.item.name})` : ch.item.name;
  }
  return "";
}

// The muted line under a channel's name: where (in a branch), "sensor", its
// unit, and which level the latest value is ("overall RMS" for a burst).
export function channelSubline(ch, { branch = false, fittedAt = new Map() } = {}) {
  const level = ch.stat === "rms" ? `overall RMS${ch.axis ? ` (${ch.axis})` : ""}` : "";
  return [branch && channelPlace(ch, fittedAt), "sensor", ch.unit, level].filter(Boolean).join(" · ");
}

// The recent levels, oldest first, as recentValues gives a point's.
export const channelValues = (ch, n = 12) => (ch?.recent || []).filter((r) => r.value != null)
  .slice(-n).map((r) => ({ at: r.t, value: Number(r.value) }));

// The channel row's ⋯ menu: Open (its own page: spectrum, bands, settings) and
// Edit bands… (the same page, at its watch bands).
export function channelMenu(ch) {
  const items = [{ id: "page", label: "Open" }, { id: "bands", label: "Edit bands…" }];
  if (ch.position?.id) items.push({ id: "open", label: "Open its position" });
  else if (ch.item?.id) items.push({ id: "open", label: "Open its item" });
  return items;
}

// Points and channels as one list, worst first: past alarm or a channel past a
// band's alarm, near a limit, due, OK, no limits, never read; then by place
// and name. Each row is { kind: "point" | "channel", key, row }.
export function measurementRows(points, channels, today, fittedAt = new Map()) {
  const cmp = (a, b) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
  const pointRank = (p) => {
    const s = pointState(p, today);
    if (s === STATES.past) return 0;
    if (s === STATES.near) return 1;
    if (readingDue(p, today)) return 2;
    return s.rank + 1;
  };
  const chRank = { attention: 0, ok: STATES.ok.rank + 1, nolimit: STATES.nolimit.rank + 1, never: STATES.none.rank + 1 };
  const rows = [
    ...(points || []).map((p) => ({ kind: "point", key: p.id, row: p, rank: pointRank(p), place: placeOf(p, fittedAt) })),
    ...(channels || []).map((c) => ({
      kind: "channel", key: `channel:${c.id}`, row: c, rank: chRank[channelChip(c).key], place: channelPlace(c, fittedAt),
    })),
  ];
  return rows.sort((a, b) => a.rank - b.rank || cmp(a.place, b.place) || cmp(a.row.name, b.row.name))
    .map(({ kind, key, row }) => ({ kind, key, row }));
}

// Needs a look: a point past or near its limit or due a reading; a channel past a band's alarm.
export const rowNeedsAttention = (r, today) => (r.kind === "channel" ? channelNeedsAttention(r.row) : needsAttention(r.row, today));

// The points shown, as a CSV file (the panel heading's "…" › Export CSV): one
// row each, in the order shown, with where it is, its latest reading and
// when, its limits and its state in words.
export function pointsCsv(points, today, fittedAt = new Map(), channels = []) {
  const head = ["Point", "Where", "Kind", "Unit", "Latest reading", "Read on", "Source", "Alarm below", "Alarm above", "State"];
  const num = (v) => (v == null ? "" : v);
  const rows = (points || []).map((p) => [
    p.name || "", placeOf(p, fittedAt), kindWord(p), p.unit || "",
    num(p.reading), p.read_at ? String(p.read_at).slice(0, 10) : "",
    p.read_at ? (p.derived ? "signal" : p.source === "manual" ? "by hand" : "feed") : "",
    num(p.alarm_below), num(p.alarm_above), pointChip(p, today).label,
  ]);
  // A channel: its latest level, from its sensor; its limits are its bands'.
  const chRows = (channels || []).map((c) => [
    c.name || "", channelPlace(c, fittedAt), "sensor", c.unit || "", num(c.latest?.value),
    c.latest?.t ? String(c.latest.t).slice(0, 10) : "", c.latest ? "sensor" : "", "", "", channelChip(c).label,
  ]);
  return toCsv([head, ...rows, ...chRows]);
}
