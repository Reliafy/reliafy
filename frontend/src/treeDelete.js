// Delete… on a position or a location in a tree: the words of its dialog and
// its toast, from the counts the server gives (a dry run of retire with
// cascade). A delete takes everything below the thing and never refuses; it
// never deletes an item (fitted ones are taken out and kept, stored ones lose
// their place); its history stays in the log, and Undo (restore with cascade)
// brings the whole branch back. Pure functions, tested in treeDelete.test.js.

// The tree's row types (treeRowMenu.js) to the server's kinds.
export const DELETE_KIND = { pos: "position", loc: "location" };

const n = (count, one, many = `${one}s`) => `${Number(count || 0).toLocaleString("en-AU")} ${count === 1 ? one : many}`;
const quoted = (s) => `“${String(s || "it").slice(0, 80)}”`;

// The positions to count in words: inside a position (not itself), or every
// one a location takes.
const positionsTaken = (c) => (c.kind === "position" ? c.positions_inside : c.positions) || 0;

// The dialog's title: "Delete “Propulsion” and everything inside it?" (just
// "Delete “Bearing”?" when nothing is inside).
export function deleteTitle(c) {
  const inside = positionsTaken(c) || c.locations_inside;
  return `Delete ${quoted(c.name)}${inside ? " and everything inside it" : ""}?`;
}

// What goes, one line each, in plain words (only the ones there are).
export function deleteLines(c) {
  const out = [];
  if (c.locations_inside) out.push(`${n(c.locations_inside, "location")} inside it`);
  const pos = positionsTaken(c);
  if (pos) out.push(c.kind === "location" ? `${n(pos, "position")} there, with everything inside them` : `${n(pos, "position")} inside it`);
  if (c.items_unfitted) {
    out.push(`${n(c.items_unfitted, "fitted item")} kept, unfitted: ${c.items_unfitted === 1 ? "it stays" : "they stay"} in Items`
      + (c.positions_on_unfitted_items ? ` (with the ${n(c.positions_on_unfitted_items, "position")} on ${c.items_unfitted === 1 ? "it" : "them"})` : ""));
  }
  if (c.tasks) out.push(`${n(c.tasks, "scheduled task")}: no longer scheduled`);
  if (c.open_work_orders) out.push(`${n(c.open_work_orders, "open work order")}: cancelled`);
  if (c.work_packages) out.push(`${n(c.work_packages, "work package")}: retired`);
  if (c.functions || c.failure_modes) {
    out.push([c.functions && n(c.functions, "function"), c.failure_modes && n(c.failure_modes, "failure mode")]
      .filter(Boolean).join(" and ") + " (its RCM)");
  }
  if (c.items_placed) out.push(`${n(c.items_placed, "item")} stored there kept, with no place now: ${c.items_placed === 1 ? "it stays" : "they stay"} in Items`);
  if (c.stock_lines) out.push(`Stock recorded there: kept`);
  return out;
}

// The one sentence under the list.
export const DELETE_NOTE = "Its history stays in the log: past fitments, work orders and failures still name it. "
  + "You can undo it straight after.";

// The confirm button: "Delete 13 positions", "Delete 3 locations and 4
// positions", "Delete the position".
export function deleteButton(c) {
  if (c.kind === "position") return c.positions > 1 ? `Delete ${n(c.positions, "position")}` : "Delete the position";
  const locs = c.locations > 1 ? n(c.locations, "location") : "the location";
  return `Delete ${locs}${c.positions ? ` and ${n(c.positions, "position")}` : ""}`;
}

// The toast after it's done: "Deleted Propulsion and 12 positions inside it."
export function deletedText(c) {
  const name = c.name || "it";
  const parts = [];
  if (c.locations_inside) parts.push(n(c.locations_inside, "location"));
  const pos = positionsTaken(c);
  if (pos) parts.push(n(pos, "position"));
  if (!parts.length) return `Deleted ${name}.`;
  const where = c.kind === "location" ? "in it" : "inside it";
  return parts.length === 1 ? `Deleted ${name} and ${parts[0]} ${where}.` : `Deleted ${name}, ${parts[0]} and ${parts[1]} ${where}.`;
}

// After Undo: what came back, and anything that had changed meanwhile.
export function undoneText(answer) {
  const name = answer?.name || "It";
  const skipped = answer?.skipped || [];
  return `Undone: ${name} and everything inside it are back.${skipped.length ? ` ${skipped.join(" ")}` : ""}`;
}

// Delete or Backspace on a focused row opens the dialog: not while typing, nor
// with a modifier (Cmd+Backspace and the like are the browser's).
export function isDeleteKey(e) {
  if (e.key !== "Delete" && e.key !== "Backspace") return false;
  if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return false;
  return !e.target?.closest?.("input, select, textarea, [contenteditable='true']");
}

// Ctrl+Z or Cmd+Z (no Shift: that's redo), not while typing.
export function isUndoKey(e) {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || String(e.key).toLowerCase() !== "z") return false;
  return !e.target?.closest?.("input, select, textarea, [contenteditable='true']");
}
