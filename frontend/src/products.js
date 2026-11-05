// Products (the designs) and Items (each serial-numbered thing built from one):
// the addresses, the product page's tabs, the Explorer scoped to one tree, and
// the words the lists use. A product's id is its design's top position id.

export const PRODUCTS_PATH = "/products";
export const ITEMS_PATH = "/items";
export const PRODUCTS_GUIDE = "products-and-items";

// The product page's tabs (?tab=; Functional structure when none).
export const PRODUCT_TABS = [
  { id: "structure", label: "Functional structure" },
  { id: "parts", label: "Parts list" },
  { id: "items", label: "Items" },
  { id: "reports", label: "Failure reports" },
  { id: "analysis", label: "Analysis" },
];
const TAB_IDS = new Set(PRODUCT_TABS.map((t) => t.id));

export function productTab(param) {
  return TAB_IDS.has(param) ? param : "structure";
}

export function productPath(id, tab = "structure") {
  const base = `${PRODUCTS_PATH}/${encodeURIComponent(id)}`;
  return tab && tab !== "structure" ? `${base}?tab=${tab}` : base;
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

// The tree read as the Explorer shows it. With a root: only that tree (a
// product's design, or an item's tree). Without: everything but the products'
// designs and the items' trees (they're under Products and Items).
export function scopeTree(data, root = null) {
  if (!data?.positions) return data;
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
    if (!drop.size) return data;
    keep = new Set(data.positions.filter((p) => !drop.has(p.id)).map((p) => p.id));
  }
  return { ...data, positions: data.positions.filter((p) => keep.has(p.id)) };
}

// Is the tree scoped to a product's design (not an item's tree)?
export function isDesignScope(data, root) {
  return !!(root && data?.positions?.find((p) => p.id === root)?.design);
}

// A design's rows: no failure report is filed there (a report is about an item).
export function designActions(actions, design) {
  return design ? actions.filter((a) => a.id !== "report-new") : actions;
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
