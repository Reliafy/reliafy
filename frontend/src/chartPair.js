// How two charts share a box (components/model/ChartPair.jsx). A chart
// narrower than about 480 px is hard to read, so two sit side by side only
// where each gets that much; otherwise:
//
//   "stack"   both, one under the other: charts read together, and any pair
//             on a phone (the page scrolls there, so height is free)
//   "switch"  one at a time at full width, a switch above naming each:
//             alternatives in a tab that fits the screen
export const MIN_CHART = 480;
// The gap between the two (ChartPair.css: .chart-pair-cells).
export const PAIR_GAP = 14;

// ``width``: the box's width in px (null until measured: no layout yet);
// ``phone``: the page scrolls; ``together``: the two are read together.
export function pairLayout({ width, phone = false, together = false, min = MIN_CHART, gap = PAIR_GAP }) {
  if (phone) return "stack";
  if (width == null || !Number.isFinite(width)) return null;
  if (width >= 2 * min + gap) return "side";
  return together ? "stack" : "switch";
}

// The item a switch shows: the chosen one while it is still there, else the first.
export function shownItem(items, chosen) {
  const list = (items || []).filter(Boolean);
  return list.find((it) => it.id === chosen) || list[0] || null;
}
