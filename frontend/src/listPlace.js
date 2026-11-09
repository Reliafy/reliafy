// Where the list goes: under the input, or above it when there's more room there (a line near the
// foot of the screen), as wide as the input but at least 22rem, kept on the screen. Fixed to the
// viewport (the list is in a portal), so a scrolling table or the pane around it can't cut it off.
export function listPlace(rect, view) {
  const gap = 4, margin = 8;
  const below = view.height - rect.bottom - gap - margin;
  const above = rect.top - gap - margin;
  const up = below < 220 && above > below;
  const width = Math.min(Math.max(rect.width, 352), view.width - 2 * margin);
  const left = Math.max(margin, Math.min(rect.left, view.width - width - margin));
  return {
    left, width, maxHeight: Math.max(120, Math.min(288, up ? above : below)),
    ...(up ? { bottom: view.height - rect.top + gap } : { top: rect.bottom + gap }),
  };
}
