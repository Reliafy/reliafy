// Phased missions and undirected networks (#160): the diagram-level settings
// and the small helpers the builder, the Phases editor and the Network panel
// share. A diagram holds
//
//   phases:  [{ name, duration, not_needed?: [blockId], votes?: {knodeId: n} }]
//   network: { source, target }   (read as an undirected network between them)
//
// Both ride with the graph wherever it goes (save, validate, analyse, the
// assistant), exactly like the diagram's costs and policies.

export const MISSION_KEYS = ["phases", "network"];

// The mission keys a graph has set.
export function missionFields(graph) {
  const out = {};
  if (Array.isArray(graph?.phases) && graph.phases.length) out.phases = graph.phases;
  if (graph?.network && typeof graph.network === "object") out.network = graph.network;
  return out;
}

export const isNetwork = (graph) => !!(graph?.network && typeof graph.network === "object");

// The network's terminals, Input and Output by default.
export function terminals(graph) {
  const n = graph?.network || {};
  return { source: n.source || "input", target: n.target || "output" };
}

// A network's connections drawn without arrows: a link works both ways.
export function undirectedEdges(edges) {
  return (edges || []).map((e) =>
    e.markerEnd ? { ...e, markerEnd: undefined, className: ((e.className || "") + " rbd-link").trim() } : e
  );
}

const isIo = (n) => n?.type === "input" || n?.type === "output";
export const nodeLabel = (n) =>
  n?.data?.label || (n?.type === "input" ? "Input" : n?.type === "output" ? "Output" : n?.id);

// What a network still needs before it can be analysed (null when ready):
// "no_blocks" with nothing but Input and Output, "not_connected" when no path
// of connections (either way) joins the two terminals.
export function networkGap(graph) {
  const nodes = (graph?.nodes || []).filter((n) => n && typeof n === "object");
  if (!nodes.some((n) => !isIo(n))) return "no_blocks";
  const { source, target } = terminals(graph);
  const adj = new Map();
  for (const e of graph?.edges || []) {
    if (e?.source == null || e?.target == null) continue;
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  }
  const seen = new Set([source]);
  const stack = [source];
  while (stack.length) {
    for (const next of adj.get(stack.pop()) || []) {
      if (!seen.has(next)) {
        seen.add(next);
        stack.push(next);
      }
    }
  }
  return seen.has(target) ? null : "not_connected";
}

// The nodes a terminal can be: Input, Output and every block.
export function terminalOptions(nodes) {
  return (nodes || [])
    .filter((n) => n && n.type !== "knode" && !n.data?.repeat_of)
    .map((n) => ({ value: n.id, label: nodeLabel(n) }));
}

// The blocks a phase can do without: every block but vote nodes and
// repeated copies (a copy goes with its original).
export function phaseBlocks(nodes) {
  return (nodes || [])
    .filter((n) => n && !isIo(n) && n.type !== "knode" && !n.data?.repeat_of)
    .map((n) => ({ id: n.id, label: nodeLabel(n) }));
}

// The vote nodes, with how many branches feed each and the n drawn on it.
export function voteNodes(nodes, edges) {
  const feeding = new Map();
  for (const e of edges || []) feeding.set(e.target, (feeding.get(e.target) || 0) + 1);
  return (nodes || [])
    .filter((n) => n?.type === "knode")
    .map((n) => ({
      id: n.id,
      label: n.data?.label || "Vote node",
      n: Math.max(1, Number(n.data?.n) || 1),
      inputs: feeding.get(n.id) || 0,
    }));
}

// Phases as they're stored: trimmed names, numeric durations, no empty or
// unknown entries. Returns { phases, errors } — errors in plain words.
export function cleanPhases(rows, nodes) {
  const blocks = new Set(phaseBlocks(nodes).map((b) => b.id));
  const votes = new Map(voteNodes(nodes, []).map((v) => [v.id, v]));
  const errors = [];
  const seen = new Set();
  const phases = (rows || []).map((r, i) => {
    const name = String(r.name || "").trim().slice(0, 80);
    const where = name ? `“${name}”` : `Phase ${i + 1}`;
    if (!name) errors.push(`${where} needs a name.`);
    else if (seen.has(name.toLowerCase())) errors.push(`Two phases are named “${name}”.`);
    seen.add(name.toLowerCase());
    const duration = Number(r.duration);
    if (String(r.duration ?? "").trim() === "" || !Number.isFinite(duration) || duration < 0)
      errors.push(`${where} needs a duration of 0 or more.`);
    const out = { name, duration };
    const notNeeded = (r.not_needed || []).filter((id) => blocks.has(id));
    if (notNeeded.length) out.not_needed = [...new Set(notNeeded)];
    const v = {};
    for (const [id, n] of Object.entries(r.votes || {})) {
      const num = Number(n);
      if (!votes.has(id) || String(n ?? "").trim() === "") continue;
      if (!Number.isInteger(num) || num < 1) errors.push(`${where}: a vote count must be a whole number of 1 or more.`);
      else v[id] = num;
    }
    if (Object.keys(v).length) out.votes = v;
    return out;
  });
  return { phases, errors };
}

// A reliability as a percentage that never rounds up to 100% (#160): enough
// decimals that its complement keeps two significant figures near 1.
export function reliabilityPercent(v) {
  const r = Number(v);
  if (v == null || !Number.isFinite(r)) return "—";
  const q = 1 - r;
  if (r < 0.99 || q <= 0) {
    if (q <= 0) return "100%";
    return `${(r * 100).toPrecision(3)}%`;
  }
  const decimals = Math.min(8, Math.max(1, Math.ceil(-Math.log10(q * 100)) + 1));
  return `${(r * 100).toFixed(decimals)}%`;
}

// The blocks tied for the top importance (within a part in a million), for
// "most important block": a symmetric network often has several.
export function topBlocks(importance) {
  const rows = (importance || []).filter((r) => r.birnbaum > 0);
  if (!rows.length) return [];
  const best = rows[0].birnbaum;
  return rows.filter((r) => r.birnbaum >= best * (1 - 1e-6));
}
