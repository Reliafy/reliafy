// The RBD builder's layout by its own width, not the screen's: on a phone, on the RBD page, or in
// the Explorer's table area beside the tree (narrower than the screen), the same width lays it out
// the same way. Below NARROW the toolbar's settings (unit, kind, safety function) move into ⋯
// (#301), the minimap goes and the action's notice takes its own row; below TIGHT "+ Add block"
// is just "+". The widths match the phone breakpoints the page used (720 and 640 px screens, less
// the page's and the card's padding). The toolbar stays one row; as space runs short: below
// NARROW "+ Add block" is the "+" alone; below TIGHT Full screen moves into ⋯ and the save status
// and the check show their icon alone; below CRAMPED, Undo and Redo move into ⋯ too.
export const NARROW_BUILDER = 660;
export const TIGHT_BUILDER = 580;
export const CRAMPED_BUILDER = 400;

// The classes for the builder at `width` px (" is-narrow is-tight is-cramped", " is-narrow is-tight", " is-narrow" or ""); none
// while it isn't measured (another tab on show).
export function builderWidthClass(width) {
  if (!width) return "";
  if (width < CRAMPED_BUILDER) return " is-narrow is-tight is-cramped";
  if (width < TIGHT_BUILDER) return " is-narrow is-tight";
  return width < NARROW_BUILDER ? " is-narrow" : "";
}
