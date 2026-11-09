// The RBD builder's layout by its own width, not the screen's: on a phone, on the RBD page, or in
// the Explorer's table area beside the tree (narrower than the screen), the same width lays it out
// the same way. Below NARROW the toolbar's settings (unit, kind, safety function) move into ⋯
// (#301), the minimap goes and the action's notice takes its own row; below TIGHT "+ Add block"
// says "+ Add". The widths match the phone breakpoints the page used (720 and 640 px screens, less
// the page's and the card's padding).
export const NARROW_BUILDER = 660;
export const TIGHT_BUILDER = 580;

// The classes for the builder at `width` px (" is-narrow is-tight", " is-narrow" or ""); none
// while it isn't measured (another tab on show).
export function builderWidthClass(width) {
  if (!width) return "";
  if (width < TIGHT_BUILDER) return " is-narrow is-tight";
  return width < NARROW_BUILDER ? " is-narrow" : "";
}
