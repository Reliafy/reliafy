// The search box of a long drop-down (Select's ``searchable``): the options
// whose label or hint holds every word typed, in any order and any case.
// A group heading stays only while an option under it matches. Within a group
// the closest matches come first (an exact name, then a name that starts with
// what was typed, then one that holds it as a phrase), and Enter takes the
// closest match in the whole list: "Supplier A" never picks "Supplier B"
// because a lone "a" appears somewhere in its hint.

const words = (q) => String(q || "").toLowerCase().split(/\s+/).filter(Boolean);

export function matchesQuery(option, query) {
  const want = words(query);
  if (!want.length) return true;
  const text = `${option?.label ?? ""} ${option?.hint ?? ""}`.toLowerCase();
  return want.every((w) => text.includes(w));
}

const squash = (v) => String(v ?? "").toLowerCase().replace(/\s+/g, " ").trim();

// How close an option is to the query: 0 its name exactly, 1 its name starts
// with it, 2 its name holds it as a phrase, 3 every word somewhere.
export function matchRank(option, query) {
  const q = squash(query);
  const name = squash(option?.label);
  if (!q) return 3;
  if (name === q) return 0;
  if (name.startsWith(q)) return 1;
  if (name.includes(q)) return 2;
  return 3;
}

// ``items`` are Select's normalised rows (``_header`` marks a heading).
export function filterOptions(items, query) {
  if (!words(query).length) return items;
  const out = [];
  const groups = [];
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
      groups.push({ heading, rows: [] });
      heading = null;
    } else if (!groups.length) {
      groups.push({ heading: null, rows: [] });
    }
    groups[groups.length - 1].rows.push(o);
  }
  for (const g of groups) {
    if (g.heading) out.push(g.heading);
    // A stable sort: equally close matches keep the list's own order.
    out.push(...g.rows.map((o, i) => [matchRank(o, query), i, o]).sort((a, b) => a[0] - b[0] || a[1] - b[1])
      .map((r) => r[2]));
  }
  return out;
}

// The index in ``items`` (filterOptions' output) Enter takes: the closest
// match, the first of equals; -1 when nothing can be picked.
export function bestMatchIndex(items, query) {
  let best = -1;
  let bestRank = Infinity;
  (items || []).forEach((o, i) => {
    if (o._header || o.disabled) return;
    const r = matchRank(o, query);
    if (r < bestRank) {
      best = i;
      bestRank = r;
    }
  });
  return best;
}
