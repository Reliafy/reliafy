// Pure helpers behind the RBD builder's toolbar and shortcuts (#299), kept
// out of the component so they can be tested on their own.

// The order blocks were clicked in, from React Flow's selection changes:
// ``prev`` = {ids, ordered}, ``selected`` = the ids selected now. A block
// added on its own (a click, a shift-click) joins the end; several at once (a
// box select) leave no click order, until the selection is cleared.
export function trackSelection(prev, selected) {
  const now = new Set(selected);
  if (!now.size) return { ids: [], ordered: true };
  const kept = (prev?.ids || []).filter((id) => now.has(id));
  const added = selected.filter((id) => !kept.includes(id));
  return {
    ids: [...kept, ...added],
    ordered: (prev?.ordered ?? true) && added.length <= 1,
  };
}

// Consecutive links of a series chain, in the order given: a → b → c.
export function chainPairs(order) {
  const out = [];
  for (let i = 0; i + 1 < order.length; i += 1) out.push([order[i], order[i + 1]]);
  return out;
}

// The component blocks "Repaired instantly" applies to (a repeated block
// is its original's, so not one of them).
const instantBlocks = (nodes) => nodes.filter((n) => n.type === "component" && !n.data?.repeat_of);

// Whether every component block is repaired instantly (false with none).
export function allInstant(nodes) {
  const blocks = instantBlocks(nodes);
  return blocks.length > 0 && blocks.every((n) => !!n.data?.instant_repair);
}

// Every component block repaired instantly (on) or by its repair model (off):
// "Repaired instantly", set once for the whole diagram.
export function setInstantRepair(nodes, on) {
  return nodes.map((n) => {
    if (n.type !== "component" || n.data?.repeat_of) return n;
    const { instant_repair: _old, ...rest } = n.data || {};
    return { ...n, data: on ? { ...rest, instant_repair: true } : rest };
  });
}

// ---- Adding a block in place (#282) ----------------------------------------
//
// "+ Add block" wires a new block in for you: after a block (in series), on
// a connection (in series), or alongside a block or a line of blocks (in
// parallel). Each helper takes the canvas's {nodes, edges} and returns new
// ones; nothing here knows about React Flow beyond its node and edge shapes.
// Parallel branches merge into a junction (a 1-of-k gate), as the samples
// draw them: a voting gate downstream then still counts the pair as one vote.

// The steps the auto-layout uses between columns and rows.
export const STEP_X = 280;
export const STEP_Y = 150;
// A block's size before React Flow has measured it (a component's, as drawn).
const BLOCK = { w: 171, h: 95 };
const JUNCTION_W = 26;
const PAD = 16;

const isEnd = (n) => n?.type === "input" || n?.type === "output";
const isGate = (n) => n?.type === "knode";
export const isJunction = (n) => isGate(n) && Number(n.data?.n ?? 1) === 1;

const sizeOf = (n) => ({
  w: n.width ?? (isJunction(n) ? JUNCTION_W : BLOCK.w),
  h: n.height ?? BLOCK.h,
});
const boxOf = (n) => ({ ...n.position, ...sizeOf(n) });
const overlap = (a, b) =>
  a.x < b.x + b.w + PAD && b.x < a.x + a.w + PAD && a.y < b.y + b.h + PAD && b.y < a.y + a.h + PAD;

// An edge id that isn't taken yet.
function edgeId(source, target, taken) {
  let id = `e-${source}-${target}`;
  for (let i = 2; taken.has(id); i += 1) id = `e-${source}-${target}-${i}`;
  taken.add(id);
  return id;
}

// A new edge, keeping the look (type, arrow) of the one it replaces.
function link(like, source, target, taken) {
  const { id: _id, selected: _sel, source: _s, target: _t, sourceHandle: _sh, targetHandle: _th, ...look } = like || {};
  return { ...look, id: edgeId(source, target, taken), source, target };
}

// Every node reachable downstream of ``ids`` (not ``ids`` themselves).
export function downstreamOf(edges, ids) {
  const start = new Set(ids);
  const out = new Set();
  const stack = [...ids];
  while (stack.length) {
    const id = stack.pop();
    for (const e of edges) {
      if (e.source !== id || out.has(e.target) || start.has(e.target)) continue;
      out.add(e.target);
      stack.push(e.target);
    }
  }
  return out;
}

