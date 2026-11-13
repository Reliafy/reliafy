// Products (the designs) and Items (each serial-numbered thing built from one):
// the addresses, the product page's tabs, the Explorer scoped to one tree, and
// the words the lists use. A product's id is its design's top position id.

import { EXPLORER_PARTS_CLASSES_TABS } from "./explorerTabs.js";
import { explorerPath } from "./assetTree.js";

export const PRODUCTS_PATH = "/products";
export const ITEMS_PATH = "/items";
export const PRODUCTS_GUIDE = "products-and-items";

// A product's page is the Explorer on its design (?view= names the tree's tab,
// as ?tab= does on the Explorer's own page). Its earlier page tabs (?tab=) are
// in that page now: the parts list is the tree's Parts tab (hidden for now:
// the product's Summary holds it as its Bill of materials); the items built,
// their failure reports and the analyses are on the product's Summary.
// Where an earlier product tab (?tab=) lands on the page now: the tree tab to
// open (null: Summary).
export function productTab(param) {
  return param === "parts" && EXPLORER_PARTS_CLASSES_TABS ? "parts" : null;
}

export function productPath(id, tab = null) {
  const base = `${PRODUCTS_PATH}/${encodeURIComponent(id)}`;
  const view = productTab(tab);
  return view ? `${base}?view=${view}` : base;
}

// A product's design on one of its structure's tabs (view: "rcm", "fmea"), the
// top position picked.
export function productViewPath(id, view = "fmea") {
  return `${productPath(id)}?view=${encodeURIComponent(view)}&sel=${encodeURIComponent(id)}`;
}

// A link to another row or tab of the tree being looked at (the RCM's "Open in
// LSA", the LSA's "Serves" links): on a product's page it stays on that page
// (its tabs are ?view=), on an item's tree it keeps the tree (?root=), and
// elsewhere it's the Explorer by positions. `extra`: { tab, sel, task, ... }.
export function explorerHere(pathname = "", search = "", extra = {}) {
  if (pathname.startsWith(`${PRODUCTS_PATH}/`)) {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(extra)) if (v) q.set(k === "tab" ? "view" : k, v);
    return `${pathname}?${q}`;
  }
  const root = new URLSearchParams(search).get("root");
  return explorerPath("positions", { ...(root ? { root } : {}), ...extra });
}

// An item's own page, and its tree (the Explorer scoped to that one tree).
export const itemPagePath = (id) => `/asset-register/items/${encodeURIComponent(id)}`;
export function itemTreePath(topPositionId, sel = null) {
  const q = new URLSearchParams({ arrange: "positions", root: topPositionId });
  if (sel) q.set("sel", sel);
  return `/asset-register/explorer?${q}`;
}

// The ids of every position in a product's design or in an item's tree built
// from one (the tree read marks a design's top `design`, every built position
// `design_position_id`).
export function productTreeIds(positions = []) {
  const kids = new Map();
  for (const p of positions) {
    const k = p.parent_id ?? null;
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(p);
  }
  const out = new Set();
  const walk = (p) => {
    if (out.has(p.id)) return;
    out.add(p.id);
    for (const c of kids.get(p.id) || []) walk(c);
  };
  for (const p of positions) {
    if (p.design_position_id) out.add(p.id);
    if (p.design && !p.parent_id) walk(p);
  }
  return out;
}

// The locations a tree read keeps for a scope: with a root, that product's
// design locations (`design_of`) or the ones that built item carries
// (`carried_by`), a design's marked `in_design`; without, the places you look
// after (neither: a product's layout is never an asset).
export function scopeLocations(locations = [], root = null, design = false) {
  if (!root) return locations.filter((l) => !l.design_of && !l.carried_by);
  return locations.filter((l) => (design ? l.design_of === root : l.carried_by === root))
    .map((l) => (design ? { ...l, in_design: true } : l));
}

// The tree read as the Explorer shows it. With a root: only that tree (a
// product's design, or an item's tree); a design's positions are each marked
// `in_design` (the tree read marks only its top `design`), so the panel knows
// they're a design's, with no maintenance. Without: everything but the
// products' designs and the items' trees (they're under Products and Items).
// Its locations as scopeLocations keeps them; with a root, `scope` says whose
// tree it is ({kind: "design" | "unit", id, name}) for the Locations arrangement.
// A root that's a place you look after (an asset on the Assets page, opened by
// Classes): every position there or at a place inside it (set or inherited),
// as the server's ?within= reads it; `scope` kind "place".
export function scopeTree(data, root = null) {
  if (!data?.positions) return data;
  const top = root ? data.positions.find((p) => p.id === root) : null;
  const place = root && !top ? scopeLocations(data.locations || []).find((l) => l.id === root) : null;
  if (place) return scopePlace(data, place);
  const locations = root && !top ? [] : scopeLocations(data.locations || [], root, !!top?.design);
  // Nothing to leave out: the same read.
  if (!root && locations.length === (data.locations || []).length && !productTreeIds(data.positions).size) return data;
  const scoped = { ...data, locations: data.locations ? locations : data.locations };
  if (top) scoped.scope = { kind: top.design ? "design" : "unit", id: root, name: top.name || "" };
  return scopePositions(scoped, root);
}

