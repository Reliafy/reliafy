// The asset tree pane's model (Operate › Assets › Positions and Locations): the
// same positions arranged by the positions tree, by where they are, or as one
// flat list; what's open; the filter that keeps the path to each match; the
// rows that are drawn (only those on screen are in the page); the ancestors
// pinned at the top while you scroll; and what's remembered on this device.
//
// Pure functions (no React), tested in assetTree.test.js. The rows come from
// GET /api/maintenance/tree: every position once, with parent_id, its own
// status (overdue, open_work, alarms, next_due) and where it is.

export const ARRANGEMENTS = [
  { value: "positions", label: "Positions", title: "What each position does, inside what" },
  { value: "locations", label: "Locations", title: "Where things are" },
  { value: "flat", label: "Flat", title: "Every position in one list, A to Z" },
];

// Which arrangement each menu entry opens on, and back.
export const ARRANGE_PATH = { positions: "/asset-register/positions", locations: "/asset-register/locations" };

// Natural A–Z: "Zone 2" before "Zone 10", case ignored.
const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
export const byName = (a, b) => collator.compare(a.name || "", b.name || "");

const blank = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null });

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
    const unhomed = (data?.unhomed || []).filter((it) => loose.has(it.id));
    if (homeless.length || unhomed.length) {
      add("G:nohome", "group", { name: "No home yet", note: "Not at a location and not fitted" });
      for (const p of homeless) addPosTree(p, "G:nohome", true);
      for (const it of unhomed.sort(byName)) addItem(it, "G:nohome", true);
    }
  } else if (mode === "flat") {
    for (const p of [...positions].sort(byName)) add(p.id, "pos", p, null);
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
  return { rows, roots, positions: positions.length };
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
    const own = { ...blank(), ...(r.ref.status || {}) };
    const sum = { ...own, positions: 0, empty: 0 };
    for (const k of r.kids) {
      const c = rows.get(k);
      const s = c.sum;
      sum.overdue += s.overdue;
      sum.open_work += s.open_work;
      sum.alarms += s.alarms;
      sum.positions += s.positions + (c.type === "pos" ? 1 : 0);
      sum.empty += s.empty + (c.type === "pos" && c.ref.position_class && !c.ref.item ? 1 : 0);
      if (s.next_due && (!sum.next_due || s.next_due < sum.next_due)) sum.next_due = s.next_due;
    }
    r.own = own;
    r.sum = sum;
  }
}

// The rows with something inside them, down to level n (1: only the tops
// open... n = Infinity: everything open). Level 1 shows the tops, closed.
export function levelSet(display, n, root = null) {
  const open = new Set();
  const base = root ? display.rows.get(root).depth + 1 : 0;
  for (const r of display.rows.values()) {
    if (r.kids.length && r.depth - base < n - 1) open.add(r.key);
  }
  return open;
}

// What a row's text is searched by: name, tag, the item's name and serial, class.
export function rowText(r) {
  const p = r.ref;
  return [p.name, p.tag, p.item?.name, p.item?.serial, p.serial, p.position_class]
    .filter(Boolean).join(" ").toLowerCase();
}

// The status filters, as chips.
export const CHIPS = [
  { id: "overdue", label: "Overdue", test: (r) => r.own.overdue > 0 },
  { id: "open", label: "Open work", test: (r) => r.own.open_work > 0 },
  { id: "alarm", label: "Alarm", test: (r) => r.own.alarms > 0 },
  { id: "empty", label: "Empty", title: "Positions with a class and nothing fitted", test: (r) => r.type === "pos" && !!r.ref.position_class && !r.ref.item },
];

// The filter: the rows that match the text and every chip that's on (and the
// extra test, if any), and every row on the way down to one (keep). null when
// nothing filters.
export function computeFilter(display, { query = "", chips = [], extra = null } = {}) {
  const q = query.trim().toLowerCase();
  const tests = CHIPS.filter((c) => chips.includes(c.id));
  if (!q && !tests.length && !extra) return null;
  const match = new Set();
  const keep = new Set();
  for (const r of display.rows.values()) {
    if (q && !rowText(r).includes(q)) continue;
    if (tests.length && !tests.every((c) => c.test(r))) continue;
    if (extra && !extra(r)) continue;
    match.add(r.key);
    let p = r.key;
    while (p != null && !keep.has(p)) {
      keep.add(p);
      p = display.rows.get(p).parent;
    }
  }
  return { match, keep };
}

// While filtering, the rows on the way down to a match start open.
export function filterOpen(filter) {
  return new Set([...filter.keep].filter((k) => !filter.match.has(k)));
}

