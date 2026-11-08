// The asset tree pane's model (Operate › Assets › Explorer): the whole
// register arranged by the positions tree or by where things are; what's open; the filter that keeps the path to
// each match; the rows that are drawn (only those on screen are in the page);
// the ancestors pinned at the top while you scroll; and what's remembered on
// this device.
//
// Pure functions (no React), tested in assetTree.test.js. The rows come from
// GET /api/maintenance/tree: every position once, with parent_id, its own
// status (overdue, open_work, alarms, next_due), where it is and the item
// fitted there; the locations; the items placed at one (spares); and the
// items neither fitted nor placed (unhomed). Items have their own page
// (/items); the tree shows an item only where it sits.

import { EXPLORER_PATH } from "./navigation.js";
import { filterRows } from "./outlineTree.js";
import { RCM_CHIPS, isRcmRow, rcmRowText } from "./explorerRcm.js";
import { CHIPS as FMEA_CHIPS } from "./fmeaWorksheet.js";
import { NOFAIL_HINT } from "./rcmWorksheet.js";

// The outline's own model (open to a level, flatten, pinned rows, the drawn
// window, type-ahead), shared with the RCM worksheet.
export {
  ancestorsOf, filterOpen, findByPrefix, flatten, levelSet, pinnedRows, windowOf,
} from "./outlineTree.js";

export const ARRANGEMENTS = [
  { value: "positions", label: "Positions", title: "What each position does, inside what", tree: "Positions" },
  { value: "locations", label: "Locations", title: "Where things are", tree: "Locations" },
];
const MODES = new Set(ARRANGEMENTS.map((a) => a.value));

// Arrangements the Explorer once had (Items, Flat): an old address or a
// saved state asking for one opens by positions.
const RETIRED = new Set(["items", "flat"]);

// The arrangement an address asks for (?arrange=), else the one used last
// here, else Positions.
export function arrangementOf(param, remembered) {
  if (MODES.has(param)) return param;
  if (RETIRED.has(param)) return "positions";
  return MODES.has(remembered) ? remembered : "positions";
}

// The arrangement the Explorer shows: by positions on the RCM and FME(C)A
// tabs (they're by position); one tree on show (`scoped`: a product's page, an
// item's tree) by positions unless its address says Locations (its own layout,
// never the arrangement remembered for the whole register); else as
// arrangementOf.
export function arrangementFor({ param = null, remembered = null, rcm = false, scoped = false } = {}) {
  if (rcm) return "positions";
  if (scoped) return param === "locations" ? "locations" : "positions";
  return arrangementOf(param, remembered);
}

// One tree's address for an arrangement (a product's page leaves Positions
// out of it: that's how it opens), without a pin from the other arrangement.
export function scopedArrangeQuery(params, mode, { ownPage = false } = {}) {
  const q = new URLSearchParams(params);
  if (ownPage && mode === "positions") q.delete("arrange");
  else q.set("arrange", mode);
  q.delete("pin");
  return q;
}

// The Explorer's address for an arrangement, with any other query
// ({sel, place}; empty values left out).
export function explorerPath(mode = "positions", extra = {}) {
  const q = new URLSearchParams({ arrange: mode });
  for (const [k, v] of Object.entries(extra)) if (v) q.set(k, v);
  return `${EXPLORER_PATH}?${q}`;
}

// The row to keep picked when the arrangement changes, if any: a position
// stays itself; an item stays itself (in Positions, the position it's fitted
// to, if any); a location stays itself in Locations. null: nothing to carry
// over.
export function carryOver(row, to, ctx = null) {
  if (!row) return null;
  if (row.type === "pos") return row.key;
  if (row.type === "item") return to === "locations" ? row.key : row.ref.fitted_to?.id ?? row.key;
  if (row.type === "loc") {
    if (to === "locations") return row.key;
    // To Positions (the RCM and FME(C)A tabs live there): the position whose
    // tree holds everything at this place, so its RCM opens.
    if (to === "positions" && ctx?.display && ctx?.positions) return mainPositionAt(row, ctx.display, ctx.positions);
    return null;
  }
  return null;
}

