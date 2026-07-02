// Pure helpers for reliability-block-diagram graphs, shared by the RBD builder
// and the AI assistant. Turns a minimal {nodes, edges} description (as the agent
// produces, or as the canvas holds) into the React-Flow / persisted shape:
// input/output handles on the sides, edges styled, life models fleshed out, and
// a tidy left-to-right layered layout so the agent never has to place nodes.

const COL_GAP = 280;
const ROW_GAP = 150;

const DIST_NAMES = {
  weibull: "Weibull",
  exponential: "Exponential",
  normal: "Normal",
  lognormal: "Lognormal",
  gamma: "Gamma",
  weibull_ph: "Weibull PH",
  exponential_ph: "Exponential PH",
  lognormal_ph: "Lognormal PH",
  normal_ph: "Normal PH",
  gamma_ph: "Gamma PH",
  cox_ph: "Cox PH",
};

const ARROW = { type: "arrowclosed", width: 18, height: 18 };

// Longest-path layered layout (mirrors the builder's Auto-arrange): each node's
// column is its longest path from the inputs; same-column nodes are stacked and
// vertically centred; Input is pinned first, Output last.
export function layoutGraph(nodes, edges) {
  const ids = new Set(nodes.map((n) => n.id));
  const indeg = new Map(nodes.map((n) => [n.id, 0]));
  const adj = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    adj.get(e.source).push(e.target);
    indeg.set(e.target, indeg.get(e.target) + 1);
  }

  const rank = new Map();
  const remaining = new Map(indeg);
  const queue = [];
  for (const n of nodes) if (remaining.get(n.id) === 0) { rank.set(n.id, 0); queue.push(n.id); }
  while (queue.length) {
    const id = queue.shift();
    const r = rank.get(id) ?? 0;
    for (const t of adj.get(id)) {
      rank.set(t, Math.max(rank.get(t) ?? 0, r + 1));
      remaining.set(t, remaining.get(t) - 1);
      if (remaining.get(t) === 0) queue.push(t);
    }
  }
  for (const n of nodes) if (!rank.has(n.id)) rank.set(n.id, 0);

  let maxRank = 0;
  for (const v of rank.values()) maxRank = Math.max(maxRank, v);
  if (ids.has("input")) rank.set("input", 0);
  if (ids.has("output")) rank.set("output", Math.max(maxRank, 1));
  maxRank = 0;
  for (const v of rank.values()) maxRank = Math.max(maxRank, v);

  const cols = new Map();
  for (const n of nodes) {
    const r = rank.get(n.id);
    if (!cols.has(r)) cols.set(r, []);
    cols.get(r).push(n);
  }

  const out = [];
  for (const [r, list] of cols) {
    list.sort((a, b) => a.id.localeCompare(b.id));
    const m = list.length;
    list.forEach((n, i) => {
      out.push({ ...n, position: { x: r * COL_GAP, y: (i - (m - 1) / 2) * ROW_GAP } });
    });
  }
  return out;
}

function fleshModel(model) {
  if (!model || typeof model !== "object") return model;
  const out = { ...model };
  if (out.distribution_id && !out.distribution) {
    out.distribution = DIST_NAMES[out.distribution_id] || out.distribution_id;
  }
  if (!out.source) out.source = "params";
  return out;
}

// Normalise a minimal {nodes, edges, unit} into the full builder/persisted shape.
export function normalizeRbdGraph(graph = {}) {
  const rawNodes = Array.isArray(graph.nodes) ? graph.nodes : [];
  const rawEdges = Array.isArray(graph.edges) ? graph.edges : [];

  const nodes = rawNodes.map((n) => {
    const data = { ...(n.data || {}) };
    if (data.model) data.model = fleshModel(data.model);
    if (!data.label) data.label = n.type === "input" ? "Input" : n.type === "output" ? "Output" : n.id;
    const base = { id: n.id, type: n.type, data, position: n.position };
    if (n.type === "input") {
      return { ...base, sourcePosition: "right", deletable: false, className: "rbd-node rbd-io" };
    }
    if (n.type === "output") {
      return { ...base, targetPosition: "left", deletable: false, className: "rbd-node rbd-io" };
    }
    return base;
  });

  const edges = rawEdges.map((e, i) => ({
    id: e.id || `e-${e.source}-${e.target}-${i}`,
    source: e.source,
    target: e.target,
    type: "smoothstep",
    markerEnd: ARROW,
  }));

  const laidOut = layoutGraph(nodes, edges);
  return { nodes: laidOut, edges, unit: graph.unit ?? "" };
}

// Strip a live/canvas graph down to the fields the assistant needs to read and
// edit (no positions, handles, or styling) — keeps token use and confusion down.
export function compactGraph(graph = {}) {
  const nodes = (graph.nodes || []).map((n) => {
    const d = n.data || {};
    const node = { id: n.id, type: n.type };
    if (d.label) node.label = d.label;
    if (d.model) {
      node.model = {
        distribution_id: d.model.distribution_id,
        params: d.model.params,
        ...(d.model.modelId ? { saved_model_id: d.model.modelId } : {}),
      };
    }
    for (const k of ["n", "k", "spares", "cold"]) if (d[k] != null) node[k] = d[k];
    if (d.rbd?.id) node.subsystem_rbd_id = d.rbd.id;
    return node;
  });
  const edges = (graph.edges || []).map((e) => ({ source: e.source, target: e.target }));
  return { nodes, edges, unit: graph.unit || "" };
}
