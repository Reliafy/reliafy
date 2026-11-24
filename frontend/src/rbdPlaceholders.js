// How much of a diagram has no real life model (none, or a placeholder), in words, for the RBD
// Calculator's note. A block with none stops the calculation (the check lists it): no life is invented.
//
// Placeholders are counted through every sub-system by the server (`placeholder_blocks` on the
// diagram's check: {basic, placeholders, names, more, mostly}); without one yet, only the
// diagram's own blocks can be counted here, and a diagram with sub-systems says so rather than
// undercount. Why: a diagram of six sub-systems whose 27 blocks are all placeholders once said
// "1 block uses placeholder parameters" (W2, 19 Nov 2026).

const n = (count) => Number(count).toLocaleString("en-AU");

export const hasSubsystems = (graph) => (graph?.nodes || []).some((x) => x.type === "subsystem" || x.data?.rbd?.id);

// {text, mostly} or null when nothing is a placeholder.
export function placeholderNote(graph, held = null) {
  if (held && Number(held.placeholders) > 0) {
    const ph = Number(held.placeholders);
    const basic = Number(held.basic) || ph;
    const mostly = !!held.mostly || ph * 2 >= basic;
    const count = basic === 1 ? "Its one block has no real life model yet"
      : `${n(ph)} of ${n(basic)} basic blocks ${ph === 1 ? "has" : "have"} no real life model yet`;
    return {
      mostly,
      text: `${count}: the results aren't real until each has one. Give each a model, or mark a block that never fails as Working under Status.`,
    };
  }
  const own = (graph?.nodes || []).filter((x) => x.data?.model?.placeholder).length;
  if (!own) return null;
  const blocks = (graph?.nodes || []).filter((x) => !["input", "output", "knode", "junction"].includes(x.type)).length;
  const inside = hasSubsystems(graph) ? " (and maybe more inside its sub-systems)" : "";
  return {
    mostly: blocks > 0 && own * 2 >= blocks,
    text: `${own === 1 ? "1 block has" : `${n(own)} blocks have`} only placeholder parameters${inside}: the results aren't real until each has a real model.`,
  };
}
