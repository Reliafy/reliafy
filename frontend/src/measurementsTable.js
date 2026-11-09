// The Explorer's Measurements tab's rows (Derryn, 9 Nov 2026: "go down and
// look at all the measuring points against particular things", see their
// values, enter them, create new ones): one per measuring point, setting,
// consumable and sensor channel, from GET /api/maintenance/points: its place,
// name and tag, Kind, Latest (value with unit, and when), State, Trend (a step
// line for a setting, bars for a consumable), Next due, whether it can be
// recorded in place, and its ⋯. Search, worst-first order and the CSV too.
// Pure functions, tested in measurementsTable.test.js. The tab draws them as
// rows of the tree (explorerMeasurements.js, components/MeasurementTable.jsx).

import { toCsv } from "./csv.js";
import { nextSort, sortParam } from "./lsaTab.js";
import { dayText, numberText } from "./measuringPoint.js";
import { consumableState, monthlyTotals, qtyText, stockText } from "./consumables.js";
import {
  STATES, channelChip, channelPlace, channelValues, isFed, isSetting, needsAttention, nextReadingOn, placeOf, pointChip,
  pointState, readingDue, recentValues, withUnit,
} from "./measurementsTab.js";

export { nextSort, sortParam };

export const MEAS_COLUMNS = [
  { id: "position", label: "Position", width: 170, title: "The position (or item) it's on" },
  { id: "point", label: "Point", width: 200, title: "Its name, and the tag a feed sends" },
  { id: "kind", label: "Kind", width: 104, title: "Condition, setting, counter, or fed (a sensor or a feed sends it)" },
  { id: "latest", label: "Latest", width: 150, num: true, title: "The latest value, and when" },
  { id: "state", label: "State", width: 150, title: "OK, needs attention, a reading due, or no reading yet; a setting says when it was set" },
  { id: "trend", label: "Trend", width: 132, title: "The recent values (a setting: a step line)" },
  { id: "due", label: "Next due", width: 112, title: "When the next hand reading falls due, by its usual round" },
  { id: "record", label: "Record", width: 128, title: "Type a value and press Enter to record it now" },
];
export const DEFAULT_MEAS_COLUMNS = MEAS_COLUMNS.map((c) => c.id);
const SORTABLE = new Set(["position", "point", "kind", "latest", "state", "due"]);

// What kind of row it is, in a word: Fed (a sensor channel, a feed's point, one
// worked out from a channel), Setting, Counter or Condition.
export function kindLabel(r) {
  if (r.kind === "consumable") return "Consumable";
  if (r.kind === "channel" || isFed(r)) return "Fed";
  if (isSetting(r)) return "Setting";
  if (r.kind === "counter") return "Counter";
  return "Condition";
}

// The row's state: { label, tone, rank, title }. Worst first: past an alarm,
// near one (both "Needs attention"), a reading due, never read, OK, a setting,
// waiting for a feed.
export function rowState(r, today) {
  if (r.kind === "channel") {
    const c = channelChip(r);
    if (c.key === "attention") return { label: "Needs attention", tone: "danger", rank: 0, title: c.title };
    if (c.key === "never") return { label: "No reading", tone: "neutral", rank: 6, title: c.title };
    return { label: "OK", tone: "success", rank: 4, title: c.title };
  }
  const chip = pointChip(r, today);
  if (isSetting(r)) {
    return r.reading != null
      ? { label: `Set ${dayText(String(r.read_at || "").slice(0, 10))}`, tone: "accent", rank: 5, title: chip.title }
      : { label: "Not set", tone: "neutral", rank: 5, title: chip.title };
  }
  const s = pointState(r, today);
  if (s === STATES.past) return { label: "Needs attention", tone: "danger", rank: 0, title: chip.title };
  if (s === STATES.near) return { label: "Needs attention", tone: "warning", rank: 1, title: chip.title };
  if (r.reading == null) {
    const due = readingDue(r, today);
    return { label: "No reading", tone: due ? "warning" : "neutral", rank: due ? 3 : 6, title: chip.title };
  }
  if (readingDue(r, today)) return { label: "Due", tone: "warning", rank: 2, title: chip.title };
  return { label: "OK", tone: "success", rank: 4, title: chip.title };
}

