// Operate › Assets: the assets are the top-level places (a house, a site, a
// plant), each counting what's anywhere inside it. Positions at no place stay
// reachable from one row at the end of the list, which opens the Explorer
// arranged by positions, filtered to them (AssetExplorer's ?place=none).

import { explorerPath } from "./assetTree.js";

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// Where the "Not at a place yet" row goes: the Explorer's positions, filtered.
export const NOT_PLACED_PATH = explorerPath("positions", { place: "none" });

// The Explorer arranged by positions, for "start with the positions".
export const POSITIONS_PATH = explorerPath("positions");

// A place's own page.
export const placePath = (id) => `/asset-register/locations/${id}`;

// Where an asset in the list goes: the Explorer, arranged by locations, with
// that place picked (opened to it) so you land in the tree.
export const assetPath = (id) => explorerPath("locations", { sel: id });

// The open work orders in a place's area (Maintenance, filtered by location).
export const openWorkPath = (id) => `/maintenance?location=${encodeURIComponent(id)}`;

// What's inside a place, in words: "4 places inside" ("" for none).
export function insideText(place) {
  return place?.locations ? `${plural(place.locations, "place")} inside` : "";
}

// What's due in the next horizon days (overdue included), in words: { text,
// overdue }. text: "Nothing due", "3 due, next 4 Nov 2026", or "3 due" when some
// are overdue (overdue: "1 overdue"; the next date would be a past one).
export function dueText(row, fmtDate = (d) => d) {
  if (!row?.due) return { text: "Nothing due", overdue: "" };
  if (row.overdue) return { text: `${row.due} due`, overdue: `${row.overdue} overdue` };
  return { text: `${row.due} due${row.next_due ? `, next ${fmtDate(row.next_due)}` : ""}`, overdue: "" };
}

// The list's summary line: "2 assets · 30 positions" (with the ones at no place).
export function assetsSummary(view) {
  if (!view) return "";
  const places = view.places || [];
  const placed = places.reduce((n, p) => n + (p.positions || 0), 0);
  const rest = view.not_placed?.positions || 0;
  return [plural(places.length, "asset"), plural(placed + rest, "position"),
    rest ? `${rest} not at a place yet` : null].filter(Boolean).join(" · ");
}
