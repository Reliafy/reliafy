// The tabs of the Explorer's detail panel (Assets › Explorer, and a product's
// page, the Explorer on its design): what the panel beside the tree can show
// for the row picked. Summary for every kind of row; RCM for a position (its
// functions, how they fail, the failure modes and their decisions, read from
// the asset tree itself); Failure reports for a position, a location or an
// item (what has failed there and below, and what was done about it); Parts
// and stock (the parts used and kept there and inside it); Classes (the
// classes used there and inside it, and the whole taxonomy); Measurements for
// a position, a location or an item (every measuring point there and inside
// it: the latest reading, its limits and state, read by hand or fed); Packages for
// a position or a location (the work packages planned there and inside it:
// tasks done together on one visit, PackagesPanel); Signals for a
// position or an item (sensor snapshots and their spectra). A tab a kind
// doesn't have isn't shown (never greyed out).
//
// A product is a design, not an operated thing: its rows (a design's
// positions) have no maintenance done to them, so no Failure reports,
// Measurements, Signals or stock. They keep RCM and FME(C)A (the design's maintenance programme is a
// design output; the assets built from it carry it out), Classes, and "Parts"
// (the parts list, with no stock). Its layout's rows (the product's design
// locations, on its page's Locations) are no place you look after either: no
// Failure reports, Signals, or Parts and stock; the Summary gives the design
// facts (what's placed there).
//
// Parts and stock and Classes are hidden for now (EXPLORER_PARTS_CLASSES_TABS
// below): their entries, bodies (TreeDetail) and old addresses (redirects.js)
// stay, so one switch brings them back. Signals is the same
// (EXPLORER_SIGNALS_TAB).
//
// Adding a tab is one entry here (id, label, the kinds of row that have it,
// `asset: true` when a design's rows don't) and its body in TreeDetail. The
// address names the tab (?tab=rcm, left out for Summary); the tab picked stays
// as you walk the tree, shown on every row of a kind that has it, Summary on
// the others.

// Derryn, 8 Nov 2026: hidden for now, may come back. Off, `tabsFor` leaves out
// Parts and stock and Classes on every row (an asset's, a product's design),
// so a `?tab=parts` or `?tab=classes` address shows Summary, and the old pages'
// redirects (redirects.js) land on the Explorer with no tab.
export const EXPLORER_PARTS_CLASSES_TABS = false;

// Derryn, 8 Nov 2026: hidden for now. Off, `tabsFor` leaves out Signals on
// every row (positions, items, a product's design), so `?tab=signals` shows
// Summary. Channels are rows of the Measurements tab instead, beside the
// hand-read points; a channel's spectrum, bands and settings are on its own
// page (/asset-register/channels/:id, signals.js channelPath).
export const EXPLORER_SIGNALS_TAB = false;

const HIDDEN_WHEN_OFF = { parts: EXPLORER_PARTS_CLASSES_TABS, classes: EXPLORER_PARTS_CLASSES_TABS, signals: EXPLORER_SIGNALS_TAB };
const offered = (t) => HIDDEN_WHEN_OFF[t.id] !== false;

export const TABS = [
  { id: "summary", label: "Summary", title: "What it is, where it is, its work and what's inside it", kinds: ["pos", "loc", "item", "group"] },
  // A place has them too: they open on the top position at that place (the
  // RCM is by position, so the tree arranges by positions).
  { id: "rcm", label: "RCM", title: "What this position (or the positions at this place) does, how it can fail, and the decision for each failure mode", kinds: ["pos", "loc"] },
  { id: "fmea", label: "FME(C)A", title: "The failure modes here as an FMEA worksheet: cause, effects, scores, action priority and criticality", kinds: ["pos", "loc"] },
  { id: "reports", label: "Failure reports", title: "What has failed here and below, and what was done about it", kinds: ["pos", "loc", "item"], asset: true },
  {
    id: "parts", label: "Parts and stock", title: "The parts used here and inside it, and what's in stock where",
    designLabel: "Parts", designTitle: "The parts list: the parts used here and inside it", kinds: ["pos", "loc"],
    notDesignLoc: true,
  },
  { id: "classes", label: "Classes", title: "The classes used here and inside it, and every class in the register", kinds: ["pos", "loc"] },
  { id: "measurements", label: "Measurements", title: "Every measuring point here and inside it: the latest reading, its limits and whether it's past them", kinds: ["pos", "loc", "item"], asset: true },
  { id: "packages", label: "Packages", title: "Every task here and below in a table: search, sort and tick the ones done on one visit to package them", kinds: ["pos", "loc"], asset: true },
  { id: "signals", label: "Signals", title: "Vibration and other sensors that send snapshots: spectra, watch bands and how they change", kinds: ["pos", "item"], asset: true },
];
const BY_ID = new Map(TABS.filter(offered).map((t) => [t.id, t]));
export const DEFAULT_TAB = "summary";