// Every row, from the points read: { key, type ("point" | "channel"), item (the
// point or channel), place ({id, name}), name, tag, kind, value, unit, when,
// state, values (oldest first, for the sparkline), step (a setting), due,
// canRecord }.
export function tableRows(points = [], channels = [], today, fittedAt = new Map(), consumables = []) {
  const rows = [];
  for (const p of points || []) {
    const placeId = p.position?.id || p.item?.id || "";
    rows.push({
      key: p.id, type: "point", item: p,
      place: { id: placeId, name: placeOf(p, fittedAt) || "" },
      name: p.name || "", tag: p.tag || "", kind: kindLabel(p),
      value: p.reading, unit: p.unit || "", when: p.read_at ? String(p.read_at) : null,
      state: rowState(p, today), values: recentValues(p, 12), step: isSetting(p),
      due: isSetting(p) ? null : (p.reading == null && readingDue(p, today) ? today : nextReadingOn(p)),
      canRecord: p.source === "manual" && !p.derived && !p.retired,
      attention: isSetting(p) ? false : needsAttention(p, today),
    });
  }
  for (const c of channels || []) {
    const placeId = c.position?.id || c.item?.fitted_to?.id || c.item?.id || "";
    const r = { ...c, kind: "channel" };
    rows.push({
      key: `channel:${c.id}`, type: "channel", item: c,
      place: { id: placeId, name: channelPlace(c, fittedAt) || "" },
      name: c.name || "", tag: c.tag || "", kind: "Fed",
      value: c.latest?.value ?? null, unit: c.unit || "", when: c.latest?.t || null,
      state: rowState(r, today), values: channelValues(c, 12), step: false, due: null, canRecord: false,
      attention: rowState(r, today).rank === 0,
    });
  }
  // A consumable: its last addition, its total of the last 90 days, monthly bars.
  for (const c of consumables || []) {
    const last = c.uses?.[0];
    rows.push({
      key: `consumable:${c.key}`, type: "consumable", item: c,
      place: { id: c.position?.id || "", name: c.position?.name || "" },
      name: c.name || "", tag: c.part?.part_number || "", kind: "Consumable",
      value: last ? last.qty : null, unit: c.unit || "", when: last?.on || null,
      state: consumableState(c, today), values: monthlyTotals(c.uses, today, 6).map((m) => ({ at: m.month, value: m.value })),
      bars: true, step: false, due: null, canRecord: true, attention: false, stock: stockText(c),
    });
  }
  return rows;
}

// When a value was taken, short: "18 Oct 2026" (a feed's instant: its day).
export const whenText = (when) => (when ? dayText(String(when).slice(0, 10)) : "");

// What a column shows for a row (and what it searches by).
export function cellText(r, col) {
  switch (col) {
    case "position": return r.place.name;
    case "point": return [r.name, r.tag].filter(Boolean).join(" ");
    case "kind": return r.kind;
    case "latest": return r.value == null ? "" : `${withUnit(numberText(r.value), r.unit)} ${whenText(r.when)}`.trim();
    case "state": return r.state.label;
    case "due": return r.due ? dayText(r.due) : "";
    default: return "";
  }
}

