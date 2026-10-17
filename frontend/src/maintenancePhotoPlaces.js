// Reliafy Maintenance: the places a photo shows. One photo can be on several
// positions, locations, items and work orders (a nameplate taken on a work
// order, on its position and location too); these are the words and links for
// them, and the choices in the "Link or move" picker.

export const PLACE_KINDS = ["Position", "Location", "Item", "WorkOrder"];

const WORDS = { Position: "position", Location: "location", Item: "item", WorkOrder: "work order" };
const PATHS = { Position: "positions", Location: "locations", Item: "items", WorkOrder: "work-orders" };

// "work order" for "WorkOrder"; also takes the lower-case kinds work order
// subjects use ("position").
export function placeKindWord(kind) {
  const k = normaliseKind(kind);
  return WORDS[k] || String(kind || "").toLowerCase();
}

export function normaliseKind(kind) {
  if (!kind) return null;
  const found = PLACE_KINDS.find((k) => k.toLowerCase() === String(kind).replace(/[\s_-]/g, "").toLowerCase());
  return found || null;
}

// The page a place is on, or null for a kind without one.
export function placePath(place) {
  const k = normaliseKind(place?.kind);
  return k && place.id ? `/maintenance/${PATHS[k]}/${place.id}` : null;
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
