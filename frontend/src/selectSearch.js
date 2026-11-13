// The search box of a long drop-down (Select's ``searchable``): the options
// whose label or hint holds every word typed, in any order and any case.
// A group heading stays only while an option under it matches.

const words = (q) => String(q || "").toLowerCase().split(/\s+/).filter(Boolean);

export function matchesQuery(option, query) {
  const want = words(query);
  if (!want.length) return true;
  const text = `${option?.label ?? ""} ${option?.hint ?? ""}`.toLowerCase();
  return want.every((w) => text.includes(w));
}

// ``items`` are Select's normalised rows (``_header`` marks a heading).
export function filterOptions(items, query) {
  if (!words(query).length) return items;
  const out = [];
  let heading = null;
  for (const o of items) {
    if (o._header) {
      heading = o;
      continue;
    }
    // "— choose —" (an empty value) is a reset, not a match.
    if (o.value === "" || o.value == null) continue;
    if (!matchesQuery(o, query)) continue;
    if (heading) {
      out.push(heading);
      heading = null;
    }
    out.push(o);
  }
  return out;
}