// Every word of the search in one of the row's columns (or its state's detail).
export function searchRows(rows, q) {
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return rows;
  return rows.filter((r) => {
    const hay = [...DEFAULT_MEAS_COLUMNS.map((c) => cellText(r, c)), r.state.title || ""].join(" ").toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

// ?sort=due,-latest: the keys in order ("-": descending), columns that sort only.
export function parseSort(param) {
  return String(param || "").split(",").map((s) => s.trim()).filter(Boolean)
    .map((s) => (s.startsWith("-") ? { col: s.slice(1), dir: -1 } : { col: s, dir: 1 }))
    .filter((k) => SORTABLE.has(k.col)).slice(0, 3);
}
export const sortable = (col) => SORTABLE.has(col);

const cmpText = (a, b) => a.localeCompare(b, "en", { numeric: true, sensitivity: "base" });
function sortValue(r, col) {
  if (col === "state") return r.state.rank;
  if (col === "latest") return r.value == null ? null : Number(r.value);
  if (col === "due") return r.due || null;
  const v = cellText(r, col);
  return v === "" ? null : v.toLowerCase();
}

// Sorted by the keys (blanks last either way); with none, worst first. Then
// position and point A–Z.
export function sortRows(rows, keys = []) {
  const by = keys.length ? keys : [{ col: "state", dir: 1 }];
  const cmpKey = (a, b, { col, dir }) => {
    const x = sortValue(a, col), y = sortValue(b, col);
    if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
    return (typeof x === "number" ? x - y : cmpText(x, y)) * dir;
  };
  return [...rows].sort((a, b) => {
    for (const k of [...by, { col: "position", dir: 1 }, { col: "point", dir: 1 }]) {
      const c = cmpKey(a, b, k);
      if (c) return c;
    }
    return a.key < b.key ? -1 : a.key > b.key ? 1 : 0;
  });
}

// A value typed in the Record box: a number, or the reason it isn't one (or is
// outside a setting's allowed range).
export function checkValue(text, point) {
  const t = String(text ?? "").trim().replace(",", ".");
  if (t === "") return { error: "Type a value" };
  const v = Number(t);
  if (!Number.isFinite(v)) return { error: "Not a number" };
  if (point.uses !== undefined && point.position) return v > 0 ? { value: v } : { error: "The quantity must be more than 0" };
  if (isSetting(point)) {
    if (point.range_min != null && v < point.range_min) return { error: `Lowest allowed is ${withUnit(point.range_min, point.unit || "")}` };
    if (point.range_max != null && v > point.range_max) return { error: `Highest allowed is ${withUnit(point.range_max, point.unit || "")}` };
  }
  if (point.kind === "counter" && point.reading != null && v < point.reading) {
    return { error: `A counter only goes up: the last was ${withUnit(numberText(point.reading), point.unit || "")}` };
  }
  return { value: v };
}

// What the box says once saved: "✓ Saved", or for a setting "✓ Set to 28 °C".
export function savedText(point, value) {
  if (point.uses !== undefined && point.position) return `✓ Added ${qtyText(value, point.unit)}`;
  return isSetting(point) ? `✓ Set to ${withUnit(numberText(value), point.unit || "")}` : "✓ Saved";
}

// The row's ⋯ menu: Open, Record a reading… (a setting: Record a change…), Edit
// limits… (or Edit…), Move…, Retire…; a channel's Open and Edit bands….
export function rowMenu(r) {
  if (r.type === "consumable") {
    return [
      { id: "page", label: "Open" },
      { id: "use", label: "Record use…" },
      r.item.listing_id ? { id: "retire", label: "Retire…", danger: true }
        : { id: "retire", label: "Retire…", danger: true, disabled: true, reason: "Recorded by hand: it stays while it has additions" },
    ];
  }
  if (r.type === "channel") return [{ id: "page", label: "Open" }, { id: "bands", label: "Edit bands…" }];
  const p = r.item;
  const manual = p.source === "manual" && !p.derived;
  const record = isSetting(p) ? "Record a change…" : "Record a reading…";
  return [
    { id: "page", label: "Open" },
    manual ? { id: "record", label: record }
      : { id: "record", label: record, disabled: true, reason: p.derived ? "Worked out from a signal channel" : `Read by a feed${p.tag ? ` (${p.tag})` : ""}` },
    { id: "limits", label: p.kind === "condition" ? "Edit limits…" : "Edit…" },
    p.derived ? { id: "move", label: "Move…", disabled: true, reason: "Stays with its signal channel" }
      : !p.position?.id ? { id: "move", label: "Move…", disabled: true, reason: "An item's point travels with the item" }
        : { id: "move", label: "Move…" },
    p.derived ? { id: "retire", label: "Retire…", disabled: true, reason: "Stop watching the band on its channel instead", danger: true }
      : { id: "retire", label: "Retire…", danger: true },
  ];
}

// The rows shown, as CSV: every column in words, with the value and unit apart.
export function measurementsCsv(rows) {
  const head = ["Position", "Point", "Tag", "Kind", "Latest", "Unit", "When", "State", "Next due"];
  return toCsv([head, ...rows.map((r) => [
    r.place.name, r.name, r.tag, r.kind, r.value == null ? "" : Number(r.value), r.unit,
    r.when ? String(r.when).slice(0, 10) : "", r.state.label, r.due || "",
  ])]);
}
