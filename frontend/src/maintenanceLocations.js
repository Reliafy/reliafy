// Reliafy Maintenance: positions (the functional tree) linked to locations (the
// physical tree). A position's location is set on it or inherited; a fitted item
// is where its position is; an item that isn't fitted is placed, or was last at
// the position it came out of.

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// A location picker's options: every location by its full path ("Site › Area X").
export function locationOptions(locations) {
  return (locations || [])
    .map((l) => ({ id: l.id, label: l.display || (l.parent ? `${l.parent.name} › ${l.name}` : l.name) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

// Where a position's location comes from, in words ("" when it's set on it).
export function inheritedText(location) {
  if (!location?.inherited || !location.inherited_from) return "";
  const from = location.inherited_from;
  return from.kind === "Item" ? `from ${from.name}, the item it's inside` : `inherited from ${from.name}`;
}

// Where an item is, for its page and the items list: { label, locationId, note }.
export function itemWhere(item, fmtDate = (d) => d) {
  const loc = item?.location;
  if (loc) {
    const label = loc.display || loc.name;
    if (loc.how === "fitted") {
      return { label, locationId: loc.id, note: loc.position ? `where ${loc.position.name} is` : "where its position is" };
    }
    return { label, locationId: loc.id, note: loc.since ? `placed ${fmtDate(loc.since)}` : "placed" };
  }
  const last = item?.last_at;
  if (last) {
    const where = last.location ? (last.location.display || last.location.name) : null;
    // The items list gives last_at as the location itself; an item page gives {location, position, since}.
    if (!last.position && last.name) return { label: `last at ${last.display || last.name}`, locationId: last.id, note: "" };
    return {
      label: where ? `last at ${where}` : "not placed",
      locationId: last.location?.id || null,
      note: last.position ? `came out of ${last.position.name}${last.since ? ` on ${fmtDate(last.since)}` : ""}` : "",
    };
  }
  return { label: "", locationId: null, note: "" };
}

// A location's counts in a line: "5 positions · 2 fitted items · 1 item placed · 1 open work order".
export function countsText(counts) {
  if (!counts) return "";
  return [
    plural(counts.positions, "position"),
    counts.fitted_items ? plural(counts.fitted_items, "fitted item") : null,
    counts.items ? `${plural(counts.items, "item")} placed` : null,
    counts.open_work_orders ? plural(counts.open_work_orders, "open work order") : null,
  ].filter(Boolean).join(" · ");
}