// The position to open for a place: the lowest position above every position
// at the place and the places inside it (the Locations arrangement nests them
// under the place's row); with no common one (two trees share the place),
// the root with the most of them, A–Z between equals. Null with none there.
export function mainPositionAt(locRow, display, positions) {
  const here = [];
  const stack = [...(locRow?.kids || [])];
  while (stack.length) {
    const r = display.rows.get(stack.pop());
    if (!r) continue;
    if (r.type === "pos") here.push(r.key);
    stack.push(...r.kids);
  }
  if (!here.length) return null;
  const byId = new Map((positions || []).map((p) => [p.id, p]));
  const up = (id) => { const out = []; for (let k = id; k != null; k = byId.get(k)?.parent_id ?? null) out.push(k); return out; };
  const chains = here.map(up);
  let common = chains[0];
  for (const c of chains.slice(1)) { const s = new Set(c); common = common.filter((k) => s.has(k)); }
  if (common.length) return common[0];
  const count = new Map();
  for (const c of chains) count.set(c.at(-1), (count.get(c.at(-1)) || 0) + 1);
  const roots = [...count.keys()].map((id) => byId.get(id) || { id, name: "" });
  roots.sort((a, b) => count.get(b.id) - count.get(a.id) || byName(a, b));
  return roots[0].id;
}

// Natural A–Z: "Zone 2" before "Zone 10", case ignored.
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
export const byName = (a, b) => collator.compare(a.name || "", b.name || "");

// A row's own status: its overdue tasks, open work orders, readings past an
// alarm limit, open failure reports (the Failure reports tab), and its next due.
const blank = () => ({ overdue: 0, open_work: 0, alarms: 0, open_reports: 0, next_due: null, not_analysed: 0 });

// The last group in Locations: what's at no location. On a product's page,
// the positions not placed in its layout yet; on an item's tree, those not
// placed on the item (they're where the item is kept).
export const NO_HOME = {
  assets: { name: "No home yet", note: "Not at a location and not fitted" },
  design: { name: "Not placed in the layout", note: "Positions not placed at one of the product's locations yet (the ones inside a placed position are where it is)" },
  unit: { name: "Not placed on the item", note: "Positions not placed at one of the item's own locations: they're where the item is kept" },
};

