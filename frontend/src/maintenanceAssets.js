// Assets: the assets are the top-level places (a house, a site, a
// plant), each counting what's anywhere inside it. Positions at no place stay
// reachable from one row at the end of the list, which opens the Explorer
// arranged by positions, filtered to them (AssetExplorer's ?place=none).

import { explorerPath } from "./assetTree.js";
import { lateWorkText, ordersPath } from "./maintenanceOrders.js";

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// Where the "Not at a place yet" row goes: the Explorer's positions, filtered.
export const NOT_PLACED_PATH = explorerPath("positions", { place: "none" });

// The Explorer arranged by positions, for "start with the positions".
export const POSITIONS_PATH = explorerPath("positions");

// A place's own page.
export const placePath = (id) => `/asset-register/locations/${id}`;

// The Assets list itself: where the Explorer sends an address with no asset (?root=) in it.
// There's no whole-register Explorer (Derryn, 14 Nov 2026): every asset is opened on its own.
export const ASSETS_LIST_PATH = "/asset-register";

// Where an asset in the list goes: the Explorer opened on that asset alone (?root=:
// nothing of another asset shows), arranged by locations, with the place picked.
export const assetPath = (id) => explorerPath("locations", { root: id, sel: id });

// What an Explorer address with no asset in it asked for (its tab, a pane to open, a
// Library record to fit with…), kept while the user picks the asset on the Assets list:
// the query without the asset or the row (root, sel), an old ?all=1 or ?place. "" for nothing.
const NOT_CARRIED = ["root", "sel", "all", "place"];
export function explorerCarry(params) {
  const q = new URLSearchParams(params);
  for (const k of NOT_CARRIED) q.delete(k);
  return q.toString();
}

// An asset opened from the Assets list with what the Explorer was asked for carried along
// (explorerCarry): the asset's own address with those keys on top.
export function assetOpenPath(id, carry = "") {
  const base = assetPath(id);
  if (!carry) return base;
  const [path, query] = base.split("?");
  const q = new URLSearchParams(query);
  for (const [k, v] of new URLSearchParams(carry)) if (!NOT_CARRIED.includes(k)) q.set(k, v);
  return `${path}?${q}`;
}

// The open work orders in a place's area (Maintenance › Orders, filtered by location).
export const openWorkPath = (id) => ordersPath("open", { location: id });

// What's inside a place, in words: "4 places inside" ("" for none).
export function insideText(place) {
  return place?.locations ? `${plural(place.locations, "place")} inside` : "";
}

