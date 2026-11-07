// A fault tree being edited, as the server stores it (backend/services/fault_trees.py):
//
//   { unit, top, nodes: [ {id, type: "gate", gate: "or"|"and"|"vote", k?, label, inputs: [ids]},
//                         {id, type: "event", label, model? | probability?, placeholder?} ] }
//
// Pure functions: each edit returns a new tree. The outline editor shows the
// tree as rows (outlineRows); a basic event under several gates (a repeated
// event) shows at each place, with `repeated` set.

export const GATE_LABELS = { or: "OR", and: "AND", vote: "Vote" };
export const GATE_WORDS = {
  or: "Occurs when any input occurs",
  and: "Occurs when all its inputs occur",
  vote: "Occurs when at least k of its inputs occur",
};
// The server's limit on gates and basic events (fault_trees.MAX_NODES).
export const MAX_NODES = 500;

export function emptyTree(label = "Top event") {
  return { unit: "Hours", top: "top", nodes: [{ id: "top", type: "gate", gate: "or", label, inputs: [] }] };
}

const byId = (tree) => Object.fromEntries(tree.nodes.map((n) => [n.id, n]));

export function nodeOf(tree, id) {
  return tree.nodes.find((n) => n.id === id) || null;
}

// A new id, unique in the tree: "g1", "g2", … or "e1", "e2", …
export function newId(tree, prefix) {
  const ids = new Set(tree.nodes.map((n) => n.id));
  let i = 1;
  while (ids.has(`${prefix}${i}`)) i += 1;
  return `${prefix}${i}`;
}

function replaceNode(tree, id, fn) {
  return { ...tree, nodes: tree.nodes.map((n) => (n.id === id ? fn(n) : n)) };
}

// Drop nodes no longer under the top event (after a delete or a move).
export function prune(tree) {
  const nodes = byId(tree);
  const keep = new Set();
  const walk = (id) => {
    if (keep.has(id) || !nodes[id]) return;
    keep.add(id);
    for (const x of nodes[id].inputs || []) walk(x);
  };
  walk(tree.top);
  return { ...tree, nodes: tree.nodes.filter((n) => keep.has(n.id)) };
}

// The tree as outline rows, top first, depth first: {key, id, depth, parent,
// index, node, repeated, last}. `key` is the path from the top, unique per row.
export function outlineRows(tree) {
  const nodes = byId(tree);
  const uses = {};
  for (const n of tree.nodes) for (const x of n.inputs || []) uses[x] = (uses[x] || 0) + 1;
  const rows = [];
  const walk = (id, depth, parent, index, key, seen) => {
    const node = nodes[id];
    if (!node) return;
    const siblings = parent ? nodes[parent].inputs : [id];
    rows.push({ key, id, depth, parent, index, node, repeated: (uses[id] || 0) > 1,
                last: index === siblings.length - 1 });
    if (seen.has(id)) return; // a loop: the server refuses it, don't spin here
    const next = new Set(seen).add(id);
    (node.inputs || []).forEach((x, i) => walk(x, depth + 1, id, i, `${key}/${x}`, next));
  };
  walk(tree.top, 0, null, 0, tree.top, new Set());
  return rows;
}

// Add a new gate or basic event as the last input of `gateId`: {tree, id}.
export function addChild(tree, gateId, type, gate = "or") {
  const id = newId(tree, type === "gate" ? "g" : "e");
  const count = tree.nodes.filter((n) => n.type === type).length + 1;
  const node = type === "gate"
    ? { id, type: "gate", gate, label: `Gate ${count}`, inputs: [], ...(gate === "vote" ? { k: 2 } : {}) }
    : { id, type: "event", label: `Basic event ${count}` };
  const next = replaceNode({ ...tree, nodes: [...tree.nodes, node] }, gateId, (g) => ({ ...g, inputs: [...(g.inputs || []), id] }));
  return { tree: next, id };
}

// Put an existing basic event under another gate too (a repeated event).
export function addRepeat(tree, gateId, eventId) {
  const gate = nodeOf(tree, gateId);
  if (!gate || gate.type !== "gate" || (gate.inputs || []).includes(eventId)) return tree;
  return replaceNode(tree, gateId, (g) => ({ ...g, inputs: [...g.inputs, eventId] }));
}

export function rename(tree, id, label) {
  return replaceNode(tree, id, (n) => ({ ...n, label }));
}

// Change a gate's type; a vote keeps (or gets) its k, within its inputs.
export function setGate(tree, id, gate, k) {
  return replaceNode(tree, id, (n) => {
    const out = { ...n, gate };
    if (gate === "vote") out.k = Math.max(1, Math.round(Number(k ?? n.k ?? 2)) || 1);
    else delete out.k;
    return out;
  });
}

// A basic event's failure data: one of {model}, {probability} or nothing
// (no data yet); `placeholder` marks a guess.
export function setEventData(tree, id, { model, probability, placeholder } = {}) {
  return replaceNode(tree, id, (n) => {
    const out = { id: n.id, type: "event", label: n.label };
    if (n.note) out.note = n.note;
    if (model) out.model = model;
    else if (probability !== undefined && probability !== null && probability !== "") out.probability = Number(probability);
    if (placeholder) out.placeholder = true;
    return out;
  });
}

