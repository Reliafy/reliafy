// The Explorer tree's options menu (the ⋯ in the tree pane's heading): Arrange
// by, the levels, Close everything and the Show only filters, behind one
// button. These helpers say what's changed from the usual view (so the button
// can show it and Reset can undo it), and how the arrow keys move in the menu.

export const DEFAULT_ARRANGEMENT = "positions";
export const DEFAULT_LEVEL = 2;

// The level a tree is shown at: the one chosen last, the usual one before
// anything is chosen, or null once rows were opened or closed one by one.
export function levelShown(levelBy, mode) {
  return Object.prototype.hasOwnProperty.call(levelBy, mode) ? levelBy[mode] : DEFAULT_LEVEL;
}

// What's not as usual, each with a short name: an arrangement other than
// Positions (offered only when `arrange` is), a level other than the usual one
// (when the levels are offered), and each Show only filter that's on.
// `chips`: the filters on that this tree offers.
export function changedFromUsual({ mode, arrange = true, level, levels = true, chips = [] }) {
  const out = [];
  if (arrange && mode !== DEFAULT_ARRANGEMENT) out.push({ id: "arrange", label: "Arrangement" });
  if (levels && typeof level === "number" && level !== DEFAULT_LEVEL) out.push({ id: "level", label: "Level" });
  for (const c of chips) out.push({ id: `chip:${c.id}`, label: c.label });
  return out;
}

// The words beside the count line when filters are on: "Showing only Overdue
// and Alarm". Empty when none are.
export function showingOnly(labels) {
  if (!labels.length) return "";
  const list = labels.length === 1 ? labels[0]
    : `${labels.slice(0, -1).join(", ")} and ${labels[labels.length - 1]}`;
  return `Showing only ${list}`;
}

// The arrow keys in a menu whose items sit in rows (a row of radios side by
// side, or one item alone). `rows`: the items' ids, row by row; `at`: the id
// with the focus (or null); `checked(id)`: is it the checked one in its row.
// ↑ ↓ go to the row before or after (round the ends), landing on its checked
// item, else its first; ← → move along a row (round its ends); Home and End
// go to the first and the last item. Returns the id to focus, or null when
// the key isn't one of these.
export function menuMove(rows, at, key, checked = () => false) {
  const live = rows.filter((r) => r.length);
  if (!live.length) return null;
  let ri = live.findIndex((r) => r.includes(at));
  const land = (row) => row.find((id) => checked(id)) ?? row[0];
  if (key === "Home") return live[0][0];
  if (key === "End") return live[live.length - 1][live[live.length - 1].length - 1];
  if (key === "ArrowDown" || key === "ArrowUp") {
    if (ri < 0) return key === "ArrowDown" ? land(live[0]) : land(live[live.length - 1]);
    ri = (ri + (key === "ArrowDown" ? 1 : -1) + live.length) % live.length;
    return land(live[ri]);
  }
  if (key === "ArrowRight" || key === "ArrowLeft") {
    if (ri < 0) return null;
    const row = live[ri];
    const i = row.indexOf(at);
    return row[(i + (key === "ArrowRight" ? 1 : -1) + row.length) % row.length];
  }
  return null;
}
