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
