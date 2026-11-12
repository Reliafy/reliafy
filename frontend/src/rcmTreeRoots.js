// The RCM done on the asset tree, for the RCM studies page (Nov 2026: studies there were free text,
// not tied to the tree, and the tree's RCM wasn't reachable from the page): one row per asset,
// the topmost position with RCM in each branch, with how many positions inside it have RCM and
// how many of their failure modes are decided. Read from GET /api/maintenance/rcm
// ({positions, parents}). Tested in rcmTreeRoots.test.js.

function modesOf(p) {
  const out = [...(p.unassigned || [])];
  for (const fn of p.functions || []) {
    out.push(...(fn.modes || []));
    for (const ff of fn.failures || []) out.push(...(ff.modes || []));
  }
  return out;
}

export function rcmTreeRoots(data) {
  const positions = data?.positions || [];
  const parents = data?.parents || {};
  const listed = new Map(positions.map((p) => [p.id, p]));
  // The topmost position with RCM above (or at) each one.
  const topOf = (id) => {
    let top = id;
    const seen = new Set([id]);
    let up = parents[id];
    while (up && !seen.has(up)) {
      seen.add(up);
      if (listed.has(up)) top = up;
      up = parents[up];
    }
    return top;
  };
  const roots = new Map();
  for (const p of positions) {
    const top = topOf(p.id);
    const r = roots.get(top) || { id: top, name: listed.get(top)?.name || "", positions: 0, modes: 0, decided: 0 };
    const modes = modesOf(p);
    r.positions += 1;
    r.modes += modes.length;
    r.decided += modes.filter((m) => m.decision).length;
    roots.set(top, r);
  }
  return [...roots.values()].sort((a, b) => a.name.localeCompare(b.name));
}

// "3 positions · 12 of 20 failure modes decided"
export function rcmRootLine(r) {
  const n = (x, one, many = `${one}s`) => `${x.toLocaleString("en-AU")} ${x === 1 ? one : many}`;
  return `${n(r.positions, "position")} · ${r.modes ? `${r.decided.toLocaleString("en-AU")} of ${n(r.modes, "failure mode")} decided` : "no failure modes yet"}`;
}
