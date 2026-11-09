import { useEffect, useMemo, useRef } from "react";
import ReactFlow, { Background, Controls, ReactFlowProvider, useReactFlow } from "reactflow";
import "reactflow/dist/style.css";
import { RBD_NODE_TYPES, RbdCcfContext, RbdRepairableContext, RbdUnitContext } from "./RbdNodes.jsx";
import { normalizeRbdGraph } from "../rbdGraph.js";
import { isNetwork, undirectedEdges } from "../rbdMission.js";

// A diagram drawn read-only (pan and zoom, no dragging, connecting or picking) with the builder's
// own node components: a shared RBD page (PublicRbd.jsx) and a mission's "Show the RBD"
// (MissionPane.jsx) both draw it here, so a block looks the same everywhere it's shown.
//
//   graph   the saved graph (its layout kept when every node is placed)
//   full    in full screen (the diagram fits itself again when it changes)
//   dim     block ids drawn faded: a mission phase's blocks it doesn't need
//   label   the canvas's name for screen readers

const hasPosition = (n) => n.position && Number.isFinite(n.position.x) && Number.isFinite(n.position.y);

// The persisted graph already carries the owner's layout; keep it when every node is placed,
// otherwise fall back to the shared auto-layout.
export function canvasGraph(graph) {
  const norm = normalizeRbdGraph(graph);
  const raw = graph.nodes || [];
  if (raw.length && raw.every(hasPosition)) {
    const pos = new Map(raw.map((n) => [n.id, n.position]));
    norm.nodes = norm.nodes.map((n) => ({ ...n, position: pos.get(n.id) }));
  }
  return norm;
}

function Canvas({ graph, full, dim }) {
  const { nodes, edges } = useMemo(() => canvasGraph(graph), [graph]);
  const shownNodes = useMemo(() => (dim?.size ? nodes.map((n) => (dim.has(n.id) || dim.has(n.data?.repeat_of)
    ? { ...n, className: `${n.className || ""} rbd-node-dim`.trim() } : n)) : nodes), [nodes, dim]);
  const { fitView } = useReactFlow();
  const seen = useRef(full);
  useEffect(() => {
    if (seen.current === full) return undefined;
    seen.current = full;
    let id = window.requestAnimationFrame(() => {
      id = window.requestAnimationFrame(() => fitView({ padding: 0.3, duration: 200 }));
    });
    return () => window.cancelAnimationFrame(id);
  }, [full, fitView]);
  // A network's links work both ways: no arrows (#160).
  const shown = useMemo(() => (isNetwork(graph) ? undirectedEdges(edges) : edges), [graph, edges]);
  return (
    <ReactFlow nodes={shownNodes} edges={shown} nodeTypes={RBD_NODE_TYPES} nodesDraggable={false} nodesConnectable={false}
               elementsSelectable={false} zoomOnDoubleClick={false} fitView fitViewOptions={{ padding: 0.3 }} minZoom={0.2}
               proOptions={{ hideAttribution: true }}>
      <Background gap={22} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

// The canvas alone, inside the caller's own contexts (the unit, repairable, common-cause groups).
export function RbdDiagramCanvas({ graph, full = false, dim = null }) {
  return (
    <ReactFlowProvider>
      <Canvas graph={graph} full={full} dim={dim} />
    </ReactFlowProvider>
  );
}

// The canvas with the contexts the nodes read, from the graph itself.
export default function RbdDiagramView({ graph, full = false, dim = null, label = "The RBD", className = "" }) {
  const ccfById = useMemo(() => {
    const out = {};
    for (const g of graph?.ccf_groups || []) for (const m of g.members || []) out[m] = g.beta;
    return out;
  }, [graph?.ccf_groups]);
  return (
    <RbdUnitContext.Provider value={graph?.unit || ""}>
      <RbdRepairableContext.Provider value={!!graph?.repairable}>
        <RbdCcfContext.Provider value={ccfById}>
          <div className={"rbd-canvas rbd-diagram-view" + (className ? ` ${className}` : "")} role="img" aria-label={label}>
            <RbdDiagramCanvas graph={graph || { nodes: [], edges: [] }} full={full} dim={dim} />
          </div>
        </RbdCcfContext.Provider>
      </RbdRepairableContext.Provider>
    </RbdUnitContext.Provider>
  );
}
