// Which tabs of a row fit, for the shared Tabs with `overflow` (Tabs.jsx; the design system's
// components/Tabs.md). Priority+: the tabs that don't fit fold, from the right, into a last
// "⋯ N" tab. The selected tab is never folded: when it would be, it takes the last slot that
// shows and the tab it displaces goes into "⋯" instead. Order never changes otherwise.
//
//   widths    each tab's width in px, in row order
//   avail     the row's width in px
//   more      the "⋯ N" tab's width in px
//   selected  the selected tab's index (-1: none)
//   gap       the gap between tabs in px
//
// Returns {shown, hidden}: indices into `widths`, each in row order (`shown` with the selected
// tab last when it was moved in). Everything fits: hidden is empty and there's no "⋯".
export function fitTabs(widths, avail, more, selected = -1, gap = 0) {
  const n = widths.length;
  const all = [...Array(n).keys()];
  const span = (ix) => ix.reduce((s, i) => s + widths[i], 0) + gap * Math.max(0, ix.length - 1);
  if (!n || span(all) <= avail) return { shown: all, hidden: [] };
  // k tabs show, then "⋯": the first k, or the first k-1 and the selected one in the last slot.
  for (let k = n - 1; k >= 1; k--) {
    let shown = all.slice(0, k);
    if (selected >= k) shown = [...all.slice(0, k - 1), selected];
    if (span(shown) + gap + more <= avail) return { shown, hidden: all.filter((i) => !shown.includes(i)) };
  }
  // Not even one beside "⋯": the selected tab (or the first) alone, the rest in "⋯".
  const keep = selected >= 0 && selected < n ? selected : 0;
  return { shown: [keep], hidden: all.filter((i) => i !== keep) };
}

// The row's keyboard: the index the focus moves to along `count` stops (the tabs shown, then
// "⋯"), or null for a key that doesn't move it. ← → wrap; Home and End go to the ends.
export function nextStop(key, index, count) {
  if (!count) return null;
  if (key === "ArrowRight") return (index + 1) % count;
  if (key === "ArrowLeft") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}
