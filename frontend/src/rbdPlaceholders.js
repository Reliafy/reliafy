// How much of a diagram rests on placeholders, in words, for the RBD Calculator's note.
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
    const count = basic === 1 ? "Its one block is a placeholder"
      : `${n(ph)} of ${n(basic)} basic blocks ${ph === 1 ? "is a placeholder" : "are placeholders"}`;
    return {
      mostly,
      text: mostly
        ? `${count}: most of this answer rests on invented lives, so it isn't a real figure. Give the blocks real models first.`
        : `${count}: results are illustrative until you set real values.`,
    };
  }
  const own = (graph?.nodes || []).filter((x) => x.data?.model?.placeholder).length;
  if (!own) return null;
  const blocks = (graph?.nodes || []).filter((x) => !["input", "output", "knode", "junction"].includes(x.type)).length;
  const inside = hasSubsystems(graph) ? " (and maybe more inside its sub-systems)" : "";
  return {
    mostly: blocks > 0 && own * 2 >= blocks,
    text: `${own === 1 ? "1 block uses" : `${n(own)} blocks use`} placeholder parameters${inside}: results are illustrative until you set real values.`,
  };
}
