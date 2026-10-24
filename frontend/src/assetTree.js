// The asset tree pane's model (Operate › Assets › Explorer): the whole
// register arranged by the positions tree, by where things are, by item, or as
// one flat list of positions; what's open; the filter that keeps the path to
// each match; the rows that are drawn (only those on screen are in the page);
// the ancestors pinned at the top while you scroll; and what's remembered on
// this device.
//
// Pure functions (no React), tested in assetTree.test.js. The rows come from
// GET /api/maintenance/tree: every position once, with parent_id, its own
// status (overdue, open_work, alarms, next_due), where it is and the item
// fitted there; the locations; the items placed at one (spares); and the
// items neither fitted nor placed (unhomed). The Items arrangement can also
// take GET /api/maintenance/items, for each item's class, make and model.

import { EXPLORER_PATH } from "./navigation.js";
import { filterRows } from "./outlineTree.js";
import { RCM_CHIPS, isRcmRow, rcmRowText } from "./explorerRcm.js";

// The outline's own model (open to a level, flatten, pinned rows, the drawn
// window, type-ahead), shared with the RCM worksheet.
export {
  ancestorsOf, filterOpen, findByPrefix, flatten, levelSet, pinnedRows, windowOf,
} from "./outlineTree.js";

export const ARRANGEMENTS = [
  { value: "positions", label: "Positions", title: "What each position does, inside what", tree: "Positions" },
  { value: "locations", label: "Locations", title: "Where things are", tree: "Locations" },
  { value: "items", label: "Items", title: "Every item: fitted, spare, or with no home yet", tree: "Items" },
  { value: "flat", label: "Flat", title: "Every position in one list, A to Z", tree: "Positions, A to Z" },
];
const MODES = new Set(ARRANGEMENTS.map((a) => a.value));

// The arrangement an address asks for (?arrange=), else the one used last
// here, else Positions.
export function arrangementOf(param, remembered) {
  if (MODES.has(param)) return param;
  return MODES.has(remembered) ? remembered : "positions";
}

// The Explorer's address for an arrangement, with any other query
// ({sel, place}; empty values left out).
export function explorerPath(mode = "positions", extra = {}) {
  const q = new URLSearchParams({ arrange: mode });
  for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
  return `${EXPLORER_PATH}?${q}`;
}

// The row to keep picked when the arrangement changes, if any: a position
// stays itself (in Items, the item fitted there); an item stays itself (in
// Positions and Flat, the position it's fitted to); a location stays itself
// in Locations. null: nothing to carry over.
export function carryOver(row, to) {
  if (!row) return null;
  if (row.type === "pos") return to === "items" ? row.ref.item?.id ?? null : row.key;
  if (row.type === "item") {
    if (to === "items" || to === "locations") return row.key;
    return row.ref.fitted_to?.id ?? (to === "positions" ? row.key : null);
  }
  if (row.type === "loc") return to === "locations" ? row.key : null;
  return null;
}

// Natural A–Z: "Zone 2" before "Zone 10", case ignored.
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
export const byName = (a, b) => collator.compare(a.name || "", b.name || "");

const blank = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0 });

