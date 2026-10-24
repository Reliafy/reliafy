// The outline's model, shared by every tree drawn as an outline: the asset
// tree pane (assetTree.js) and the RCM study's worksheet (rcmWorksheet.js).
//
// A display is {rows, roots}: rows a Map of key → {key, parent, kids, depth,
// ref, ...}, roots the keys at the top. These pure functions (no React) open
// it to a level, filter it while keeping the path to each match, flatten what's
// open into the rows drawn, and work out which of those are on screen and
// which ancestors stay pinned at the top. Tested in outlineTree.test.js (and,
// through the asset tree, in assetTree.test.js).

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

// The deepest level in a display (1: only tops).
export function depthOf(display) {
  let max = 0;
  for (const r of display.rows.values()) max = Math.max(max, r.depth + 1);
  return max;
}

// The filter: the rows that pass `test`, and every row on the way down to one
// (keep). {match, keep}.
export function filterRows(display, test) {
  const match = new Set();
  const keep = new Set();
  const above = new Set(); // every row with a match somewhere inside it
  for (const r of display.rows.values()) {
    if (!test(r)) continue;
    match.add(r.key);
    let p = r.key;
    while (p != null && !keep.has(p)) {
      keep.add(p);
      p = display.rows.get(p).parent;
    }
    for (let up = r.parent; up != null && !above.has(up); up = display.rows.get(up).parent) above.add(up);
  }
  return { match, keep, above };
}

// While filtering, the rows on the way down to a match start open, a match
// with other matches inside it too.
export function filterOpen(filter) {
  if (filter.above) return new Set(filter.above);
  return new Set([...filter.keep].filter((k) => !filter.match.has(k)));
}

// The rows in the order they're drawn: [{key, depth, pos, size}] (pos and size:
// its place among the siblings shown, for aria-posinset and aria-setsize), and
// each key's index. Under a match, everything inside it shows. With `order`
// (a function of the sibling keys), the siblings are drawn in that order: a
// sort that keeps the tree.
export function flatten(display, open, filter = null, order = null) {
  const list = [];
  const index = new Map();
  const walk = (keys, under) => {
    let vis = filter && !under ? keys.filter((k) => filter.keep.has(k)) : keys;
    if (order) vis = order(vis);
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

const refName = (r) => r.ref.name;

// Type-ahead: the next row (after `from`, wrapping) whose name starts with `prefix`.
export function findByPrefix(display, list, from, prefix, nameOf = refName) {
  const q = prefix.toLowerCase();
  for (let n = 1; n <= list.length; n++) {
    const v = list[(from + n) % list.length];
    if ((nameOf(display.rows.get(v.key)) || "").toLowerCase().startsWith(q)) return v.key;
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

// After the open rows change (a level picked, a row closed), the row to keep
// picked: the picked one if it still shows, else the nearest row it's inside.
export function visiblePick(display, shownIndex, key) {
  let k = key;
  while (k != null && !shownIndex.has(k)) k = display.rows.get(k)?.parent ?? null;
  return k;
}
