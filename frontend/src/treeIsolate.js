// "Isolate" in the Explorer's tree (a row's menu: Isolate › with 1 level open,
// 2 levels open, 3 levels open, or everything open): a one-off change to what's
// open, not a view. Every other branch of the tree closes (its rows stay on
// show, closed), the rows above the chosen one stay open so it's still in
// view, and the chosen row opens exactly that many levels below it (closed
// beyond). After that, rows open and close by hand as usual. Nothing is hidden
// or filtered and the address doesn't change (a pinned branch, treePin.js, is
// the way to show only one branch).
//
// Pure functions (no React), tested in treeIsolate.test.js.

// The RCM tab's rows that can be isolated as well as the tree's own: a
// function, a performance standard (and the "No standard" row), a functional
// failure and a failure mode. Not the "Not under a functional failure" heading
// (it has no menu), nor a reference row (a cause that lives on another position).
const RCM_TYPES = new Set(["fn", "std", "nostd", "fail", "mode"]);

// Can this row be isolated in this arrangement? Every row a branch can be
// pinned at (canPin: positions, locations, items with something inside), and
// the RCM tab's rows. Not the pane's own headings, and nothing in Flat.
export function canIsolate(row, mode, canPin) {
  if (!row || mode === "flat") return false;
  return canPin(row, mode) || RCM_TYPES.has(row.type);
}

export const DEPTHS = [1, 2, 3, "all"];

// "1 level", "2 levels", "every level".
export const depthWords = (depth) => (depth === "all" ? "every level" : `${depth} level${depth === 1 ? "" : "s"}`);

// What's open after isolating `key` `depth` levels deep (1, 2, 3 or "all") in
// `display` (the tree as drawn: a pinned branch, or the whole tree): the rows
// above it, and the rows inside it less than `depth` levels below it (the row
// itself counts as the first), and nothing else in the display. Rows that
// aren't in the display (outside a pinned branch) keep what they had.
export function isolateOpen(display, open, key, depth) {
  const top = display?.rows.get(key);
  const next = new Set([...(open || [])].filter((k) => !display?.rows.has(k)));
  if (!top) return new Set(open || []);
  for (let up = top.parent; up != null; up = display.rows.get(up)?.parent ?? null) next.add(up);
  const stack = [key];
  while (stack.length) {
    const r = display.rows.get(stack.pop());
    if (!r || !r.kids.length) continue;
    if (depth === "all" || r.depth - top.depth < depth) {
      next.add(r.key);
      stack.push(...r.kids);
    }
  }
  return next;
}
