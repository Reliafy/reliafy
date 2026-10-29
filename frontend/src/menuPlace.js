// Where a menu opened at a point goes, so it stays on screen (RowMenu).

export const EDGE = 8;

// A menu of size w×h opened at (x, y) in a viewport vw×vh: at the point, else
// flipped left or up, and never past the edges (EDGE px in from them).
export function placeMenu({ x, y }, { w, h }, { vw, vh }) {
  let left = x + w + EDGE > vw ? x - w : x;
  let top = y + h + EDGE > vh ? y - h : y;
  left = Math.max(EDGE, Math.min(left, vw - w - EDGE));
  top = Math.max(EDGE, Math.min(top, vh - h - EDGE));
  return { left: Math.round(left), top: Math.round(top) };
}

// A submenu of size w×h beside its item (the item's box `item`): to its
// right, overlapping the menu by 2 px, else to its left; its top level with
// the item's (less the menu's padding), moved up to stay on screen.
export function placeSubmenu(item, { w, h }, { vw, vh }) {
  let left = item.right + w + EDGE > vw ? item.left - w + 2 : item.right - 2;
  let top = item.top - 4;
  left = Math.max(EDGE, Math.min(left, vw - w - EDGE));
  top = Math.max(EDGE, Math.min(top, vh - h - EDGE));
  return { left: Math.round(left), top: Math.round(top) };
}
