// "Isolate" in the Explorer's tree (a row's menu: Isolate › with 1 level open,
// 2 levels open, 3 levels open, or everything open): one row becomes the top
// of the tree pane, and everything above it and beside it goes, so the tree
// shows only the part you're working on, opened exactly that many levels
// below the row (closed beyond), whatever the tree's own level is. Rows can
// still be opened and closed by hand after. The rest of the pane (the levels,
// the search, the Show only filters, the counts, the RCM rows) then works on
// that branch alone, because it's handed a display that holds only the branch.
//
// It lives in the address (?isolate=<id>&depth=1|2|3|all), so Back leaves it
// and a shared link opens isolated. It isn't remembered on this device. The
// old "Pin this branch" links (?pin=<id>) still work: isolated, with what's
// open left as it was (no depth), as a pin did.
//
// Pure functions (no React), tested in treeIsolate.test.js.

import { levelSet } from "./outlineTree.js";

// The RCM tab's rows that can be isolated: a function, a performance standard
// (and the "No standard" row), a functional failure, a failure mode, and the
// "Not under a functional failure" row. Not a reference row (a cause that
// lives on another position).
const RCM_TYPES = new Set(["fn", "std", "nostd", "fail", "mode", "unassigned"]);

// Can this row be isolated in this arrangement? Any position, any location,
// an item with something inside it (positions it carries), and the RCM tab's
// rows. Not the pane's own headings ("No home yet" and so on), and nothing in
// Flat.
export function canIsolate(row, mode) {
  if (!row || mode === "flat") return false;
  if (row.type === "pos" || row.type === "loc") return true;
  if (row.type === "item") return row.kids.length > 0;
  return RCM_TYPES.has(row.type);
}

// The row an address asks to isolate, if it can be isolated here: else null
// (not found, retired, deleted, or not a row this arrangement can isolate).
export function isolateKey(display, mode, key) {
  if (key == null || !display) return null;
  return canIsolate(display.rows.get(key), mode) ? key : null;
}

// The levels a branch opens to: 1, 2, 3, or "all" (everything open); null
// (an old ?pin= link, or no depth given) leaves what's open as it was.
export const DEPTHS = [1, 2, 3, "all"];
export const DEFAULT_DEPTH = 2;
export function parseDepth(raw) {
  if (raw === "all") return "all";
  const n = Number(raw);
  return [1, 2, 3].includes(n) ? n : null;
}
// "1 level open", "2 levels open", "everything open".
export function depthWords(depth, { open = true } = {}) {
  if (depth === "all") return open ? "everything open" : "everything";
  if (depth == null) return "";
  return `${depth} level${depth === 1 ? "" : "s"}${open ? " open" : ""}`;
}

// What the address asks for: {id, depth, legacy}. ?isolate= wins over an old
// ?pin= (legacy: true, no depth).
export function parseIsolate(params) {
  const id = params.get("isolate");
  if (id) return { id, depth: parseDepth(params.get("depth")), legacy: false };
  const pin = params.get("pin");
  if (pin) return { id: pin, depth: null, legacy: true };
  return { id: null, depth: null, legacy: false };
}

// The address with a branch isolated (key, depth), or with none (key null).
// An old ?pin= goes either way.
export function writeIsolate(q, key, depth = null) {
  q.delete("pin");
  if (key == null) {
    q.delete("isolate");
    q.delete("depth");
    return q;
  }
  q.set("isolate", key);
  if (depth == null) q.delete("depth");
  else q.set("depth", String(depth));
  return q;
}

// The row to isolate in this display, from the address's id: {key, pending}.
// On the Summary tab there are no RCM rows: a function, failure or mode
// isolated on the RCM tab isolates its position there (`rcmWhole`: the
// positions with their RCM, to find it), and the address keeps the row, so
// the RCM tab goes back to it. `waiting`: the RCM isn't read yet, so an id
// not found may still be one of its rows (pending: don't drop it yet).
export function resolveIsolate(display, mode, id, { rcmWhole = null, waiting = false } = {}) {
  if (id == null || !display) return { key: null, pending: false };
  const own = isolateKey(display, mode, id);
  if (own) return { key: own, pending: false };
  const r = rcmWhole?.rows.get(id);
  if (r && RCM_TYPES.has(r.type)) {
    const pos = isolateKey(display, mode, r.ref.position_id);
    if (pos) return { key: pos, pending: false };
  }
  return { key: null, pending: !!waiting };
}

