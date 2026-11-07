// The Data model page's logic (views/DataModelPage.jsx): the live graph's
// schema and the stored design turned into one diagram's nodes and edges, the
// three views of it ("What's built", "What's designed", "Both"), the table
// rows, search, colours, and the Arrows (arrows.app) export. Pure functions,
// no React, so node --test covers them.

export const VIEWS = [
  { id: "built", label: "What's built" },
  { id: "designed", label: "What's designed" },
  { id: "both", label: "Both" },
];

// One colour per kind of thing, in alphabetical order of every label (built or designed).
// Each holds white text at 4.5:1 or better. None is the warning colour, which
// marks what's built but not in the design.
export const PALETTE = [
  "#1d4ed8", "#0e7490", "#7c3aed", "#be185d", "#15803d", "#4338ca",
  "#0f766e", "#a21caf", "#475569", "#9f1239", "#3f6212",
];
export const WARN = "#b45309";

export const edgeKey = (from, type, to) => `${from}|${type}|${to}`;
const NO_LABEL = "(no label)";

// The live schema (GET /api/maintenance/graph/schema) as kinds and connections.
export function liveModel(schema) {
  const nodes = new Map();
  for (const n of schema?.nodes || []) {
    if (!n?.label) continue;
    nodes.set(n.label, {
      label: n.label,
      count: Number.isFinite(n.count) ? n.count : null,
      properties: Object.entries(n.properties || {}).map(([key, p]) => ({ key, type: p?.type || "" })),
    });
  }
  const edges = [];
  for (const r of schema?.relationships || []) {
    if (!r?.type) continue;
    const connects = r.connects?.length ? r.connects : [];
    for (const c of connects) {
      const from = c.from || NO_LABEL;
      const to = c.to || NO_LABEL;
      for (const label of [from, to]) {
        if (!nodes.has(label)) nodes.set(label, { label, count: null, properties: [] });
      }
      edges.push({ from, type: r.type, to, count: Number.isFinite(c.count) ? c.count : null });
    }
  }
  return { nodes: [...nodes.values()], edges };
}

// The design document (GET /api/maintenance/graph/design) the same way, by
// label: edges name node ids, which become their nodes' labels.
export function designModel(design) {
  if (!design?.available) return null;
  const byId = new Map();
  const nodes = new Map();
  for (const n of design.nodes || []) {
    if (!n?.id || !n?.label) continue;
    byId.set(n.id, n.label);
    if (!nodes.has(n.label)) {
      nodes.set(n.label, { label: n.label, structure: n.structure || null, definition: n.definition || null });
    }
  }
  const edges = [];
  const seen = new Set();
  for (const e of design.edges || []) {
    const from = byId.get(e?.from);
    const to = byId.get(e?.to);
    if (!from || !to || !e.type) continue;
    const key = edgeKey(from, e.type, to);
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({ from, type: e.type, to, status: e.status === "proposed" ? "proposed" : "decided", note: e.note || null });
  }
  return { nodes: [...nodes.values()], edges, updated: design.updated || null };
}

// One diagram for a view: nodes and edges, each saying whether it's built,
// designed or both, and how to draw it (`dashed`, `warn`). A designed node
// matches a built one by its label.
//   built     the live graph only;
//   designed  the design only (a proposed edge dashed), with live counts where built;
//   both      everything: designed but not built yet dashed, built but not
//             in the design in the warning colour.
export function combine(live, design, view) {
  const liveNodes = new Map((live?.nodes || []).map((n) => [n.label, n]));
  const designNodes = new Map((design?.nodes || []).map((n) => [n.label, n]));
  const liveEdges = new Map((live?.edges || []).map((e) => [edgeKey(e.from, e.type, e.to), e]));
  const designEdges = new Map((design?.edges || []).map((e) => [edgeKey(e.from, e.type, e.to), e]));
  const useLive = view !== "designed";
  const useDesign = view !== "built";

  const labels = new Set();
  if (useLive) for (const l of liveNodes.keys()) labels.add(l);
  if (useDesign) for (const l of designNodes.keys()) labels.add(l);
  const keys = new Set();
  if (useLive) for (const k of liveEdges.keys()) keys.add(k);
  if (useDesign) for (const k of designEdges.keys()) keys.add(k);
  // An edge's ends are always drawn.
  for (const k of keys) {
    const e = liveEdges.get(k) || designEdges.get(k);
    labels.add(e.from);
    labels.add(e.to);
  }

  // Colours by the labels of both, so a kind keeps its colour from view to view.
  const everyLabel = new Set([...liveNodes.keys(), ...designNodes.keys()]);
  for (const e of [...liveEdges.values(), ...designEdges.values()]) everyLabel.add(e.from).add(e.to);
  const colourAt = new Map([...everyLabel].sort((a, b) => a.localeCompare(b)).map((l, i) => [l, PALETTE[i % PALETTE.length]]));
  const sorted = [...labels].sort((a, b) => a.localeCompare(b));
  const nodes = sorted.map((label) => {
    const l = liveNodes.get(label);
    const d = designNodes.get(label);
    const built = Boolean(l);
    const designed = Boolean(d);
    return {
      id: label,
      label,
      count: l ? l.count : null,
      properties: l ? l.properties : [],
      structure: d?.structure || null,
      definition: d?.definition || null,
      built,
      designed,
      colour: colourAt.get(label),
      dashed: view === "both" && designed && !built,
      warn: view === "both" && built && !designed,
    };
  });
  const edges = [...keys].sort().map((key, i) => {
    const l = liveEdges.get(key);
    const d = designEdges.get(key);
    const e = l || d;
    const built = Boolean(l);
    const designed = Boolean(d);
    return {
      id: `e${i}`,
      key,
      from: e.from,
      type: e.type,
      to: e.to,
      count: l ? l.count : null,
      status: d ? d.status : null,
      note: d?.note || null,
      built,
      designed,
      loop: e.from === e.to,
      dashed: view === "designed" ? d?.status === "proposed" : view === "both" && designed && !built,
      warn: view === "both" && built && !designed,
    };
  });
  return { nodes, edges };
}

