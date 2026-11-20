// Systems › RBDs (views/RbdHome.jsx): the saved diagrams as a tree. A diagram built for another
// carries `parent_id` (GET /api/rbds: a sub-assembly's diagram that Build from what's inside made,
// or a mission's copy of a position's diagram) and is listed under that one, not at the top.
// Each row comes back with `depth` and its `children`; a row whose parent isn't in the list, or one
// caught in a loop, stays at the top, so nothing is ever left out.
export function nestRbds(rows = []) {
  const byId = new Map(rows.map((r) => [r.id, r]));
  const kids = new Map();
  const top = [];
  for (const r of rows) {
    const p = r.parent_id && r.parent_id !== r.id && byId.has(r.parent_id) ? r.parent_id : null;
    if (p) kids.set(p, [...(kids.get(p) || []), r]);
    else top.push(r);
  }
  const reached = new Set();
  const walk = (r, depth) => {
    if (reached.has(r.id)) return null;
    reached.add(r.id);
    return { ...r, depth, children: (kids.get(r.id) || []).map((c) => walk(c, depth + 1)).filter(Boolean) };
  };
  const out = top.map((r) => walk(r, 0)).filter(Boolean);
  for (const r of rows) if (!reached.has(r.id)) out.push(walk(r, 0));
  return out;
}

// A nested row and everything under it, for the list's search: finding "Propulsion" finds the
// drone's diagram it sits under.
export const rbdNames = (r) => [r.name, ...(r.children || []).flatMap(rbdNames)];