// Place ``node`` at ``pos`` without covering another block: first by moving
// the ``shift`` blocks right a step (to make room downstream), then, if
// something is still in the way, by moving the new block down a row.
function place(nodes, node, pos, shift = new Set()) {
  let moved = nodes;
  const others = () => moved.filter((n) => n.id !== node.id);
  const box = { ...pos, ...sizeOf(node) };
  if (shift.size && others().some((n) => overlap(box, boxOf(n)))) {
    moved = moved.map((n) => (shift.has(n.id) ? { ...n, position: { x: n.position.x + STEP_X, y: n.position.y } } : n));
  }
  for (let i = 0; i < 40 && others().some((n) => overlap(box, boxOf(n))); i += 1) box.y += STEP_Y;
  return { nodes: moved, position: { x: box.x, y: box.y } };
}

const selectOnly = (nodes, id) => nodes.map((n) => (n.selected === (n.id === id) ? n : { ...n, selected: n.id === id }));
const unselectEdges = (edges) => edges.map((e) => (e.selected ? { ...e, selected: false } : e));

// The selected blocks as one series line, in order: ``{ok: true, order}``,
// or ``{ok: false, reason}``. A line is joined one after another, with no
// branch leaving or joining it part-way.
export function chainOf(nodes, edges, ids) {
  const sel = new Set(ids);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  if (ids.some((id) => isEnd(byId.get(id))))
    return { ok: false, reason: "Input and Output are the diagram's ends; select only blocks between them." };
  if (ids.length < 2) return { ok: false, reason: "Select two or more blocks joined one after another." };
  const notALine = "The selected blocks aren't one line in series: select blocks joined one after another, with no branch in between.";
  const next = new Map();
  const prev = new Map();
  for (const e of edges) {
    if (!sel.has(e.source) || !sel.has(e.target) || e.source === e.target) continue;
    if (next.has(e.source) || prev.has(e.target)) return { ok: false, reason: notALine };
    next.set(e.source, e.target);
    prev.set(e.target, e.source);
  }
  const starts = ids.filter((id) => !prev.has(id));
  if (starts.length !== 1) return { ok: false, reason: notALine };
  const order = [starts[0]];
  while (next.has(order[order.length - 1]) && order.length <= ids.length) order.push(next.get(order[order.length - 1]));
  if (order.length !== ids.length) return { ok: false, reason: notALine };
  // No branch leaves or joins the line part-way.
  for (let i = 0; i + 1 < order.length; i += 1) {
    const outs = edges.filter((e) => e.source === order[i]).length;
    const ins = edges.filter((e) => e.target === order[i + 1]).length;
    if (outs !== 1 || ins !== 1) return { ok: false, reason: notALine };
  }
  return { ok: true, order };
}

// What "+ Add block" can do in place for the current selection: the items
// to show, each {key, label, reason} (``reason`` set when it can't apply,
// as the item's title), and the blocks or connection they act on. Null when
// nothing is selected. A network has no junctions, so its parallel adds
// share the block's connections instead (see insertAlongside).
export function inPlaceItems(nodes, edges) {
  const picked = nodes.filter((n) => n.selected);
  if (!picked.length) {
    const lines = edges.filter((e) => e.selected);
    if (!lines.length) return null;
    return {
      edge: lines.length === 1 ? lines[0].id : null,
      items: [{
        key: "split", label: "Insert on this line (in series)",
        reason: lines.length === 1 ? null : "Select one connection to insert a block on it.",
      }],
    };
  }
  if (picked.length === 1) {
    const n = picked[0];
    const end = isEnd(n) ? "Input and Output are the diagram's ends; select a block between them." : null;
    return {
      ids: [n.id],
      items: [
        { key: "after", label: "Add after (in series)", reason: end },
        {
          key: "alongside", label: "Add alongside (in parallel)",
          reason: end || (isGate(n) ? "Junctions and voting nodes never fail, so there's nothing to put alongside one." : null),
        },
      ],
    };
  }
  const chain = chainOf(nodes, edges, picked.map((n) => n.id));
  return {
    ids: chain.ok ? chain.order : picked.map((n) => n.id),
    items: [{ key: "bypass", label: "Add alongside the selection (in parallel)", reason: chain.ok ? null : chain.reason }],
  };
}

// Series, after ``id``: the new block takes over everything ``id`` fed, and
// ``id`` feeds it. It goes a column to the right; the blocks downstream move
// right a column only if they're in the way.
export function insertAfter({ nodes, edges }, id, block) {
  const s = nodes.find((n) => n.id === id);
  if (!s || s.type === "output") return { nodes, edges };
  const taken = new Set(edges.map((e) => e.id));
  const outs = edges.filter((e) => e.source === id);
  const kept = edges.filter((e) => e.source !== id);
  const moved = outs.map((e) => link(e, block.id, e.target, taken));
  const sz = sizeOf(block);
  const pos = { x: s.position.x + STEP_X, y: s.position.y + (sizeOf(s).h - sz.h) / 2 };
  const placed = place(nodes, block, pos, downstreamOf(edges, [id]));
  return {
    nodes: selectOnly([...placed.nodes, { ...block, position: placed.position }], block.id),
    edges: unselectEdges([...kept, link(outs[0], id, block.id, taken), ...moved]),
  };
}

