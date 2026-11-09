// "Isolate" in the Explorer's tree (a row's menu: Focus › with 1 level open,
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
// failure, a failure mode and a task. Not the "Not under a functional failure" heading
// (it has no menu), nor a reference row (a cause that lives on another position).
const RCM_TYPES = new Set(["fn", "std", "nostd", "fail", "mode", "task"]);

// Can this row be isolated in this arrangement? Every row a branch can be
// pinned at (canPin: positions, locations, items with something inside), and
// the RCM tab's rows. Not the pane's own headings.
export function canIsolate(row, mode, canPin) {
  if (!row) return false;
  return canPin(row, mode) || RCM_TYPES.has(row.type);
}

export const DEPTHS = [1, 2, 3, "all"];

// How many levels can be opened below a row: 0 for a row with nothing inside,
// 1 when only its own kids show, and so on (a position on the RCM tab goes down
// through functions, standards, functional failures and failure modes to their
// tasks). The isolate menu offers a fourth and a fifth level only where they exist.
export function levelsBelow(display, key) {
  const r = display?.rows.get(key);
  if (!r || !r.kids.length) return 0;
  let most = 0;
  for (const k of r.kids) most = Math.max(most, levelsBelow(display, k));
  return most + 1;
}

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

// ---- "Focus on incomplete rows" (the RCM tab's rows menu) -------------------------
// Opens the way to the RCM work still to finish under a row, and closes the
// rest: a function with no functional failure, a functional failure with no
// failure mode or cause, a failure mode still without a decision, and the two
// holding rows (modes with no functional failure yet, and modes not under one).
// A function's functional failures sit under it directly or under a standard.
const hasFailure = (display, r) => r.kids.some((k) => {
  const c = display.rows.get(k);
  return c?.type === "fail" || c?.type === "nofail" || ((c?.type === "std" || c?.type === "nostd") && c.kids.some((f) => display.rows.get(f)?.type === "fail"));
});
export function isIncompleteRcm(display, r) {
  if (!r) return false;
  if (r.type === "fn") return !hasFailure(display, r);
  if (r.type === "fail") return !r.kids.length;
  if (r.type === "mode") return !r.ref.decision;
  return r.type === "nofail" || r.type === "unassigned";
}

// The rows under `key` (and it) that are incomplete, in tree order.
export function incompleteRows(display, key) {
  const out = [];
  const stack = [key];
  while (stack.length) {
    const r = display?.rows.get(stack.pop());
    if (!r) continue;
    if (isIncompleteRcm(display, r)) out.push(r);
    stack.push(...[...r.kids].reverse());
  }
  return out;
}

// What's open after isolating the incomplete rows under `key`: the rows above
// it and the rows leading to each incomplete row, nothing else in the display.
// {open, rows}: `rows` is the incomplete ones found.
export function isolateIncompleteOpen(display, open, key) {
  const rows = incompleteRows(display, key);
  const next = new Set([...(open || [])].filter((k) => !display?.rows.has(k)));
  const up = (k) => { for (let p = display.rows.get(k)?.parent; p != null; p = display.rows.get(p)?.parent ?? null) next.add(p); };
  up(key);
  for (const r of rows) up(r.key);
  return { open: next, rows };
}

// The menu entry, on an RCM-tab row that has something inside it (or is itself
// the thing to finish).
export function isolateIncompleteItem(r, { can } = {}) {
  if (!r || !can || !r.kids?.length) return [];
  return [{ id: "isolate-incomplete", label: "Focus on incomplete rows" }];
}
