// k-of-n vote nodes, checked against the inputs wired into them (never the total typed on the
// node): the same rules as the backend's check (backend/services/rbd_analysis.py,
// vote_node_notes), so the node shows what Calculate will say.

// The number of working inputs a vote node needs (its data.n), 1 when unset.
export function voteNeed(data) {
  const n = Number(data?.n ?? 1);
  return Number.isFinite(n) ? n : NaN;
}

// How many wires come into each node: { id: count }.
export function inputCounts(edges) {
  const into = {};
  for (const e of edges || []) if (e?.target) into[e.target] = (into[e.target] || 0) + 1;
  return into;
}

// A vote node's state from what it needs and what is wired in:
// "unwired" (nothing in yet, drawing), "too_many" (needs more than wired: refused),
// "all_must_work" (needs all of 2 or more: series, no redundancy), "ok".
export function voteState(need, inputs) {
  if (!Number.isInteger(need) || need < 1) return "too_many";
  if (!inputs) return need > 1 ? "unwired" : "ok";
  if (need > inputs) return "too_many";
  if (need === inputs && need > 1) return "all_must_work";
  return "ok";
}

// The node's one-line note for a state, or "".
export function voteNote(need, inputs) {
  switch (voteState(need, inputs)) {
    case "too_many": return `Needs ${need} working inputs; ${inputs === 1 ? "1 is" : `${inputs} are`} wired in`;
    case "all_must_work": return `All ${inputs} must work: no redundancy`;
    case "unwired": return `Wire in ${need} or more inputs`;
    default: return "";
  }
}

// After wires are removed: each vote node whose inputs dropped below what it needs (and still
// has at least one) is clamped to its inputs. `before` and `after` are inputCounts. Returns
// { nodes, clamped: [{ id, label, from, to }] }; nodes unchanged (the same array) when none is.
export function clampVotes(nodes, before, after) {
  const clamped = [];
  const out = (nodes || []).map((node) => {
    if (node?.type !== "knode") return node;
    const was = before[node.id] || 0;
    const now = after[node.id] || 0;
    const need = voteNeed(node.data);
    if (now >= was || now < 1 || !(need > now)) return node;
    clamped.push({ id: node.id, label: node.data?.label || "", from: need, to: now });
    return { ...node, data: { ...node.data, n: now, k: now } };
  });
  return clamped.length ? { nodes: out, clamped } : { nodes, clamped };
}

// The flash note for clamped vote nodes.
export function clampNote(clamped) {
  if (!clamped.length) return "";
  const one = (c) => `${c.label ? `“${c.label}”` : "A vote node"} now needs ${c.to} of ${c.to} (it needed ${c.from}, more than are wired in)`;
  return clamped.length === 1 ? `${one(clamped[0])}.` : `${clamped.map(one).join("; ")}.`;
}