// Series, on a connection: the new block splits it.
export function insertOnEdge({ nodes, edges }, edgeIdToSplit, block) {
  const e = edges.find((x) => x.id === edgeIdToSplit);
  if (!e) return { nodes, edges };
  const u = nodes.find((n) => n.id === e.source);
  const v = nodes.find((n) => n.id === e.target);
  if (!u || !v) return { nodes, edges };
  const taken = new Set(edges.map((x) => x.id));
  const sz = sizeOf(block);
  const midY = (u.position.y + sizeOf(u).h / 2 + v.position.y + sizeOf(v).h / 2) / 2 - sz.h / 2;
  const gap = v.position.x - u.position.x;
  const x = gap >= 2 * STEP_X ? u.position.x + gap / 2 : u.position.x + STEP_X;
  const shift = new Set([v.id, ...downstreamOf(edges, [v.id])]);
  shift.delete(u.id);
  const placed = place(nodes, block, { x, y: midY }, shift);
  return {
    nodes: selectOnly([...placed.nodes, { ...block, position: placed.position }], block.id),
    edges: unselectEdges([
      ...edges.filter((x2) => x2.id !== e.id),
      link(e, u.id, block.id, taken),
      link(e, block.id, v.id, taken),
    ]),
  };
}

// Parallel, alongside a block or a line of blocks (``order``, first to
// last): the new block is fed by whatever feeds the first and joins the
// line again after the last, through a junction — the one already there if
// the last block's only successor is a junction, else a new one
// (``junctionId``) in front of what the last block fed. ``junctions: false``
// (a network) shares the line's connections directly instead. The new block
// goes a row below the line.
export function insertAlongside({ nodes, edges }, order, block, { junctionId, junctions = true } = {}) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const line = order.map((id) => byId.get(id)).filter(Boolean);
  if (!line.length || line.some(isEnd)) return { nodes, edges };
  const first = line[0].id;
  const last = line[line.length - 1].id;
  const taken = new Set(edges.map((e) => e.id));
  const ins = edges.filter((e) => e.target === first);
  const outs = edges.filter((e) => e.source === last);

  // A row below the line, centred under it.
  const sz = sizeOf(block);
  const xs = line.map((n) => n.position.x);
  const bottom = Math.max(...line.map((n) => n.position.y + sizeOf(n).h));
  const placed = place(nodes, block, { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: bottom + STEP_Y - sz.h });
  let nextNodes = [...placed.nodes, { ...block, position: placed.position }];
  let nextEdges = [...edges, ...ins.map((e) => link(e, e.source, block.id, taken))];

  const succ = outs.length === 1 ? byId.get(outs[0].target) : null;
  if (!junctions) {
    nextEdges.push(...outs.map((e) => link(e, block.id, e.target, taken)));
  } else if (succ && isJunction(succ)) {
    // Join the junction that's already there: one more branch into it.
    nextEdges.push(link(outs[0], block.id, succ.id, taken));
    const k = nextEdges.filter((e) => e.target === succ.id).length;
    nextNodes = nextNodes.map((n) => (n.id === succ.id ? { ...n, data: { ...n.data, k } } : n));
  } else if (outs.length) {
    // A new junction just after the line, between it and the new block.
    const lastNode = byId.get(last);
    const jy = (lastNode.position.y + sizeOf(lastNode).h / 2 + placed.position.y + sz.h / 2) / 2 - BLOCK.h / 2;
    const junction = { id: junctionId, type: "knode", data: { n: 1, k: 2 }, position: { x: 0, y: 0 } };
    const jx = lastNode.position.x + sizeOf(lastNode).w + (STEP_X - BLOCK.w - JUNCTION_W) / 2;
    const spot = place(nextNodes, junction, { x: jx, y: jy }, downstreamOf(edges, [last]));
    nextNodes = [...spot.nodes, { ...junction, position: spot.position }];
    nextEdges = [
      ...nextEdges.filter((e) => e.source !== last),
      link(outs[0], last, junctionId, taken),
      link(outs[0], block.id, junctionId, taken),
      ...outs.map((e) => link(e, junctionId, e.target, taken)),
    ];
  }
  return { nodes: selectOnly(nextNodes, block.id), edges: unselectEdges(nextEdges) };
}
