// Whether a diagram has anything to analyse yet (#271). A new diagram is just
// Input and Output; until at least one block sits on a path from Input to
// Output, every tab (Calculator, Fault tree, Design, Outage history, What to
// improve, Maintenance intervals) shows a friendly next step instead of
// calling the API and showing its 422. Mirrors backend/services/rbd_graph.py
// (diagram_gap), which gives API and MCP callers the same answer in words.

export const NO_BLOCKS = "no_blocks";
export const NOT_CONNECTED = "not_connected";

// NO_BLOCKS when there are no blocks besides Input and Output, NOT_CONNECTED
// when no block lies on a path from Input to Output, else null. A diagram
// without exactly one Input and one Output is left to validation (null).
export function diagramGap(graph) {
  const nodes = (graph?.nodes || []).filter((n) => n && typeof n === "object");
  const blocks = new Set(nodes.filter((n) => n.type !== "input" && n.type !== "output").map((n) => n.id));
  if (!blocks.size) return NO_BLOCKS;
  const inputs = nodes.filter((n) => n.type === "input");
  const outputs = nodes.filter((n) => n.type === "output");
  if (inputs.length !== 1 || outputs.length !== 1) return null;
  const forward = new Map();
  const backward = new Map();
  for (const e of graph?.edges || []) {
    if (e?.source == null || e?.target == null) continue;
    if (!forward.has(e.source)) forward.set(e.source, []);
    if (!backward.has(e.target)) backward.set(e.target, []);
    forward.get(e.source).push(e.target);
    backward.get(e.target).push(e.source);
  }
  const reach = (start, adjacency) => {
    const seen = new Set([start]);
    const stack = [start];
    while (stack.length) {
      for (const next of adjacency.get(stack.pop()) || []) {
        if (!seen.has(next)) {
          seen.add(next);
          stack.push(next);
        }
      }
    }
    return seen;
  };
  const fromInput = reach(inputs[0].id, forward);
  const toOutput = reach(outputs[0].id, backward);
  for (const id of blocks) if (fromInput.has(id) && toOutput.has(id)) return null;
  return NOT_CONNECTED;
}
