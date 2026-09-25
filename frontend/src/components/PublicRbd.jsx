import { useMemo } from "react";
import ReactFlow, { Background, Controls, ReactFlowProvider } from "reactflow";
import "reactflow/dist/style.css";
import {
  RBD_NODE_TYPES,
  RbdCcfContext,
  RbdRepairableContext,
  RbdUnitContext,
} from "./RbdNodes.jsx";
import { AvailabilityView, Results, savedOn } from "./RbdCalculator.jsx";
import { normalizeRbdGraph } from "../rbdGraph.js";

// Read-only rendering of a publicly linked RBD: the diagram on a non-editable
// React Flow canvas (pan/zoom only, no drag/connect/select) using the builder's
// own node components, followed by the analysis the server computed — the same
// results panels the builder's Calculator tab shows.

const hasPosition = (n) =>
  n.position && Number.isFinite(n.position.x) && Number.isFinite(n.position.y);

// The persisted graph already carries the owner's layout; keep it when every
// node is placed, otherwise fall back to the shared auto-layout.
function canvasGraph(graph) {
  const norm = normalizeRbdGraph(graph);
  const raw = graph.nodes || [];
  if (raw.length && raw.every(hasPosition)) {
    const pos = new Map(raw.map((n) => [n.id, n.position]));
    norm.nodes = norm.nodes.map((n) => ({ ...n, position: pos.get(n.id) }));
  }
  return norm;
}

function Canvas({ graph }) {
  const { nodes, edges } = useMemo(() => canvasGraph(graph), [graph]);
  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={RBD_NODE_TYPES}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      zoomOnDoubleClick={false}
      fitView
      fitViewOptions={{ padding: 0.3 }}
      minZoom={0.2}
      proOptions={{ hideAttribution: true }}
    >
      <Background gap={22} color="#e8e7e2" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export default function PublicRbd({ a }) {
  const graph = a.graph || {};
  const unit = graph.unit || "";
  const repairable = !!graph.repairable;
  const analysis = a.analysis;

  // Component id -> common-cause beta, so grouped blocks show their CC badge.
  const ccfById = useMemo(() => {
    const out = {};
    for (const g of graph.ccf_groups || []) {
      for (const m of g.members || []) out[m] = g.beta;
    }
    return out;
  }, [graph.ccf_groups]);

  const nComponents = (graph.nodes || []).filter(
    (n) => n.type !== "input" && n.type !== "output"
  ).length;

  // Read R(t) off at the middle of the computed grid, as the builder prefills.
  const evalT = useMemo(() => {
    const time = analysis?.time;
    if (!time?.length) return null;
    return Number((time[time.length - 1] / 2).toPrecision(4));
  }, [analysis]);

  return (
    <RbdUnitContext.Provider value={unit}>
      <RbdRepairableContext.Provider value={repairable}>
        <RbdCcfContext.Provider value={ccfById}>
          <div className="card" style={{ padding: "0.9rem" }}>
            <div className="rbd-canvas public-rbd-canvas">
              <ReactFlowProvider>
                <Canvas graph={graph} />
              </ReactFlowProvider>
            </div>
            <div className="public-rbd-meta">
              <span>Time unit: <b>{unit || "unspecified"}</b></span>
              <span><b>{repairable ? "Repairable" : "Non-repairable"}</b> — {repairable ? "analysed for availability" : "analysed for reliability"}</span>
              <span><b>{nComponents}</b> block{nComponents === 1 ? "" : "s"}</span>
              {(graph.ccf_groups || []).length > 0 && (
                <span><b>{graph.ccf_groups.length}</b> common-cause group{graph.ccf_groups.length === 1 ? "" : "s"}</span>
              )}
            </div>
          </div>

          {a.analysis_error && (
            <div className="card note" style={{ marginTop: "1rem" }}>
              This diagram couldn't be analysed: {a.analysis_error}
            </div>
          )}

          {!analysis && a.analysis_note && (
            <div className="card note" style={{ marginTop: "1rem" }}>
              {a.analysis_note}
            </div>
          )}

          {analysis && analysis.kind === "repairable" && (
            <div className="card" style={{ marginTop: "1rem" }}>
              <h2>System availability</h2>
              {analysis.cached && (
                <p className="rbd-saved-note">{savedOn(analysis.computed_at)}</p>
              )}
              <AvailabilityView result={analysis} unit={unit} />
            </div>
          )}

          {analysis && analysis.kind !== "repairable" && (
            <div className="card rbd-calc" style={{ marginTop: "1rem" }}>
              <h2>System reliability</h2>
              <Results result={analysis} t={evalT} tMax={null} conditionalAge={analysis.conditional_age || 0} />
            </div>
          )}
        </RbdCcfContext.Provider>
      </RbdRepairableContext.Provider>
    </RbdUnitContext.Provider>
  );
}
