// A measuring point in full (the Explorer's Measurements tab, &point=) and the readings
// table it shares with the Explorer's Readings dialog. Pure functions, tested
// in measuringPoint.test.js. The point is GET /api/maintenance/points/:id, as
// Maintenance.point gives it: latest reading, limits, status, the rate (a
// counter) or trend and projected alarm date (condition), and its recent
// readings (a hand-read point's newest first, struck-out ones included and
// marked; a feed's oldest first, values only).

import { isStruck, liveReadings, readingStatusText } from "./maintenanceReadings.js";
import { isSetting, needsAttention, nextReadingOn, pointChip, pointState, rangeText, STATES, withUnit } from "./measurementsTab.js";

// The line over the readings, in plain words.
export const READINGS_INTRO =
  "The latest readings. A voided reading stays listed and struck out, and is left out of rates, due dates and alarms.";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// "2026-10-18" → "18 Oct 2026" (the day as written: no time zone shift).
export function dayText(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || "");
  if (!m) return "";
  return `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

// When a reading was taken, on one line, to the precision it's known:
// "18 Oct 2026", "18 Oct 2026, 10:14", "Oct 2026", "2026". The server's
// `when` is the reading's local time ("2026-10-18 10:14"); a feed's reading
// has only `at` (an instant, shown as its day and time in UTC).
export function readingDate(r) {
  if (!r) return "";
  const when = r.when || "";
  if (r.precision === "year") return (when || r.at || "").slice(0, 4);
  if (r.precision === "month") {
    const m = /^(\d{4})-(\d{2})/.exec(when || r.at || "");
    return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : when;
  }
  const clock = (text) => (/[ T](\d{2}:\d{2})/.exec(text) || [])[1];
  if (when.length > 10) return `${dayText(when)}, ${clock(when)}`;
  const day = r.on || (r.at || "").slice(0, 10);
  const at = r.at || "";
  if (!r.on && !r.when && at.length > 10) {
    const t = clock(at);
    return t && t !== "00:00" ? `${dayText(day)}, ${t}` : dayText(day);
  }
  return dayText(day);
}

// A value to four significant figures at most ("7.123", "1250", "0.0042").
export function numberText(v) {
  if (v == null || v === "") return "—";
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  return String(Number(n.toPrecision(4)));
}

// The readings table's header for the value column: the unit lives here only.
export const valueHeading = (point) => (point?.unit ? `Value (${point.unit})` : "Value");

// What happened to a reading, as a chip: "Void" (struck out by hand),
// "Replaced" (struck out by a correction), "Correction" (it replaces
// another), or null for one as entered.
export function readingChip(r) {
  if (r.status === "voided") return { label: "Void", tone: "danger" };
  if (r.status === "replaced") return { label: "Replaced", tone: "neutral" };
  if (r.status === "correction") return { label: "Correction", tone: "accent" };
  return null;
}

// A hand-read point's readings can be corrected or voided (not a feed's,
// nor one worked out from a signal channel).
export const canEditReadings = (point) => point?.source === "manual" && !point?.derived;

// The rows of the readings table, newest first: the date on one line, the
// value, the note and what happened to it (a muted line under the note),
// whether it's struck out, and its chip.
export function readingRows(point) {
  const rows = (point?.readings || []).map((r, i) => ({
    id: r.id || `r${i}`,
    reading: r,
    date: readingDate(r),
    value: numberText(r.value),
    note: (r.note || "").trim(),
    detail: readingStatusText(r, dayText),
    struck: isStruck(r),
    chip: readingChip(r),
    sortAt: r.at || r.on || "",
  }));
  // A feed's readings come oldest first: show every table newest first.
  if (rows.length > 1 && rows[0].sortAt < rows[rows.length - 1].sortAt) rows.reverse();
  return rows;
}

// A reading's ⋯ menu (RowMenu items). A struck-out reading keeps the menu,
// greyed with the reason, so the row lines up and the reason can be read.
export function readingMenu(r) {
  if (isStruck(r)) {
    const reason = r.status === "replaced" ? "Corrected already: change the reading that replaced it" : "Voided already";
    return [
      { id: "correct", label: "Correct…", disabled: true, reason },
      { id: "void", label: "Void", disabled: true, reason },
    ];
  }
  return [{ id: "correct", label: "Correct…" }, { id: "void", label: "Void", danger: true }];
}

// The page's one state chip: OK, Needs attention (past or near a limit, or a
// reading due), or No reading. `title` carries the detail (the Explorer's
// chip's words: which limit, the limits, how long since the last reading).
export function pageState(point, today) {
  const detail = pointChip(point, today).title;
  if (isSetting(point)) {
    return point?.reading == null ? { label: "Not set yet", tone: "neutral", title: "Record the value it's set to" }
      : { label: "Setting", tone: "accent", title: "Holds until the next change: no alarm, never due" };
  }
  if (point?.reading == null) return { label: "No reading", tone: needsAttention(point, today) ? "warning" : "neutral", title: detail };
  if (needsAttention(point, today)) {
    return { label: "Needs attention", tone: pointState(point, today) === STATES.past ? "danger" : "warning", title: detail };
  }
  return { label: "OK", tone: "success", title: detail };
}

const signed = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${numberText(Math.abs(v))}`;

