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