// What's due in the next horizon days (overdue included), in words: { text,
// overdue }. text: "Nothing due", "3 due, next 4 Nov 2026", "3 due" when some
// are overdue (the late line says so), or "1 due, overdue since 18 May 2023" when
// the earliest date is already past but isn't counted as overdue (a plan with work
// management off, an old last done): never a past date as "next". today: the
// workspace's date (the server's), ISO. overdue: the late work in the wording Home
// and Orders use, from the asset's `late` counts ("2 work orders late · 1 task
// overdue with no work order"; lateWorkText).
export function dueText(row, fmtDate = (d) => d, today = null) {
  const overdue = lateWorkText(row?.late);
  if (!row?.due) return { text: "Nothing due", overdue };
  if (row.overdue) return { text: `${row.due} due`, overdue };
  if (!row.next_due) return { text: `${row.due} due`, overdue };
  const past = today && row.next_due < today;
  return { text: `${row.due} due, ${past ? "overdue since" : "next"} ${fmtDate(row.next_due)}`, overdue };
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

// The places a new position can be at, for the New position form's Location box:
// every place, depth first, A to Z, each labelled with its path ("Riverside ›
// Pump hall"). `locations`: [{id, name, parent_id}] (or {parent: {id}}).
export function locationChoices(locations) {
  const list = (locations || []).filter((l) => l && l.id);
  const byId = new Map(list.map((l) => [l.id, l]));
  const parentOf = (l) => {
    const p = l.parent_id ?? l.parent?.id ?? null;
    return p && byId.has(p) ? p : null;
  };
  const kids = new Map();
  for (const l of list) {
    const p = parentOf(l);
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(l);
  }
  const collator = new Intl.Collator("en", { numeric: true, sensitivity: "base" });
  for (const k of kids.values()) k.sort((a, b) => collator.compare(a.name || "", b.name || ""));
  const out = [];
  const seen = new Set();
  const walk = (p, path) => {
    for (const l of kids.get(p) || []) {
      if (seen.has(l.id)) continue;
      seen.add(l.id);
      const label = [...path, l.name || "(no name)"];
      out.push({ id: l.id, label: label.join(" › ") });
      walk(l.id, label);
    }
  };
  walk(null, []);
  return out;
}

// ---- the search inside the assets, and the items of products --------------------------------

// The asset a search result is at, in words: "Riverside", "Survey quadcopter · Q-7 at
// Riverside" (a built item's tree), "Not at a place yet" for a tree top with none.
export function siteText(site) {
  if (!site) return "";
  if (site.unit && site.name && site.name !== site.unit) return `${site.unit} at ${site.name}`;
  return site.unit || site.name || "Not at a place yet";
}

// A position found by the search: its title ("P-101 · Filter pump") and the line under
// it (the asset, the way down, what's fitted).
export function positionHitText(hit) {
  const title = hit.tag && hit.tag !== hit.name ? `${hit.tag} · ${hit.name}` : hit.name;
  // A built item's own tree top is named as the item: say neither twice.
  const site = siteText(hit.site);
  const item = hit.item && [hit.item.name !== hit.name ? hit.item.name : "", hit.item.serial && `serial ${hit.item.serial}`]
    .filter(Boolean).join(", ");
  return { title, sub: [site === hit.name ? "" : site.replace(`${hit.name} at `, "at "), hit.path, item ? `fitted: ${item}` : ""]
    .filter(Boolean).join(" · ") };
}

// An item found by the search (or listed as a product's): its title ("Grundfos CR ·
// serial SN-42") and where it is ("Riverside · fitted to Filter pump", "spare at Store
// A", "not fitted or placed"), with the product it is.
export function itemHitText(hit) {
  // A built item is named "<product> · <serial>": its serial isn't said again.
  const title = [hit.name, hit.serial && !String(hit.name).includes(hit.serial) && `serial ${hit.serial}`].filter(Boolean).join(" · ");
  const w = hit.where || {};
  const unit = hit.site?.unit;
  // Fitted at the top of its own tree (built from a product): where the tree is, if anywhere.
  const ownTree = w.how === "fitted" && unit && w.position.name === unit;
  const where = ownTree ? (hit.site.name && hit.site.name !== unit ? `at ${hit.site.name}` : "")
    : w.how === "fitted" ? `fitted to ${w.position.name}`
      : w.how === "placed" ? `kept at ${w.location.name}` : "not fitted or placed";
  const site = w.how && !ownTree ? siteText(hit.site) : "";
  const product = hit.product ? `${hit.product.built ? "built from" : "a"} ${hit.product.name}` : "";
  return { title, sub: [site && site !== "Not at a place yet" ? site : "", where, product].filter(Boolean).join(" · ") };
}

// The search's count line: "2 positions and 1 item inside your assets" ("" for none;
// "first 50 of 120 positions" when the server stopped at its limit).
export function matchesText(found) {
  if (!found) return "";
  const part = (shown, total, one) => {
    if (!total) return null;
    return shown < total ? `first ${shown} of ${plural(total, one)}` : plural(total, one);
  };
  const bits = [part(found.positions.length, found.positions_total, "position"),
    part(found.items.length, found.items_total, "item")].filter(Boolean);
  return bits.length ? `${bits.join(" and ")} inside your assets` : "";
}