// The rate (a counter) or the trend (condition), in words: {label, text,
// detail}; null without one.
export function trendText(point) {
  if (!point || isSetting(point)) return null;
  const u = point.unit ? ` ${point.unit}` : "";
  if (point.kind === "counter") {
    if (point.rate_per_hour != null) return { label: "Rate", text: `${numberText(point.rate_per_hour)}${u} an hour`, detail: "from the last two readings" };
    if (point.rate_per_day != null) return { label: "Rate", text: `${numberText(point.rate_per_day)}${u} a day`, detail: "from its readings" };
    return null;
  }
  const detail = "over the last few readings";
  if (point.trend_per_hour != null) return { label: "Trend", text: `${signed(point.trend_per_hour)}${u} an hour`, detail };
  if (point.trend_per_day != null) return { label: "Trend", text: `${signed(point.trend_per_day)}${u} a day`, detail };
  return null;
}

// The dates the page shows, if the point has them: when its trend reaches a
// limit (condition) and when its next hand reading falls due.
export function pointDates(point) {
  return {
    reachesLimit: point?.projected_alarm || null,
    nextReading: point && point.reading != null ? nextReadingOn(point) : null,
  };
}

// Where a reading goes on the chart's time axis, as the chart reads dates
// (no time zone): its local time when known to the minute, else its day; a
// feed's instant as written.
export function chartTime(r) {
  if (r.when && r.when.length > 10) return r.when;
  if (r.on) return r.on;
  return (r.at || "").slice(0, 19).replace("T", " ");
}

// The chart's data: the readings that count, oldest first, and the limit
// lines (alarm below / above). Struck-out readings are left out. A setting
// draws as steps (`step`: each value holds until the next change), carried
// on to `today`, with its allowed range (`range`) in place of alarm limits.
export function chartData(point, today = null) {
  const live = liveReadings(point?.readings).filter((r) => r.value != null && (r.at || r.on));
  const pts = live.map((r) => ({ x: chartTime(r), y: Number(r.value), label: readingDate(r) }))
    .sort((a, b) => (a.x < b.x ? -1 : a.x > b.x ? 1 : 0));
  const limits = [
    point?.alarm_above != null && { value: Number(point.alarm_above), label: `Alarm above ${numberText(point.alarm_above)}` },
    point?.alarm_below != null && { value: Number(point.alarm_below), label: `Alarm below ${numberText(point.alarm_below)}` },
  ].filter(Boolean);
  if (!isSetting(point)) return { points: pts, limits, step: false, range: [] };
  const last = pts[pts.length - 1];
  const held = last && today && today > last.x.slice(0, 10) ? [...pts, { x: today, y: last.y, label: `${dayText(today)} (still set)`, held: true }] : pts;
  const range = [
    point.range_max != null && { value: Number(point.range_max), label: `Highest allowed ${numberText(point.range_max)}` },
    point.range_min != null && { value: Number(point.range_min), label: `Lowest allowed ${numberText(point.range_min)}` },
  ].filter(Boolean);
  return { points: held, limits, step: true, range };
}