// The display tree for one arrangement: rows {key, type (pos | loc | item |
// group), ref, parent, kids, depth, own, sum} keyed by id, and the tops.
// Every position appears exactly once: one the arrangement has no place for
// (it shouldn't happen) goes in a last group rather than going missing.
export function buildDisplay(data, mode) {
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
  // In Locations, a position goes under its location when that's one on show
  // (a product's page shows only its design's locations: a position set at a
  // place outside it is where its parent is there).
  const known = new Set(mode === "locations" ? (data?.locations || []).map((l) => l.id) : []);
  const placedHere = (p) => !!p.location_id && known.has(p.location_id);
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
      if (skipPlaced && placedHere(c)) continue;
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
      if (skipPlaced && placedHere(p)) continue;
      addPosTree(p, item.id, skipPlaced);
    }
  };

  if (mode === "locations") {
    const locs = data?.locations || [];
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
    const homeless = tops.filter((p) => !placedHere(p));
    const unhomed = data?.scope ? [] : [...(data?.unhomed || [])];
    if (homeless.length || unhomed.length) {
      add("G:nohome", "group", NO_HOME[data?.scope?.kind] || NO_HOME.assets);
      for (const p of homeless) addPosTree(p, "G:nohome", true);
      for (const it of unhomed.sort(byName)) addItem(it, "G:nohome", true);
    }
  } else {
    for (const p of tops) addPosTree(p, null, false);
    if (loose.size) {
      add("G:loose", "group", { name: "On items fitted nowhere", note: "Positions an item carries, while the item isn't fitted" });
      for (const { item } of [...loose.values()].sort((a, b) => byName(a.item, b.item))) addItem(item, "G:loose", false);
    }
  }
  // Anything left over still shows, in one last group.
  const missing = positions.filter((p) => !rows.has(p.id));
  if (missing.length) {
    add("G:other", "group", { name: "Elsewhere", note: "Positions with no place in this arrangement" });
    for (const p of missing.sort(byName)) if (!rows.has(p.id)) add(p.id, "pos", p, "G:other");
  }
  rollUp(rows, roots);
  let items = 0;
  for (const r of rows.values()) items += r.type === "item";
  return { rows, roots, positions: positions.length, items };
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
    // not_analysed: a position whose RCM isn't finished (ANALYSED_RULE), from
    // the tree's rows (the server decides it); a parent's sum counts it and
    // every position inside it.
    const own = { ...blank(), ...(r.ref.status || {}), not_analysed: r.type === "pos" && r.ref.not_analysed ? 1 : 0 };
    const sum = { ...own, positions: 0, empty: 0 };
    for (const k of r.kids) {
      const c = rows.get(k);
      const s = c.sum;
      sum.overdue += s.overdue;
      sum.open_work += s.open_work;
      sum.alarms += s.alarms;
      sum.open_reports += s.open_reports;
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

// What "analysed" means (RCM), in plain words: the Not analysed chip's
// tooltip. The server applies the same rule (Maintenance._analysed) to every
// position, so the tree's marks, the chip, the counts and a parent's roll-up
// all agree.
export const ANALYSED_RULE = "Not analysed: positions whose RCM isn't finished. A position is analysed when it has at least "
  + "one function, every function has a functional failure, every functional failure has failure modes or is "
  + "caused by other failures on its tree that are answered in turn, and every failure mode has a decision. "
  + "A position with no functions of its own is not analysed.";

// The status filters, as chips.
export const CHIPS = [
  { id: "overdue", label: "Overdue", test: (r) => r.own.overdue > 0 },
  { id: "open", label: "Open work", test: (r) => r.own.open_work > 0 },
  { id: "alarm", label: "Alarm", test: (r) => r.own.alarms > 0 },
  { id: "reports", label: "Open reports", title: "Positions with an open failure report", test: (r) => r.own.open_reports > 0 },
  { id: "empty", label: "Empty", title: "Positions with a class and nothing fitted", test: (r) => r.type === "pos" && !!r.ref.position_class && !r.ref.item },
  { id: "unanalysed", label: "Not analysed", title: ANALYSED_RULE, test: (r) => r.own.not_analysed > 0 },
  // The RCM tab's own, about its failure modes (shown on that tab only), and
  // the FME(C)A tab's (on that tab only).
  ...RCM_CHIPS,
  ...FMEA_CHIPS,
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

// Derryn, 8 Nov 2026: hidden for now, may come back. False: the tree rows draw
// no status markers (overdue, open work, alarm, open reports, not analysed,
// the RCM hints, the grey inside-count) and the tree's ⋯ menu drops its key to
// them. markersOf still works and the Show only filters and their counts are
// untouched; turning this on again is this one line.
export const TREE_ROW_MARKERS = false;

// A row's markers, each only when there's something to mark: overdue (a
// count), open work (a count), "!" for an alarm, and open failure reports (a
// count; the Failure reports tab). A row with something inside it counts
// everything inside (and itself); `inside` says so. Each has the words for a
// screen reader. With `rcm` (the RCM tab open, or the Not analysed chip on),
// a quiet one more: a position not analysed yet (a parent: how many, inside
// it and itself).
export function markersOf(r, { rcm = false } = {}) {
  if (r.type === "std" && isRcmRow(r)) {
    // On the RCM tab: a standard of the list with no functional failure yet.
    // Quiet, in words: a hint for the reader, never a gate (the position's
    // "analysed" doesn't rest on it).
    return r.ref.no_failure
      ? [{ kind: "nofail", text: "no failure yet", label: "No functional failure written yet for this performance standard" }] : [];
  }
  if (r.type === "nofail") {
    // On the RCM tab: failure modes directly under a function (written on the
    // FME(C)A tab). Quiet, in words: how to finish the RCM there.
    return [{ kind: "nofail", text: "finish the RCM", label: NOFAIL_HINT }];
  }
  if (r.type === "fail" && isRcmRow(r)) {
    // On the RCM tab: a functional failure that causes ones above it. Quiet
    // (no colour of its own); its text names them, and clicking it goes up.
    const up = (r.ref.effects || []).filter((e) => e.inside !== false);
    if (!up.length) return [];
    const names = up.map((e) => `${e.text} (on ${e.position?.name || "another position"})`).join("; ");
    return [{ kind: "up", text: `↑ ${up.length}`, label: `Causes: ${names}`, effect: up[0].id }];
  }
  if (isRcmRow(r)) return [];
  // Kids that are positions, locations or items (not the RCM tab's rows).
  const parent = r.kids.length - (r.rcmKids || 0) > 0;
  const s = parent ? r.sum : r.own;
  const where = (own) => (!parent ? "" : own ? " here and inside" : " inside");
  const out = [];
  if (s.overdue) out.push({ kind: "overdue", text: String(s.overdue), label: `${plural(s.overdue, "overdue task")}${where(r.own.overdue)}` });
  if (s.open_work) out.push({ kind: "open", text: String(s.open_work), label: `${plural(s.open_work, "open work order")}${where(r.own.open_work)}` });
  if (s.alarms) out.push({ kind: "alarm", text: "!", label: `${plural(s.alarms, "reading")} past an alarm limit${where(r.own.alarms)}` });
  if (s.open_reports) out.push({ kind: "report", text: String(s.open_reports), label: `${plural(s.open_reports, "open failure report")}${where(r.own.open_reports)}` });
  if (rcm && s.not_analysed) {
    out.push({ kind: "rcm", text: parent ? String(s.not_analysed) : "○",
      label: parent ? `${plural(s.not_analysed, "position")} not analysed yet${where(r.own.not_analysed)}` : "Not analysed yet (RCM)" });
  }
  return out.map((m) => ({ ...m, inside: parent }));
}

// The markers' key: each Show only filter in the tree's ⋯ menu shows the
// marker it matches (markersOf's kinds), so the red and blue counts are
// explained without hovering over every one.
export const CHIP_MARK = {
  overdue: { kind: "overdue", text: "3" },
  open: { kind: "open", text: "3" },
  alarm: { kind: "alarm", text: "!" },
  reports: { kind: "report", text: "3" },
  unanalysed: { kind: "rcm", text: "○" },
};

// The status in words, for the detail panel: what's on the row itself, and
// what's inside it. [{kind, text}].
export function statusWords(r) {
  const out = [];
  const add = (kind, n, one, many, suffix) => n && out.push({ kind, text: `${plural(n, one, many)}${suffix}` });
  add("overdue", r.own.overdue, "overdue task", undefined, "");
  add("open", r.own.open_work, "open work order", undefined, "");
  add("alarm", r.own.alarms, "reading past an alarm limit", "readings past an alarm limit", "");
  add("report", r.own.open_reports, "open failure report", undefined, "");
  if (r.kids.length) {
    const inner = {
      overdue: r.sum.overdue - r.own.overdue, open: r.sum.open_work - r.own.open_work, alarm: r.sum.alarms - r.own.alarms,
      report: r.sum.open_reports - r.own.open_reports,
    };
    add("overdue", inner.overdue, "overdue", "overdue", " inside");
    add("open", inner.open, "open work order", undefined, " inside");
    add("alarm", inner.alarm, "alarm", undefined, " inside");
    add("report", inner.report, "open failure report", undefined, " inside");
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
      // Whether the width is one the user dragged to (else the RCM tab fits its tree column to
      // the rows on show, fitTreeWidth). Before Nov 2026 every width was kept: the starting one
      // wasn't chosen.
      widthSet: typeof v.widthSet === "boolean" ? v.widthSet : Number.isFinite(v.width) && v.width !== PANE.initial,
      collapsed: !!v.collapsed,
    };
  } catch {
    return { mode: null, open: {}, selected: {}, width: PANE.initial, widthSet: false, collapsed: false };
  }
}

export function saveTreeState(ws, state, storage = globalThis.localStorage) {
  try {
    storage?.setItem(KEY(ws), JSON.stringify({
      mode: state.mode || null,
      open: Object.fromEntries(Object.entries(state.open || {}).map(([m, set]) => [m, [...set]])),
      selected: state.selected || {},
      width: state.width,
      widthSet: !!state.widthSet,
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

// The RCM (and FME(C)A) tab's tree column until the user drags it: wide enough for
// the longest name among the rows on show (its indent, arrow, icon and markers too),
// at least the usual width and at most TREE_FIT.cap or TREE_FIT.share of the window,
// so the worksheet's columns keep their room. Names are measured at TREE_FIT.charPx a
// character (the 13px font's average). A window narrower than TREE_FIT.from (a 1280 px
// laptop, where the table already folds its Interval column: explorerRcm.js NARROW_TABLE)
// keeps the usual width, so the columns keep theirs. rows: [{depth, text}].
export const TREE_FIT = { charPx: 7, extraPx: 72, cap: 600, share: 0.36, from: 1400 };
export function fitTreeWidth(rows, windowWidth) {
  if (!(windowWidth >= TREE_FIT.from)) return PANE.initial;
  let need = 0;
  for (const r of rows || []) {
    const w = Math.min(r.depth || 0, 30) * 14 + String(r.text || "").length * TREE_FIT.charPx + TREE_FIT.extraPx;
    if (w > need) need = w;
  }
  const max = Math.max(PANE.initial, Math.min(TREE_FIT.cap, Math.round((windowWidth || 0) * TREE_FIT.share)));
  return Math.max(PANE.initial, Math.min(max, Math.ceil(need)));
}

// The Summary tab's scroll area keeps room for the scrollbar (its width is the
// tree's plus this gutter) so rows never narrow when the bar comes and goes.
// The gutter measured after each render is taken only when it is wider than
// the one kept, so it settles: a measure that changes with the width it sets
// can't keep the page re-rendering.
export const nextGutter = (kept, measured) => (Number.isFinite(measured) && measured > kept ? measured : kept);