// What's open once `root` is isolated `depth` levels deep: the rows inside the
// branch opened exactly that far below it (root itself counts as the first),
// closed beyond; open rows outside the branch kept, so leaving the branch
// shows the rest as it was. depth "all": everything inside it open.
export function isolateOpen(display, open, root, depth) {
  const top = display?.rows.get(root);
  if (!top) return new Set(open || []);
  const inside = new Set();
  const stack = [root];
  while (stack.length) {
    const k = stack.pop();
    const r = display.rows.get(k);
    if (!r) continue;
    inside.add(k);
    for (const c of r.kids) stack.push(c);
  }
  const next = new Set([...(open || [])].filter((k) => !inside.has(k)));
  for (const k of inside) {
    const r = display.rows.get(k);
    if (!r.kids.length) continue;
    if (depth === "all" || r.depth - top.depth < depth) next.add(k);
  }
  return next;
}

// The tree's own level that matches a depth (the ⋯ menu ticks it): the
// isolated row is level 1, so N levels open below it is level N + 1.
export const levelOfDepth = (depth) => (depth === "all" ? Infinity : depth + 1);

// Is `key` the row `root` or somewhere inside it?
export function inBranch(display, key, root) {
  let k = key;
  while (k != null) {
    if (k === root) return true;
    const r = display.rows.get(k);
    if (!r) return false;
    k = r.parent;
  }
  return false;
}

// The display with one branch only: `root` is the one top row, its depth 0
// (so "open to level n" counts from it), and everything inside it as before.
// Rows outside it aren't in it at all, so a search, a filter and the counts
// only see the branch. Its counts: positions, locations, items, and positions
// not analysed (RCM). `whole` keeps the display it came from (for the way up
// in the panel's heading). null when `root` isn't a row.
export function isolateDisplay(display, root) {
  const top = display?.rows.get(root);
  if (!top) return null;
  const base = top.depth;
  const rows = new Map();
  const n = { positions: 0, locations: 0, items: 0, notAnalysed: 0 };
  const stack = [root];
  while (stack.length) {
    const k = stack.pop();
    const r = display.rows.get(k);
    rows.set(k, { ...r, depth: r.depth - base, parent: k === root ? null : r.parent });
    if (r.type === "pos") {
      n.positions += 1;
      if (r.ref.not_analysed) n.notAnalysed += 1;
    } else if (r.type === "loc") n.locations += 1;
    else if (r.type === "item") n.items += 1;
    for (let i = r.kids.length - 1; i >= 0; i--) stack.push(r.kids[i]);
  }
  return { ...display, rows, roots: [root], ...n, isolated: root, whole: display };
}

// Does what's open match "open to level n" (counted from the display's top)?
// After isolating or leaving it, the ⋯ menu ticks a level only while it's true.
export function levelMatches(display, open, n) {
  const want = levelSet(display, n);
  for (const r of display.rows.values()) {
    if (!r.kids.length) continue;
    if (open.has(r.key) !== want.has(r.key)) return false;
  }
  return true;
}

// Would isolating `key` show the whole tree anyway (it's the tree's one top
// row)? Then it isolates nothing: the crumb shows everything, and the ⋯ menu
// doesn't count it as a change.
export function isolateCoversAll(whole, key) {
  return !!whole && key != null && whole.roots?.length === 1 && whole.roots[0] === key;
}

// What a click on a crumb in the panel's heading does while a branch is
// isolated: a crumb inside the branch is picked ("select"); one above it
// isolates that row instead ("isolate"), or, when it can't be isolated (one of
// the pane's own headings) or is the whole tree's one top row, shows
// everything with it picked ("show-all").
export function crumbAction(isolated, whole, mode, key) {
  if (!isolated || isolated.rows.has(key)) return "select";
  if (isolateCoversAll(whole, key)) return "show-all";
  return canIsolate(whole.rows.get(key), mode) ? "isolate" : "show-all";
}

// The isolated row's way down from the top of the whole tree, by name
// ("Plant › Line A › Pump A"): the tooltip on the notice, so a short or
// cut-off name still says where it is.
export function isolatePath(display, key) {
  const names = [];
  let k = key;
  while (k != null) {
    const r = display?.rows.get(k);
    if (!r) break;
    names.unshift(r.ref?.name || r.ref?.text || "(no name)");
    k = r.parent;
  }
  return names.join(" › ");
}
