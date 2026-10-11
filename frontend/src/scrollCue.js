// Sideways-scroll cues (#301): which edges of a scrolling strip hide content,
// and where to scroll so a chosen child is in view. Pure, so it's testable.

// A pixel of slack: browsers report fractional scroll positions at some zooms.
const SLACK = 1;

// { start, end }: true where content is hidden past that edge.
export function scrollEdges({ scrollLeft = 0, scrollWidth = 0, clientWidth = 0 } = {}) {
  const max = scrollWidth - clientWidth;
  if (max <= SLACK) return { start: false, end: false };
  return { start: scrollLeft > SLACK, end: scrollLeft < max - SLACK };
}

// The scrollLeft that brings [left, left + width) into view with `margin` to
// spare at each edge (room for the fade), or null when it's already in view.
export function scrollToReveal({ scrollLeft, clientWidth, scrollWidth }, { left, width }, margin = 0) {
  const max = Math.max(0, scrollWidth - clientWidth);
  const clamp = (x) => Math.min(max, Math.max(0, x));
  if (left - margin < scrollLeft) return clamp(left - margin);
  if (left + width + margin > scrollLeft + clientWidth) return clamp(left + width + margin - clientWidth);
  return null;
}

// The scrollLeft after an arrow press: most of a view's width, keeping a bit
// of what was showing so the reader keeps their place.
export function scrollStep({ scrollLeft, clientWidth, scrollWidth }, dir) {
  const max = Math.max(0, scrollWidth - clientWidth);
  const step = Math.max(40, Math.round(clientWidth * 0.7));
  return Math.min(max, Math.max(0, scrollLeft + (dir < 0 ? -step : step)));
}
