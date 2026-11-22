// The Guides drawer's filter box (components/HelpButton.jsx): the groups from
// guides.js `guidesByCategory` narrowed to the guides that match what was
// typed. A guide matches when every word typed is somewhere in its title, its
// one-line task or its text, whatever the case or the order ("csv fit" finds
// "Fit your first non-repairable model from a CSV"; "shape" finds the guide that
// explains a Weibull's shape). In each group the guides whose title or task
// match come first, then those that match in their text only. Groups left with
// no guide drop out; nothing typed keeps every group as it was.
export function filterGuideGroups(groups = [], query = "") {
  const words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return groups;
  const all = (text) => words.every((w) => text.includes(w));
  return groups
    .map((group) => {
      const head = [];
      const body = [];
      for (const g of group.items) {
        const named = `${g.title || ""} ${g.task || ""}`.toLowerCase();
        if (all(named)) head.push(g);
        else if (all(`${named} ${String(g.body || "").toLowerCase()}`)) body.push(g);
      }
      return { ...group, items: [...head, ...body] };
    })
    .filter((group) => group.items.length > 0);
}

// The guide for the page you're on, for the drawer's "?" to open at: the page's own (its header's
// "Read the guide", `pageSlug`) when it has one, else the guide whose `related` link is the
// longest match for the address (its path, or a path under it; a query on the link must be on the
// address too), the lowest `order` first on a tie (`guides` comes sorted that way). Null when
// no guide is about this page: the drawer then opens on the list.
export function guideForPath(guides = [], pathname = "", search = "", pageSlug = null) {
  if (pageSlug && guides.some((g) => g.slug === pageSlug)) return pageSlug;
  const here = new URLSearchParams(search || "");
  let best = null;
  let bestLen = 0;
  for (const g of guides) {
    const href = g.related?.href;
    if (!href || !href.startsWith("/")) continue;
    const [path, query = ""] = href.split("?");
    const clean = path.replace(/\/+$/, "") || "/";
    if (!(pathname === clean || pathname.startsWith(`${clean}/`))) continue;
    if ([...new URLSearchParams(query)].some(([k, v]) => here.get(k) !== v)) continue;
    const len = clean.length + (query ? query.length + 1 : 0);
    if (len > bestLen) {
      best = g.slug;
      bestLen = len;
    }
  }
  return best;
}