// The display tree for one arrangement: rows {key, type (pos | loc | item |
// group), ref, parent, kids, depth, own, sum} keyed by id, and the tops.
// Every position appears exactly once: one the arrangement has no place for
// (it shouldn't happen) goes in a last group rather than going missing.
export function buildDisplay(data, mode, itemList = null) {
  const rows = new Map();
  const roots = [];
  const add = (key, type, ref, parent = null) => {
    if (rows.has(key)) return null;
    const r = { key, type, ref, parent, kids: [], depth: 0 };
    rows.set(key, r);
    (parent == null ? roots : rows.get(parent).kids).push(key);
    return r;
  };
  const positions = data?.positions || [];
  const kidsOf = new Map();
  for (const p of positions) {
    const k = p.parent_id ?? null;
    if (!kidsOf.has(k)) kidsOf.set(k, []);
    kidsOf.get(k).push(p);
  }
  for (const list of kidsOf.values()) list.sort(byName);
  // A position and everything inside it; with skipPlaced, a child set at a
  // location of its own goes under that location instead.
  const addPosTree = (p, parent, skipPlaced) => {
    if (!add(p.id, "pos", p, parent)) return;
    for (const c of kidsOf.get(p.id) || []) {
      if (skipPlaced && c.location_id) continue;
      addPosTree(c, p.id, skipPlaced);
    }
  };
  // Positions an item carries while the item is fitted nowhere, by item.
  const loose = new Map();
  for (const p of kidsOf.get(null) || []) {
    if (!p.carried_by) continue;
    if (!loose.has(p.carried_by.id)) loose.set(p.carried_by.id, { item: p.carried_by, positions: [] });
    loose.get(p.carried_by.id).positions.push(p);
  }
  const tops = (kidsOf.get(null) || []).filter((p) => !p.carried_by);
  const addItem = (item, parent, skipPlaced) => {
    if (!add(item.id, "item", item, parent)) return;
    for (const p of loose.get(item.id)?.positions || []) {
      if (skipPlaced && p.location_id) continue;
      addPosTree(p, item.id, skipPlaced);
    }
  };

  if (mode === "locations") {
    const locs = data?.locations || [];
    const known = new Set(locs.map((l) => l.id));
    const locKids = new Map();
    for (const l of locs) {
      const k = known.has(l.parent_id) ? l.parent_id : null;
      if (!locKids.has(k)) locKids.set(k, []);
      locKids.get(k).push(l);
    }
    for (const list of locKids.values()) list.sort(byName);
    const placed = new Map();
    for (const p of positions) {
      if (!p.location_id || !known.has(p.location_id)) continue;
      if (!placed.has(p.location_id)) placed.set(p.location_id, []);
      placed.get(p.location_id).push(p);
    }
    for (const list of placed.values()) list.sort(byName);
    const spares = new Map();
    for (const it of data?.spares || []) {
      if (!spares.has(it.location_id)) spares.set(it.location_id, []);
      spares.get(it.location_id).push(it);
    }
    for (const list of spares.values()) list.sort(byName);
    const addLoc = (l, parent) => {
      if (!add(l.id, "loc", l, parent)) return;
      for (const p of placed.get(l.id) || []) addPosTree(p, l.id, true);
      for (const it of spares.get(l.id) || []) addItem(it, l.id, true);
      for (const c of locKids.get(l.id) || []) addLoc(c, l.id);
    };
    for (const l of locKids.get(null) || []) addLoc(l, null);
    const homeless = tops.filter((p) => !p.location_id);
    const unhomed = [...(data?.unhomed || [])];
    if (homeless.length || unhomed.length) {
      add("G:nohome", "group", { name: "No home yet", note: "Not at a location and not fitted" });
      for (const p of homeless) addPosTree(p, "G:nohome", true);
      for (const it of unhomed.sort(byName)) addItem(it, "G:nohome", true);
    }
  } else if (mode === "items") {
    addItems(data, itemList, add);
  } else if (mode === "flat") {
    for (const p of [...positions].sort(byName)) add(p.id, "pos", p, null);
  } else {
    for (const p of tops) addPosTree(p, null, false);
    if (loose.size) {
      add("G:loose", "group", { name: "On items fitted nowhere", note: "Positions an item carries, while the item isn't fitted" });
      for (const { item } of [...loose.values()].sort((a, b) => byName(a.item, b.item))) addItem(item, "G:loose", false);
    }
  }
  // Anything left over still shows, in one last group (Items lists items only).
  const missing = mode === "items" ? [] : positions.filter((p) => !rows.has(p.id));
  if (missing.length) {
    add("G:other", "group", { name: "Elsewhere", note: "Positions with no place in this arrangement" });
    for (const p of missing.sort(byName)) if (!rows.has(p.id)) add(p.id, "pos", p, "G:other");
  }
  rollUp(rows, roots);
  let items = 0;
  for (const r of rows.values()) items += r.type === "item";
  return { rows, roots, positions: positions.length, items };
}

// The Items arrangement: every item once, A to Z, in three groups: fitted to
// a position now, at a location and not fitted (spares, and things away from
// their positions), and neither (no home yet). Each item row carries what the
// detail panel says about it: serial, the position it's fitted to, where it
// is, and (from the items list, once loaded) its class, make and model.
const ITEM_GROUPS = [
  { key: "G:fitted", name: "Fitted", note: "Fitted to a position now" },
  { key: "G:placed", name: "At a location, not fitted", note: "Spares, and items away from their positions" },
  { key: "G:unhomed", name: "No home yet", note: "Not fitted and not at a location" },
];

