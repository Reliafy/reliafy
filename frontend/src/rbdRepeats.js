// Repeated blocks (#102): one component drawn in several places of a diagram,
// such as a power supply feeding two trains. A linked copy is a component node
// whose data.repeat_of names the component it repeats; it has its own position
// and connections but no model of its own — the analysis treats every
// appearance as the one component. Pure helpers for the builder.

export const REPEAT_MARK = "↺";

// The id of the component a node stands for: its original when it is a copy.
export function originalId(nodes, id) {
  const node = nodes.find((n) => n.id === id);
  return node?.data?.repeat_of || id;
}

export const isRepeat = (node) => !!node?.data?.repeat_of;

// A new linked copy of `id` (or of its original, when `id` is itself a copy),
// placed just below it.
export function makeRepeat(nodes, id, newId) {
  const source = nodes.find((n) => n.id === id);
  if (!source) return null;
  const origId = source.data?.repeat_of || source.id;
  const original = nodes.find((n) => n.id === origId) || source;
  return {
    id: newId,
    type: "component",
    // The label is the original's (kept for readers without the canvas); the
    // canvas always shows the original's current label and model.
    data: { label: original.data?.label || origId, repeat_of: origId },
    position: { x: source.position.x + 30, y: source.position.y + 120 },
    sourcePosition: "right",
    targetPosition: "left",
  };
}

// Deleting a component that has copies keeps the component: its first
// remaining copy takes over its model, label and pinned state and becomes the
// original, and the other copies repeat that one. Returns the nodes with the
// copies of `removedIds` promoted (the removed nodes themselves are left for
// the caller to drop).
export function promoteRepeats(nodes, removedIds) {
  const removed = new Set(removedIds);
  const heirs = new Map(); // removed original id -> promoted copy id
  for (const n of nodes) {
    const target = n.data?.repeat_of;
    if (target && removed.has(target) && !removed.has(n.id) && !heirs.has(target)) {
      heirs.set(target, n.id);
    }
  }
  if (!heirs.size) return nodes;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return nodes.map((n) => {
    const target = n.data?.repeat_of;
    if (!target || !heirs.has(target) || removed.has(n.id)) return n;
    const heir = heirs.get(target);
    if (n.id === heir) {
      const { repeat_of: _unused, ...own } = n.data;
      const { label, model, repair, state } = byId.get(target).data || {};
      return { ...n, data: { ...own, label, model, ...(repair ? { repair } : {}), ...(state ? { state } : {}) } };
    }
    return { ...n, data: { ...n.data, repeat_of: heir } };
  });
}

// The ids of the linked copies of component `id`.
export function copiesOf(nodes, id) {
  return nodes.filter((n) => n.data?.repeat_of === id).map((n) => n.id);
}
