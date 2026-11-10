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
// top position picked (the Explorer's way to a Survey quadcopter).
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
export function scopeTree(data, root = null) {
  if (!data?.positions) return data;
  const top = root ? data.positions.find((p) => p.id === root) : null;
  const locations = root && !top ? [] : scopeLocations(data.locations || [], root, !!top?.design);
  // Nothing to leave out: the same read.
  if (!root && locations.length === (data.locations || []).length && !productTreeIds(data.positions).size) return data;
  const scoped = { ...data, locations: data.locations ? locations : data.locations };
  if (top) scoped.scope = { kind: top.design ? "design" : "unit", id: root, name: top.name || "" };
  return scopePositions(scoped, root);
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

// A design's rows: no failure report is filed there (a report is about an item).
// The product's own row (the design's top position, `r`) adds Build an item…
// first, as its Summary does (greyed with the reason when the workspace is
// view only).
// An earlier copy of the Survey quadcopter (still named "(sample)") adds Make
// this my own… after it on its own row (the copy becomes the user's product in
// place: "(sample)" leaves its name).
export const BUILD_ITEM = { id: "build-item", label: "Build an item…" };
export const MAKE_OWN = { id: "make-own", label: "Make this my own…" };
export function designActions(actions, design, { row = null, viewOnly = null } = {}) {
  if (!design) return actions;
  const out = actions.filter((a) => a.id !== "report-new" && a.id !== "event-log");
  if (row?.type !== "pos" || !row.ref?.design) return out;
  const offer = (a) => (viewOnly ? { ...a, disabled: true, reason: viewOnly } : a);
  return [offer(BUILD_ITEM), ...(isSampleRow(row) ? [offer(MAKE_OWN)] : []), ...out];
}

// Is the row a copy of the Survey quadcopter added before it took a product's own
// name (it still says "(sample)"), not yet made the user's own? A copy added now
// reads as the user's own from the start and is never offered this.
export const isSampleRow = (row) => row?.type === "pos" && !!row.ref?.design?.sample;

// Make this my own…'s question, and what's said once it's done.
export function makeOwnConfirm(name) {
  return {
    title: "Make this product your own?",
    body: `“${name}” becomes your own product, exactly as it is: its design, RCM, tasks, items and reports stay. “(sample)” leaves its name and the names of its part, built items, RBD and maintainability prediction. Its life models and strategy analyses are saved in your workspace as your own, and its positions and decisions point at those. It won't be added again beside this one unless you ask for a fresh copy.`,
    confirmLabel: "Make it my own",
    pendingLabel: "Making it yours…",
    failedWhat: "make it your own",
    destructive: false,
  };
}
// What it did, in the server's words when it sent them (what was renamed, what was
// saved as the user's own, and any record the plan's storage had no room for).
export const madeOwnText = (out) => out.message || `“${out.was}” is your own product now, as “${out.name}”.`;

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