// What a node or edge is, in words, for the details panel and the table.
export function stateText(thing, view) {
  if (view === "built") return "";
  if (view === "designed") return thing.status === "proposed" ? "Proposed" : thing.status === "decided" ? "Decided" : "";
  if (thing.built && thing.designed) return "Built and designed";
  if (thing.designed) return "Designed, not built yet";
  return "Built, not in the design";
}

// A node's connections, out and in.
export function connectionsOf(model, label) {
  return {
    out: model.edges.filter((e) => e.from === label),
    in: model.edges.filter((e) => e.to === label && e.from !== label),
  };
}

// The rows of the table: every connection, then every kind with none.
export function tableRows(model) {
  const rows = model.edges.map((e) => ({ ...e, kind: "edge" }));
  const linked = new Set(model.edges.flatMap((e) => [e.from, e.to]));
  for (const n of model.nodes) {
    if (!linked.has(n.id)) rows.push({ kind: "node", id: n.id, from: n.label, type: null, to: null, count: n.count, built: n.built, designed: n.designed });
  }
  return rows;
}

// What a search picks out: the nodes whose label and the edges whose type
// holds the text (case ignored), and the nodes at each end of a picked edge.
export function searchModel(model, query) {
  const q = (query || "").trim().toLowerCase();
  if (!q) return null;
  const nodes = new Set(model.nodes.filter((n) => n.label.toLowerCase().includes(q)).map((n) => n.id));
  const edges = new Set();
  for (const e of model.edges) {
    if (e.type.toLowerCase().includes(q)) {
      edges.add(e.id);
      nodes.add(e.from);
      nodes.add(e.to);
    }
  }
  return { nodes, edges };
}

// A node's size on the diagram: bigger for more, on a log scale, 44 to 110 px.
export function nodeSize(count, max) {
  if (!Number.isFinite(count) || count <= 0 || !Number.isFinite(max) || max <= 0) return 54;
  const t = Math.log10(count + 1) / Math.log10(max + 1);
  return Math.round(44 + t * 66);
}

export const formatCount = (n) => (Number.isFinite(n) ? n.toLocaleString("en-GB") : "");

export function caption(node, showCounts) {
  return showCounts && Number.isFinite(node.count) ? `${node.label}\n${formatCount(node.count)}` : node.label;
}

// Where each node goes without a drawn diagram (the table view): on a circle.
export function circlePositions(nodes, radius = 260) {
  const out = {};
  const n = nodes.length || 1;
  nodes.forEach((node, i) => {
    const a = (2 * Math.PI * i) / n - Math.PI / 2;
    out[node.id] = { x: Math.round(radius * Math.cos(a)), y: Math.round(radius * Math.sin(a)) };
  });
  return out;
}

// The diagram as an Arrows file (arrows.app, Neo4j's drawing tool): one node
// per kind, at its place on screen, and one relationship per connection; a
// proposed or not-yet-built connection dashed.
export function toArrows(model, positions = {}, { showCounts = true } = {}) {
  const ids = new Map(model.nodes.map((n, i) => [n.id, `n${i}`]));
  const fallback = circlePositions(model.nodes);
  const nodes = model.nodes.map((n) => {
    const properties = {};
    if (showCounts && Number.isFinite(n.count)) properties.count = String(n.count);
    for (const p of n.properties || []) properties[p.key] = p.type || "";
    if (n.structure) properties.structure = n.structure;
    const style = { "node-color": n.colour, "caption-color": "#ffffff" };
    if (n.dashed) style["border-style"] = "dashed";
    if (n.warn) style["border-color"] = WARN;
    const at = positions[n.id] || fallback[n.id];
    return {
      id: ids.get(n.id),
      position: { x: Math.round(at.x), y: Math.round(at.y) },
      caption: n.label,
      labels: [n.label],
      properties,
      style,
    };
  });
  const relationships = model.edges.map((e, i) => {
    const properties = {};
    if (showCounts && Number.isFinite(e.count)) properties.count = String(e.count);
    if (e.status) properties.status = e.status;
    const style = {};
    if (e.dashed) style["border-style"] = "dashed";
    if (e.warn) style["arrow-color"] = WARN;
    return { id: `r${i}`, fromId: ids.get(e.from), toId: ids.get(e.to), type: e.type, properties, style };
  });
  return { nodes, relationships };
}

// Why there's nothing to draw, from the schema request's failure.
export function liveProblem(err) {
  const status = err?.status;
  if (status === 404 || status === 401 || status === 403) return "no-access";
  if (status === 503) return "not-connected";
  if (status === 422) return "not-copied";
  return "failed";
}

export const PROBLEM_TEXT = {
  "no-access": "Your account doesn't have graph access. The data model is shown only to people who can query the maintenance graph.",
  "not-connected": "The maintenance graph isn't connected on this server, so there's nothing built to draw.",
  "not-copied": "This workspace hasn't been copied to the maintenance graph yet, so there's nothing built to draw.",
  failed: "The maintenance graph couldn't be read just now. Try again in a minute.",
};