// Remove the row's node from its parent gate (the node itself goes when
// nothing else uses it). The top event can't be removed.
export function removeRow(tree, row) {
  if (!row.parent) return tree;
  const cut = replaceNode(tree, row.parent, (g) => ({ ...g, inputs: g.inputs.filter((_, i) => i !== row.index) }));
  return prune(cut);
}

// Move a row up or down among its siblings (dir -1 or +1).
export function moveRow(tree, row, dir) {
  if (!row.parent) return tree;
  return replaceNode(tree, row.parent, (g) => {
    const inputs = [...g.inputs];
    const j = row.index + dir;
    if (j < 0 || j >= inputs.length) return g;
    [inputs[row.index], inputs[j]] = [inputs[j], inputs[row.index]];
    return { ...g, inputs };
  });
}

// Whether a node lies under (or is) `ancestor`.
function under(tree, id, ancestor) {
  const nodes = byId(tree);
  const seen = new Set();
  const walk = (x) => {
    if (x === id) return true;
    if (seen.has(x) || !nodes[x]) return false;
    seen.add(x);
    return (nodes[x].inputs || []).some(walk);
  };
  return walk(ancestor);
}

// Move a row into the gate just above it among its siblings (an indent), as
// that gate's last input. Null when there's no gate there.
export function indentRow(tree, row) {
  if (!row.parent || row.index === 0) return null;
  const parent = nodeOf(tree, row.parent);
  const target = nodeOf(tree, parent.inputs[row.index - 1]);
  if (!target || target.type !== "gate" || (target.inputs || []).includes(row.id)) return null;
  if (under(tree, target.id, row.id)) return null;
  let next = replaceNode(tree, row.parent, (g) => ({ ...g, inputs: g.inputs.filter((_, i) => i !== row.index) }));
  next = replaceNode(next, target.id, (g) => ({ ...g, inputs: [...g.inputs, row.id] }));
  return next;
}

// Move a row out of its gate, to just after that gate in the gate above (an
// outdent). Null at the top level.
export function outdentRow(tree, rows, row) {
  if (!row.parent) return null;
  const parentRow = rows.find((r) => r.id === row.parent && row.key.startsWith(`${r.key}/`) && r.depth === row.depth - 1);
  if (!parentRow || !parentRow.parent) return null;
  const grand = nodeOf(tree, parentRow.parent);
  if (grand.inputs.includes(row.id)) return null;
  let next = replaceNode(tree, row.parent, (g) => ({ ...g, inputs: g.inputs.filter((_, i) => i !== row.index) }));
  next = replaceNode(next, grand.id, (g) => {
    const inputs = [...g.inputs];
    inputs.splice(parentRow.index + 1, 0, row.id);
    return { ...g, inputs };
  });
  return next;
}

// What still stops the tree being analysed, in words (the server says the same).
export function treeIssues(tree) {
  const out = [];
  for (const n of tree.nodes) {
    if (n.type === "gate") {
      const size = (n.inputs || []).length;
      if (!size) out.push({ id: n.id, text: `${n.label}: add its inputs` });
      else if (n.gate === "vote" && (n.k || 0) > size) out.push({ id: n.id, text: `${n.label}: needs ${n.k} of its inputs but has ${size}` });
    } else if (!n.model && (n.probability === undefined || n.probability === null)) {
      out.push({ id: n.id, text: `${n.label}: no failure data yet` });
    }
  }
  if (tree.nodes.length > MAX_NODES) out.push({ id: tree.top, text: `More than ${MAX_NODES} gates and basic events` });
  return out;
}

// A number in at most 4 significant figures, scientific when small ("8e-5").
const short = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  const r = Number(n.toPrecision(4));
  return r !== 0 && Math.abs(r) < 1e-3 ? r.toExponential() : String(r);
};

// One line about a basic event's data, for its row.
export function eventSummary(node, unit = "") {
  if (node.probability !== undefined && node.probability !== null) return `q = ${node.probability}`;
  const m = node.model;
  if (!m) return "No failure data";
  if (m.source === "saved" || m.modelId) return m.name ? `Saved model: ${m.name}` : "Saved model";
  const p = Object.fromEntries((m.params || []).map((x) => [x.name, x.value]));
  const u = unit ? ` /${unit.toLowerCase().replace(/s$/, "")}` : "";
  if (m.distribution_id === "exponential" && p.failure_rate != null) return `λ = ${short(p.failure_rate)}${u}`;
  if (m.distribution_id === "weibull" && p.alpha != null) return `Weibull α = ${short(p.alpha)}, β = ${short(p.beta)}`;
  return m.distribution || m.distribution_id || "Model";
}

// A gate's line in words: "OR · any of 3", "Vote · 2 of 3".
export function gateSummary(node) {
  const n = (node.inputs || []).length;
  if (node.gate === "vote") return `Vote · ${node.k} of ${n}`;
  if (node.gate === "and") return `AND · all of ${n}`;
  return `OR · any of ${n}`;
}
