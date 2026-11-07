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
  return point.kind === "counter" ? "Counts use" : "No limits";
}

// The readings that count, oldest first (the struck-out ones left out).
export function recentValues(point, n = 12) {
  const live = liveReadings(point?.readings).filter((r) => r.value != null);
  // Manual points' trails are newest first; a feed's recent readings oldest first.
  const ordered = live.length > 1 && dayMs(live[0].at) > dayMs(live[live.length - 1].at) ? [...live].reverse() : live;
  return ordered.slice(-n).map((r) => ({ at: r.at, value: Number(r.value) }));
}

// Is a hand-read point due a reading?
export function readingDue(point, today = new Date().toISOString().slice(0, 10)) {
  if (!point || point.source !== "manual" || point.derived) return false;
  if (point.reading == null) return true;
  const rs = recentValues(point, 7);
  if (rs.length < 3) return false;
  const gaps = rs.slice(1).map((r, i) => daysBetween(rs[i].at, r.at)).filter((g) => g > 0).sort((a, b) => a - b);
  if (!gaps.length) return false;
  const usual = gaps[Math.floor(gaps.length / 2)];
  return daysBetween(rs[rs.length - 1].at, today) > Math.max(1, usual * 1.5);
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
  return [branch && placeOf(point, fittedAt), point.kind === "counter" ? "counter" : "condition", point.unit]
    .filter(Boolean).join(" · ");
}

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

// The row's ⋯ menu (RowMenu items). Recording stays in the menu for a feed's
// point, greyed with the reason, so it can be found and the reason read.
export function pointMenu(point) {
  const manual = point.source === "manual" && !point.derived;
  const items = [
    manual ? { id: "record", label: "Record a reading…" }
      : { id: "record", label: "Record a reading…", disabled: true,
        reason: point.derived ? "Worked out from a signal channel" : `Read by a feed${point.tag ? ` (${point.tag})` : ""}` },
  ];
  if (manual && point.readings?.length) items.push({ id: "history", label: "Readings…" });
  if (point.kind !== "counter") items.push({ id: "limits", label: "Edit limits…" });
  if (pointHref(point)) items.push({ id: "open", label: "Open the point" });
  if (point.alarm_work_order) items.push({ id: "work-order", label: `Open work order #${point.alarm_work_order.number}` });
  return items;
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

// The tab's own address: ?only=attention (the filter) and ?point= (the point
// whose history is open).
export function readMeasurementsQuery(params) {
  return { attention: params.get("only") === "attention", point: params.get("point") || null };
}