// The tab the address asks for, if it's one (else Summary).
export function tabParam(value) {
  return BY_ID.has(value) ? value : DEFAULT_TAB;
}

// Is the row part of a product's design (its top position, marked `design`,
// a position inside it, marked `in_design` when the tree is scoped to the
// design: products.js scopeTree, or one of its design locations, `design_of`)?
export function isDesignRow(row) {
  if (row?.type === "loc") return !!(row.ref?.design_of || row.ref?.in_design);
  return row?.type === "pos" && !!(row.ref?.design || row.ref?.in_design);
}

// Is the row a product's top position (the product itself)?
export function isProductRow(row) {
  return row?.type === "pos" && !!row.ref?.design;
}

// The word over a picked row's name: what kind of row it is. A product's own
// row says "Product"; the positions of its design below it stay "Position".
export const ROW_KINDS = { pos: "Position", loc: "Location", item: "Item", group: "" };
export function rowKind(row) {
  if (row?.type === "loc" && isDesignRow(row)) return "Design location";
  return isProductRow(row) ? "Product" : ROW_KINDS[row?.type] || "";
}

// The tabs a row has (a design's rows with their own names where they differ).
export function tabsFor(row) {
  if (!row) return [];
  const design = isDesignRow(row);
  return TABS.filter((t) => offered(t) && t.kinds.includes(row.type) && !(design && t.asset) && !(design && row.type === "loc" && t.notDesignLoc))
    .map((t) => (design && t.designLabel ? { ...t, label: t.designLabel, title: t.designTitle || t.title } : t));
}

// The tab to show for a row: the one picked if the row has it, else Summary.
export function shownTab(wanted, row) {
  return tabsFor(row).some((t) => t.id === wanted) ? wanted : DEFAULT_TAB;
}

// Every row in a branch: the row's own key and everything inside it in the
// display tree, split by kind ({pos, loc, item}: Sets of keys). For the tabs
// that show a branch's parts and classes.
export function branchOf(display, key) {
  const out = { pos: new Set(), loc: new Set(), item: new Set() };
  if (!display?.rows?.has(key)) return out;
  const stack = [key];
  while (stack.length) {
    const r = display.rows.get(stack.pop());
    if (!r) continue;
    out[r.type]?.add(r.key);
    stack.push(...(r.kids || []));
  }
  return out;
}

// The parts at a branch: kept in stock at a location in it, or on the parts
// list of a position in it. A design's parts list has no stock (`design`).
export function partsInBranch(parts = [], branch, { design = false } = {}) {
  return parts.filter((pt) => (!design && (pt.stock || []).some((st) => branch.loc.has(st.location?.id)))
    || (pt.used_at || []).some((u) => branch.pos.has(u.position?.id)));
}

// The position classes used in a branch, with how many of its positions have
// each: [{position_class, here}], A–Z.
export function classesInBranch(display, branch) {
  const count = new Map();
  for (const k of branch.pos) {
    const c = display.rows.get(k)?.ref?.position_class;
    if (c) count.set(c, (count.get(c) || 0) + 1);
  }
  return [...count].map(([position_class, here]) => ({ position_class, here }))
    .sort((a, b) => a.position_class.localeCompare(b.position_class, "en", { numeric: true, sensitivity: "base" }));
}
