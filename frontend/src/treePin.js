// "Pin this branch" in the Explorer's tree: one row becomes the top of the
// tree pane, and everything above it and beside it goes, so the tree shows
// only the part you're working on. The rest of the pane (the levels, the
// search, the Show only filters, the counts, the RCM rows) then works on that
// branch alone, because it's handed a display that holds only the branch.
//
// The pin lives in the address (?pin=<id>), so Back un-pins and a shared link
// opens pinned. It isn't remembered on this device.
//
// Pure functions (no React), tested in treePin.test.js.

import { levelSet } from "./outlineTree.js";

// Can this row be pinned in this arrangement? Any position, any location, and
// an item with something inside it (positions it carries). Not the pane's own
// headings ("No home yet" and so on), not an RCM row, and nothing in Flat.
export function canPin(row, mode) {
  if (!row || mode === "flat") return false;
  if (row.type === "pos" || row.type === "loc") return true;
  if (row.type === "item") return row.kids.length > 0;
  return false;
}

// The row an address asks to pin, if it can be pinned here: else null (not
// found, retired, deleted, or not a row this arrangement can pin).
export function pinTarget(display, mode, key) {
  if (key == null || !display) return null;
  return canPin(display.rows.get(key), mode) ? key : null;
}

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
export function pinDisplay(display, root) {
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
  return { ...display, rows, roots: [root], ...n, pinned: root, whole: display };
}

// Does what's open match "open to level n" (counted from the display's top)?
// After pinning or un-pinning, the ⋯ menu ticks a level only while it's true.
export function levelMatches(display, open, n) {
  const want = levelSet(display, n);
  for (const r of display.rows.values()) {
    if (!r.kids.length) continue;
    if (open.has(r.key) !== want.has(r.key)) return false;
  }
  return true;
}

// What a click on a crumb in the panel's heading does while a branch is
// pinned: a crumb inside the branch is picked ("select"); one above it moves
// the pin up to it ("pin"), or, when it can't be pinned (one of the pane's own
// headings), shows the whole tree with it picked ("unpin").
export function crumbAction(pinned, whole, mode, key) {
  if (!pinned || pinned.rows.has(key)) return "select";
  return canPin(whole.rows.get(key), mode) ? "pin" : "unpin";
}