function scopePlace(data, place) {
  const all = scopeLocations(data.locations || []);
  const kids = new Map();
  for (const l of all) {
    if (!kids.has(l.parent_id ?? null)) kids.set(l.parent_id ?? null, []);
    kids.get(l.parent_id ?? null).push(l.id);
  }
  const places = new Set();
  const stack = [place.id];
  while (stack.length) {
    const id = stack.pop();
    if (places.has(id)) continue;
    places.add(id);
    stack.push(...(kids.get(id) || []));
  }
  const drop = productTreeIds(data.positions);
  return {
    ...data,
    locations: all.filter((l) => places.has(l.id)),
    positions: data.positions.filter((p) => !drop.has(p.id) && places.has(p.location?.id)),
    scope: { kind: "place", id: place.id, name: place.name || "" },
  };
}

function scopePositions(data, root) {
  let keep;
  if (root) {
    const kids = new Map();
    for (const p of data.positions) {
      const k = p.parent_id ?? null;
      if (!kids.has(k)) kids.set(k, []);
      kids.get(k).push(p);
    }
    keep = new Set();
    const walk = (id) => {
      if (keep.has(id)) return;
      keep.add(id);
      for (const c of kids.get(id) || []) walk(c.id);
    };
    if (data.positions.some((p) => p.id === root)) walk(root);
  } else {
    const drop = productTreeIds(data.positions);
    keep = new Set(data.positions.filter((p) => !drop.has(p.id)).map((p) => p.id));
  }
  const design = !!(root && data.positions.find((p) => p.id === root)?.design);
  const positions = data.positions.filter((p) => keep.has(p.id));
  return { ...data, positions: design ? positions.map((p) => (p.design ? p : { ...p, in_design: true })) : positions };
}

// Is the tree scoped to a product's design (not an item's tree)?
export function isDesignScope(data, root) {
  return !!(root && data?.positions?.find((p) => p.id === root)?.design);
}

// Does one tree on show offer the Classes arrangement (the item classes, each with its positions)?
// An asset's tree opened on its own does (a position's tree, or a place's): items are fitted there. A product's design doesn't, on
// its own page (`ownPage`) or opened as a tree: nothing is fitted in a design. Until the tree is
// read (`data` null) the address is taken at its word, so a reload by Classes stays by Classes.
export function scopeHasClasses(data, { ownPage = false } = {}) {
  if (ownPage) return false;
  return !data || data.scope?.kind === "unit" || data.scope?.kind === "place";
}

// A design's rows: no failure report is filed there (a report is about an item).
// The product's own row (the design's top position, `r`) adds Build an item…
// first, as its Summary does (greyed with the reason when the workspace is
// view only).
export const BUILD_ITEM = { id: "build-item", label: "Build an item…" };
export function designActions(actions, design, { row = null, viewOnly = null } = {}) {
  if (!design) return actions;
  // A design's (and a built unit's) tree isn't in the Excel export: it's the product's.
  const out = actions.filter((a) => a.id !== "report-new" && a.id !== "event-log" && a.id !== "pos-here" && a.id !== "tree-export");
  if (row?.type !== "pos" || !row.ref?.design) return out;
  const offer = (a) => (viewOnly ? { ...a, disabled: true, reason: viewOnly } : a);
  return [offer(BUILD_ITEM), ...out];
}

// Words.
const n = (count, one, many = `${one}s`) => `${Number(count || 0).toLocaleString("en-AU")} ${count === 1 ? one : many}`;
export const itemsText = (count) => n(count, "item");
export const reportsText = (count) => n(count, "open report");

// "212 hours" (a counter's own unit), or "—" with none.
export function hoursText(hours) {
  if (!hours || hours.value == null) return "—";
  const v = Number(hours.value);
  const shown = Number.isInteger(v) ? v.toLocaleString("en-AU") : v.toLocaleString("en-AU", { maximumFractionDigits: 1 });
  return `${shown} ${hours.unit || "hours"}`;
}

// "Rev C" or "" with none.
export const revText = (rev) => (rev ? `Rev ${rev}` : "");

// The Items list's status, in words.
const STATUS = { fitted: "Fitted", spare: "Spare (placed)", "not placed": "Not placed" };
export const statusText = (status) => STATUS[status] || status || "—";

// The filter choices for the Items list from what's in it: the products and
// the types (item classes), each by name, plus "none" when some have none.
export function itemFilters(products = [], classes = []) {
  const byName = (a, b) => a.name.localeCompare(b.name);
  return {
    products: [...products].sort(byName).map((p) => ({ value: p.id, label: p.name })),
    types: [...classes].sort(byName).map((c) => ({ value: c.id, label: c.name })),
  };
}

// The RBDs of a product: those named after it (one made from its structure is
// "<product> (from Maintenance)"; the sample's is "<product>: …").
export function productRbds(product, rbds = []) {
  if (!product?.name) return [];
  const name = product.name.toLowerCase();
  return rbds.filter((r) => {
    const n = String(r.name || "").toLowerCase();
    return n === name || n.startsWith(`${name} (`) || n.startsWith(`${name}:`);
  });
}

// A serial already used: the build's refusal in plain words is the server's own;
// an empty serial is caught before asking.
export function buildProblem(serial) {
  return String(serial || "").trim() ? null : "Give the item's serial number.";
}