// The rows in the order they're drawn: [{key, depth, pos, size}] (pos and size:
// its place among the siblings shown, for aria-posinset and aria-setsize), and
// each key's index. Under a match, everything inside it shows.
export function flatten(display, open, filter = null) {
  const list = [];
  const index = new Map();
  const walk = (keys, under) => {
    const vis = filter && !under ? keys.filter((k) => filter.keep.has(k)) : keys;
    let pos = 0;
    for (const k of vis) {
      const r = display.rows.get(k);
      index.set(k, list.length);
      list.push({ key: k, depth: r.depth, pos: ++pos, size: vis.length });
      if (r.kids.length && open.has(k)) walk(r.kids, under || (filter && filter.match.has(k)));
    }
  };
  walk(display.roots, false);
  return { list, index };
}

// The ancestors pinned at the top while scrolling (VS Code's sticky scroll):
// the rows the first row on screen sits inside, at most `max` (the top one and
// the nearest ones when there are more).
export function pinnedRows(display, list, index, scrollTop, rowHeight, max = 4) {
  if (scrollTop <= 2 || !list.length) return [];
  const top = Math.floor(scrollTop / rowHeight + 0.0001);
  let pins = [];
  for (let it = 0; it < 4; it++) {
    const i = Math.min(list.length - 1, top + pins.length);
    const chain = [];
    let p = display.rows.get(list[i].key).parent;
    while (p != null) {
      if (index.has(p)) chain.unshift(p);
      p = display.rows.get(p).parent;
    }
    pins = chain.filter((k) => index.get(k) < top + chain.length);
  }
  if (pins.length > max) pins = [pins[0], ...pins.slice(pins.length - max + 1)];
  return pins;
}

// The first rows drawn and the last (exclusive): what's on screen, plus a few.
export function windowOf(count, scrollTop, viewHeight, rowHeight, extra = 8) {
  const from = Math.max(0, Math.floor(scrollTop / rowHeight) - extra);
  const to = Math.min(count, Math.ceil((scrollTop + viewHeight) / rowHeight) + extra);
  return [from, to];
}

// Type-ahead: the next row (after `from`, wrapping) whose name starts with `prefix`.
export function findByPrefix(display, list, from, prefix) {
  const q = prefix.toLowerCase();
  for (let n = 1; n <= list.length; n++) {
    const v = list[(from + n) % list.length];
    if ((display.rows.get(v.key).ref.name || "").toLowerCase().startsWith(q)) return v.key;
  }
  return null;
}

// The keys of the rows a row sits inside, top first.
export function ancestorsOf(display, key) {
  const out = [];
  let p = display.rows.get(key)?.parent;
  while (p != null) {
    out.unshift(p);
    p = display.rows.get(p).parent;
  }
  return out;
}

const plural = (n, one, many = `${one}s`) => `${n.toLocaleString("en-AU")} ${n === 1 ? one : many}`;

// A row's markers, at most three: overdue (a count), open work (a count), and
// "!" for an alarm. A row with something inside it counts everything inside
// (and itself); `inside` says so. Each has the words for a screen reader.
export function markersOf(r) {
  const parent = r.kids.length > 0;
  const s = parent ? r.sum : r.own;
  const where = (own) => (!parent ? "" : own ? " here and inside" : " inside");
  const out = [];
  if (s.overdue) out.push({ kind: "overdue", text: String(s.overdue), label: `${plural(s.overdue, "overdue task")}${where(r.own.overdue)}` });
  if (s.open_work) out.push({ kind: "open", text: String(s.open_work), label: `${plural(s.open_work, "open work order")}${where(r.own.open_work)}` });
  if (s.alarms) out.push({ kind: "alarm", text: "!", label: `${plural(s.alarms, "reading")} past an alarm limit${where(r.own.alarms)}` });
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

// What's remembered on this device, per workspace: the rows open in each
// arrangement, the selection in each, the pane's width and whether it's
// folded to a rail. Storage can throw (private mode, blocked site data), so
// every read and write is guarded and the page works without it.
const KEY = (ws) => `reliafy.assetTree.${ws || "personal"}`;
export const PANE = { min: 220, initial: 320, rail: 44 };

export function loadTreeState(ws, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem(KEY(ws));
    const v = raw ? JSON.parse(raw) : {};
    return {
      open: Object.fromEntries(Object.entries(v.open || {}).map(([m, keys]) => [m, new Set(keys)])),
      selected: v.selected || {},
      width: Number.isFinite(v.width) ? v.width : PANE.initial,
      collapsed: !!v.collapsed,
    };
  } catch {
    return { open: {}, selected: {}, width: PANE.initial, collapsed: false };
  }
}

export function saveTreeState(ws, state, storage = globalThis.localStorage) {
  try {
    storage?.setItem(KEY(ws), JSON.stringify({
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
