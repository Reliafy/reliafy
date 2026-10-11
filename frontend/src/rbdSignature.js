// Signatures of an RBD, to tell when what was checked or calculated is no
// longer the diagram on screen.

// A structural signature of the diagram (ignoring node positions) so callers
// can tell when it has changed since the last validation or calculation.
export function graphSignature(graph) {
  return JSON.stringify({
    nodes: (graph.nodes || []).map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data,
    })),
    edges: (graph.edges || []).map((e) => ({
      source: e.source,
      target: e.target,
    })),
    unit: graph.unit || "",
    // Diagram-level costs (#99) change a repairable diagram's results.
    ...(graph.costs ? { costs: graph.costs } : {}),
    // A network is checked as one; phases add their own warnings (#160).
    ...(graph.network ? { network: graph.network } : {}),
    ...(graph.phases ? { phases: graph.phases } : {}),
    // Repairable or not, and the common-cause groups, change the check and
    // the answer alike.
    ...(graph.repairable ? { repairable: true } : {}),
    ...(graph.ccf_groups?.length ? { ccf_groups: graph.ccf_groups } : {}),
  });
}

// Whether a shown result is out of date: the diagram has changed since the
// check (``checkStale``), or since the result was calculated (``resultSig``,
// the diagram's signature then, against ``graphSig``, now). A diagram that
// changed and passed a new check still hasn't been calculated.
export function resultIsStale({ result, resultSig, graphSig, checkStale = false }) {
  if (checkStale) return true;
  return result != null && resultSig != null && resultSig !== graphSig;
}