function addItems(data, itemList, add) {
  const more = new Map((itemList || []).map((i) => [i.id, i]));
  const locName = new Map((data?.locations || []).map((l) => [l.id, l.name]));
  const extra = (id) => {
    const i = more.get(id);
    if (!i) return {};
    return {
      item_class: i.item_class || null, manufacturer: i.manufacturer_entry?.name || i.manufacturer || "",
      model: i.model || "", part_number: i.part_number || "",
    };
  };
  const groups = { "G:fitted": [], "G:placed": [], "G:unhomed": [] };
  const seen = new Set();
  const put = (group, ref) => {
    if (seen.has(ref.id)) return;
    seen.add(ref.id);
    groups[group].push({ ...ref, ...extra(ref.id) });
  };
  for (const p of data?.positions || []) {
    if (!p.item) continue;
    put("G:fitted", {
      id: p.item.id, name: p.item.name, serial: p.item.serial || "", status: p.item.status,
      fitted_to: { id: p.id, name: p.name }, place: p.location ? { id: p.location.id, name: p.location.name } : null,
    });
  }
  for (const it of data?.spares || []) {
    put("G:placed", { ...it, place: locName.has(it.location_id) ? { id: it.location_id, name: locName.get(it.location_id) } : null });
  }
  for (const it of data?.unhomed || []) put("G:unhomed", { ...it });
  // An item in the items list that the tree doesn't have yet (made a moment
  // ago): with no home, until the tree is read again.
  for (const i of more.values()) {
    if (!seen.has(i.id)) put(i.fitted_to ? "G:fitted" : i.location ? "G:placed" : "G:unhomed", {
      id: i.id, name: i.name, serial: i.serial || "", fitted_to: i.fitted_to || null,
      place: i.location ? { id: i.location.id, name: i.location.name } : null,
    });
  }
  for (const g of ITEM_GROUPS) {
    if (!groups[g.key].length) continue;
    add(g.key, "group", { name: g.name, note: g.note });
    for (const ref of groups[g.key].sort(byName)) add(ref.id, "item", ref, g.key);
  }
}

// Depth, and each row's totals: its own status plus everything inside it.
function rollUp(rows, roots) {
  const order = [];
  const stack = roots.map((k) => [k, 0]);
  while (stack.length) {
    const [key, depth] = stack.pop();
    const r = rows.get(key);
    r.depth = depth;
    order.push(r);
    for (const k of r.kids) stack.push([k, depth + 1]);
  }
  for (let i = order.length - 1; i >= 0; i--) {
    const r = order[i];
    // not_analysed: a position whose RCM isn't done (no function yet, or a
    // failure mode with no decision), from the tree's rows.
    const own = { ...blank(), ...(r.ref.status || {}), not_analysed: r.type === "pos" && r.ref.not_analysed ? 1 : 0 };
    const sum = { ...own, positions: 0, empty: 0 };
    for (const k of r.kids) {
      const c = rows.get(k);
      const s = c.sum;
      sum.overdue += s.overdue;
      sum.open_work += s.open_work;
      sum.alarms += s.alarms;
      sum.not_analysed += s.not_analysed;
      sum.positions += s.positions + (c.type === "pos" ? 1 : 0);
      sum.empty += s.empty + (c.type === "pos" && c.ref.position_class && !c.ref.item ? 1 : 0);
      if (s.next_due && (!sum.next_due || s.next_due < sum.next_due)) sum.next_due = s.next_due;
    }
    r.own = own;
    r.sum = sum;
  }
}

// What a row's text is searched by: name, tag, the item's name and serial,
// class; for an item, its serial, class, make, model and part number too.
export function rowText(r) {
  if (isRcmRow(r)) return rcmRowText(r);
  const p = r.ref;
  return [p.name, p.tag, p.item?.name, p.item?.serial, p.serial, p.position_class, p.item_class?.name,
    p.manufacturer, p.model, p.part_number]
    .filter(Boolean).join(" ").toLowerCase();
}

// The status filters, as chips.
export const CHIPS = [
  { id: "overdue", label: "Overdue", test: (r) => r.own.overdue > 0 },
  { id: "open", label: "Open work", test: (r) => r.own.open_work > 0 },
  { id: "alarm", label: "Alarm", test: (r) => r.own.alarms > 0 },
  { id: "empty", label: "Empty", title: "Positions with a class and nothing fitted", positionsOnly: true, test: (r) => r.type === "pos" && !!r.ref.position_class && !r.ref.item },
  { id: "unanalysed", label: "Not analysed", title: "Positions with no function yet, or a failure mode with no decision (RCM)", positionsOnly: true, test: (r) => r.own.not_analysed > 0 },
  // The RCM tab's own, about its failure modes (shown on that tab only).
  ...RCM_CHIPS,
];

