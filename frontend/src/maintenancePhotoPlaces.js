// Reliafy Maintenance: the places a photo shows. One photo can be on several
// positions, locations, items and work orders (a nameplate taken on a work
// order, on its position and location too); these are the words and links for
// them, and the choices in the "Link or move" picker.

export const PLACE_KINDS = ["Position", "Location", "Item", "WorkOrder"];

// A failure report (the Explorer's Failure reports tab) holds photos too, but
// isn't a place a photo is linked or moved to from the picker.
const WORDS = { Position: "position", Location: "location", Item: "item", WorkOrder: "work order", FailureReport: "failure report" };
// Each kind's pages: the register's under Assets, work orders under Maintenance.
const PATHS = {
  Position: "/asset-register/positions/", Location: "/asset-register/locations/", Item: "/asset-register/items/",
  WorkOrder: "/maintenance/work-orders/",
};

// "work order" for "WorkOrder"; also takes the lower-case kinds work order
// subjects use ("position").
export function placeKindWord(kind) {
  const k = normaliseKind(kind);
  return WORDS[k] || WORDS[kind] || String(kind || "").toLowerCase();
}

export function normaliseKind(kind) {
  if (!kind) return null;
  const found = PLACE_KINDS.find((k) => k.toLowerCase() === String(kind).replace(/[\s_-]/g, "").toLowerCase());
  return found || null;
}

// The page a place is on, or null for a kind without one.
export function placePath(place) {
  const k = normaliseKind(place?.kind);
  return k && place.id ? `${PATHS[k]}${place.id}` : null;
}

// "also on Pool pump and 2 more" under a thumbnail; "" when it's only here.
export function alsoOnText(places) {
  const list = places || [];
  if (!list.length) return "";
  const first = list[0].name || placeKindWord(list[0].kind);
  return list.length === 1 ? `also on ${first}` : `also on ${first} and ${list.length - 1} more`;
}

// Suggested places for a photo (what the page it's on is related to), without
// the page itself, ones the photo is already on, or repeats.
export function suggestions(related, here, on) {
  const skip = new Set([here, ...(on || []).map((p) => p.id)]);
  const out = [];
  for (const r of related || []) {
    const kind = normaliseKind(r?.kind);
    if (!r?.id || !kind || skip.has(r.id)) continue;
    skip.add(r.id);
    out.push({ id: r.id, kind, name: r.name || r.title || placeKindWord(kind) });
  }
  return out;
}

// The options for one kind in the picker: { id, label } in display order.
// positions: a flattened tree ({id, name, depth}); the others plain lists.
export function placeOptions(kind, lists) {
  const l = lists || {};
  if (kind === "Position") {
    return (l.positions || []).map((p) => ({ id: p.id, label: `${"  ".repeat(p.depth || 0)}${p.name}` }));
  }
  if (kind === "Location") {
    return (l.locations || [])
      .map((x) => ({ id: x.id, label: x.display || (x.parent ? `${x.parent.name} › ${x.name}` : x.name) }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }
  if (kind === "Item") {
    return (l.items || []).map((i) => ({ id: i.id, label: i.serial ? `${i.name} (${i.serial})` : i.name }));
  }
  if (kind === "WorkOrder") {
    return (l.workOrders || []).map((w) => ({
      id: w.id, label: `${w.number != null ? `#${w.number} ` : ""}${w.title || "Work order"}`,
    }));
  }
  return [];
}

// The photo viewer's keys: ← and → step through the gallery, wrapping at the
// ends; Home and End jump to the first and last. Any other key: null.
export function photoStep(index, count, key) {
  if (count < 2 || index < 0) return null;
  if (key === "ArrowRight") return (index + 1) % count;
  if (key === "ArrowLeft") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

// The words a thumbnail button reads out: "Open photo 2 of 5: Nameplate".
export function photoLabel(index, count, caption) {
  return `Open photo ${index + 1} of ${count}${caption ? `: ${caption}` : ""}`;
}

// The picker's choices inside one asset (the Explorer opened on it, ?root=), from that asset's
// tree read (GET /api/maintenance/tree?within=): its positions (depth first, A to Z), its places
// and its items (fitted there, or placed at one of its places). `ids`: every one of them, for
// keeping only the work orders on something inside it (inAsset).
export function assetLists(tree) {
  const positions = tree?.positions || [];
  const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""), "en", { numeric: true, sensitivity: "base" });
  const known = new Set(positions.map((p) => p.id));
  const kids = new Map();
  for (const p of positions) {
    const k = p.parent_id && known.has(p.parent_id) ? p.parent_id : null;
    if (!kids.has(k)) kids.set(k, []);
    kids.get(k).push(p);
  }
  for (const list of kids.values()) list.sort(byName);
  const ordered = [];
  const stack = [...(kids.get(null) || [])].reverse().map((p) => [p, 0]);
  const seen = new Set();
  while (stack.length) {
    const [p, depth] = stack.pop();
    if (seen.has(p.id)) continue;
    seen.add(p.id);
    ordered.push({ id: p.id, name: p.name, depth });
    for (const c of [...(kids.get(p.id) || [])].reverse()) stack.push([c, depth + 1]);
  }
  const locs = tree?.locations || [];
  const locById = new Map(locs.map((l) => [l.id, l]));
  const locations = locs.map((l) => ({ id: l.id, name: l.name, parent: locById.has(l.parent_id) ? { name: locById.get(l.parent_id).name } : null }));
  const items = [];
  const itemIds = new Set();
  for (const it of [...positions.map((p) => p.item).filter(Boolean), ...(tree?.spares || [])]) {
    if (itemIds.has(it.id)) continue;
    itemIds.add(it.id);
    items.push({ id: it.id, name: it.name, serial: it.serial });
  }
  items.sort(byName);
  return { positions: ordered, locations, items, ids: new Set([...known, ...locById.keys(), ...itemIds]) };
}

// Whether a work order (as the work order list gives it) is on something inside the asset (`ids`:
// assetLists' ids): what it's on, the position the work is at, or where it is.
export function inAsset(wo, ids) {
  return [wo?.subject?.id, wo?.position?.id, wo?.location?.id].some((id) => id && ids.has(id));
}
