// Right-click everywhere in the Explorer, the product tree and the lists that lead to them: the
// app's menu, never the browser's, except in a field being typed in (copy and paste). Helpers for
// the fallbacks (TreePane's, RegisterList's, LibRows'); no React.

// A field being typed in keeps the browser's own menu.
export function isEditable(target) {
  return !!target?.closest?.("input, textarea, select, .sel-trigger, .sel-menu, [contenteditable='true']");
}

// The ⋯ of the row a right-click landed in, in a panel or a list (a table row, a list item, a
// row of cards): the row's menu opens from it. null when the row has none.
const ROWS = "tr, [role='row'], li, .rfs-row, .lib-row, .reg-row, .rw-row, .pk-row, .lsa-row, .mt-row, .rcm-ws-row";
export function panelRowMore(target) {
  const row = target?.closest?.(ROWS);
  if (!row) return null;
  const btn = row.querySelector(".more-btn:not([disabled]), .lib-more:not([disabled]), .rt-more:not([disabled])");
  return btn || null;
}