// A setting's changes, newest first, as the point view lists them: "Set to 60%
// on 1 Oct 2026 (from 45%)", the work order (and task) it was set at, or by
// hand, and how long it held that value ("held 6 months"; the latest: "still
// set, 38 days so far", with `today`).
export function settingChangeRows(point, today = null) {
  const u = point?.unit || "";
  const changes = point?.changes || [];
  const day = (c) => String(c.on || c.when || "").slice(0, 10);
  return changes.map((c, i) => {
    const until = i ? day(changes[i - 1]) : today;
    const days = until && day(c) ? Math.round((Date.parse(`${until}T00:00:00Z`) - Date.parse(`${day(c)}T00:00:00Z`)) / 86400000) : null;
    return {
      key: c.reading_id || `c${i}`,
      text: `Set to ${withUnit(numberText(c.value), u)} on ${readingDate(c)}${c.from != null ? ` (from ${withUnit(numberText(c.from), u)})` : ""}`,
      workOrder: c.work_order || null,
      task: c.task || null,
      byHand: !c.work_order,
      held: days == null || days < 0 ? "" : i ? `held ${spanText(days)}` : `still set, ${spanText(days)} so far`,
    };
  });
}

// A number of days as people say it: "today", "1 day", "12 days", "about 3 months", "about 1.5 years".
export function spanText(days) {
  if (days <= 0) return "since today";
  if (days < 60) return `${days} ${days === 1 ? "day" : "days"}`;
  if (days < 548) return `about ${Math.round(days / 30.44)} months`;
  return `about ${Math.round((days / 365.25) * 10) / 10} years`;
}

// What a setting has been over time, in one line: "Set 3 times since 1 Apr
// 2026, between 45% and 60%. 60% now, since 1 Oct 2026." ("" with no changes).
export function settingSummary(point) {
  const changes = point?.changes || [];
  if (!changes.length) return "";
  const u = point.unit || "";
  const values = changes.map((c) => Number(c.value)).filter(Number.isFinite);
  const lo = Math.min(...values), hi = Math.max(...values);
  const first = changes[changes.length - 1], last = changes[0];
  const span = lo === hi ? `always ${withUnit(numberText(lo), u)}` : `between ${withUnit(numberText(lo), u)} and ${withUnit(numberText(hi), u)}`;
  const times = changes.length === 1 ? "Set once" : `Set ${changes.length} times`;
  return `${times} since ${readingDate(first)}, ${span}. ${withUnit(numberText(last.value), u)} now, since ${readingDate(last)}.`;
}

// The setting's allowed range as the page's fact: {text, detail}.
export function rangeFact(point) {
  const text = rangeText(point);
  return text ? { text: text[0].toUpperCase() + text.slice(1), detail: "a value outside it is refused" }
    : { text: "Any value", detail: "set a range to catch typing mistakes" };
}

// What the point is, on one muted line: "Condition · read by hand · mm/s".
export function pointMeta(point) {
  const source = point.derived ? "from a signal channel" : point.source === "automated"
    ? (point.tag ? `fed by ${point.tag}` : "fed automatically") : "read by hand";
  const kind = point.kind === "counter" ? "Counter" : isSetting(point) ? "Setting" : "Condition";
  return [kind, source, point.unit, point.retired && "retired"]
    .filter(Boolean).join(" · ");
}

// ---- Move… : a point to another position ----------------------------------
// The positions a point can move to, from the tree pane's flat rows
// (GET /api/maintenance/tree: id, name, parent_id, tag): in tree order, each
// with its depth and the path above it, the one it's on now marked `here`
// (it can't be picked). A query keeps the positions whose name, tag or path
// match, shown with their path; at most `limit` rows.
export function pointMoveChoices(positions, query = "", hereId = null, limit = 300) {
  const rows = positions || [];
  const byId = new Map(rows.map((p) => [p.id, p]));
  const kids = new Map();
  for (const p of rows) {
    const parent = p.parent_id && byId.has(p.parent_id) ? p.parent_id : null;
    if (!kids.has(parent)) kids.set(parent, []);
    kids.get(parent).push(p);
  }
  const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""), "en", { sensitivity: "base" });
  const out = [];
  const seen = new Set();
  const walk = (parent, depth, path) => {
    for (const p of (kids.get(parent) || []).slice().sort(byName)) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      out.push({ id: p.id, name: p.name || "(no name)", tag: p.tag || "", depth, path, here: p.id === hereId });
      walk(p.id, depth + 1, [...path, p.name || "(no name)"]);
    }
  };
  walk(null, 0, []);
  const q = String(query || "").trim().toLowerCase();
  const shown = q ? out.filter((r) => [r.name, r.tag, ...r.path].some((t) => String(t).toLowerCase().includes(q))) : out;
  return { rows: shown.slice(0, limit), more: shown.length > limit };
}