// The filter: the rows that match the text and every chip that's on (and the
// extra test, if any), and every row on the way down to one (keep). null when
// nothing filters.
export function computeFilter(display, { query = "", chips = [], extra = null } = {}) {
  const q = query.trim().toLowerCase();
  const tests = CHIPS.filter((c) => chips.includes(c.id));
  if (!q && !tests.length && !extra) return null;
  return filterRows(display, (r) => (!q || rowText(r).includes(q))
    && (!tests.length || tests.every((c) => c.test(r)))
    && (!extra || extra(r)));
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// A row's markers, at most three: overdue (a count), open work (a count), and
// "!" for an alarm. A row with something inside it counts everything inside
// (and itself); `inside` says so. Each has the words for a screen reader.
// With `rcm` (the RCM tab open, or the Not analysed chip on), a quiet fourth:
// a position not analysed yet (a parent: how many, inside it and itself).
export function markersOf(r, { rcm = false } = {}) {
  if (isRcmRow(r)) return [];
  // Kids that are positions, locations or items (not the RCM tab's rows).
  const parent = r.kids.length - (r.rcmKids || 0) > 0;
  const s = parent ? r.sum : r.own;
  const where = (own) => (!parent ? "" : own ? " here and inside" : " inside");
  const out = [];
  if (s.overdue) out.push({ kind: "overdue", text: String(s.overdue), label: `${plural(s.overdue, "overdue task")}${where(r.own.overdue)}` });
  if (s.open_work) out.push({ kind: "open", text: String(s.open_work), label: `${plural(s.open_work, "open work order")}${where(r.own.open_work)}` });
  if (s.alarms) out.push({ kind: "alarm", text: "!", label: `${plural(s.alarms, "reading")} past an alarm limit${where(r.own.alarms)}` });
  if (rcm && s.not_analysed) {
    out.push({ kind: "rcm", text: parent ? String(s.not_analysed) : "○",
      label: parent ? `${plural(s.not_analysed, "position")} not analysed yet${where(r.own.not_analysed)}` : "Not analysed yet (RCM)" });
  }
  return out.map((m) => ({ ...m, inside: parent }));
}

// The status in words, for the detail panel: what's on the row itself, and
// what's inside it. [{kind, text}].
export function statusWords(r) {
  const out = [];
  const add = (kind, n, one, many, suffix) => n && out.push({ kind, text: `${plural(n, one, many)}${suffix}` });
  add("overdue", r.own.overdue, "overdue task", undefined, "");
  add("open", r.own.open_work, "open work order", undefined, "");
  add("alarm", r.own.alarms, "reading past an alarm limit", "readings past an alarm limit", "");
  if (r.kids.length) {
    const inner = {
      overdue: r.sum.overdue - r.own.overdue, open: r.sum.open_work - r.own.open_work, alarm: r.sum.alarms - r.own.alarms,
    };
    add("overdue", inner.overdue, "overdue", "overdue", " inside");
    add("open", inner.open, "open work order", undefined, " inside");
    add("alarm", inner.alarm, "alarm", undefined, " inside");
  }
  return out;
}

// "84 positions · 4 empty" for what's inside a row ("" for nothing).
export function insideWords(r) {
  if (!r.sum.positions) return "";
  return [plural(r.sum.positions, "position"), r.sum.empty ? `${r.sum.empty.toLocaleString("en-AU")} empty` : null]
    .filter(Boolean).join(" · ");
}

// What's remembered on this device, per workspace: the arrangement used last,
// the rows open in each arrangement, the selection in each, the pane's width
// and whether it's folded to a rail. Storage can throw (private mode, blocked site data), so
// every read and write is guarded and the page works without it.
const KEY = (ws) => `reliafy.assetTree.${ws || "personal"}`;
export const PANE = { min: 220, initial: 320, rail: 44 };

export function loadTreeState(ws, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(KEY(ws));
    const v = raw ? JSON.parse(raw) : {};
    return {
      mode: MODES.has(v.mode) ? v.mode : null,
      open: Object.fromEntries(Object.entries(v.open || {}).map(([m, keys]) => [m, new Set(keys)])),
      selected: v.selected || {},
      width: Number.isFinite(v.width) ? v.width : PANE.initial,
      collapsed: !!v.collapsed,
    };
  } catch {
    return { mode: null, open: {}, selected: {}, width: PANE.initial, collapsed: false };
  }
}

export function saveTreeState(ws, state, storage = globalThis.localStorage) {
  try {
    storage?.setItem(KEY(ws), JSON.stringify({
      mode: state.mode || null,
      open: Object.fromEntries(Object.entries(state.open || {}).map(([m, set]) => [m, [...set]])),
      selected: state.selected || {},
      width: state.width,
      collapsed: !!state.collapsed,
    }));
  } catch {
    // Not remembered on this device; the tree still works.
  }
}

// The pane's width, kept between the smallest and 60% of the window.
export function clampWidth(width, windowWidth) {
  const max = Math.max(PANE.min, Math.round(windowWidth * 0.6));
  return Math.min(max, Math.max(PANE.min, Math.round(width)));
}
