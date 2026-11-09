import { useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, { Background, Controls, ReactFlowProvider, useReactFlow } from "reactflow";
import "reactflow/dist/style.css";
import {
  RBD_NODE_TYPES,
  RbdCcfContext,
  RbdRepairableContext,
  RbdUnitContext,
} from "./RbdNodes.jsx";
import { AvailabilityView, Results, savedOn } from "./RbdCalculator.jsx";
import { normalizeRbdGraph } from "../rbdGraph.js";
import { isNetwork, undirectedEdges } from "../rbdMission.js";
import { PYTHON_EXPORT_TIP, downloadPublicRbdPython } from "../api.js";
import useFullScreen from "./useFullScreen.js";
import FullScreenButton from "./FullScreenButton.jsx";

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

function Canvas({ graph, full }) {
  const { nodes, edges } = useMemo(() => canvasGraph(graph), [graph]);
  // Into or out of full screen: fit the diagram to the new size.
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
    <ReactFlow
      nodes={nodes}
      edges={shown}
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
      <Background gap={22} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

// "Download as Python" for a public RBD — free, no sign-in needed.
function DownloadPython({ token, unlock }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      await downloadPublicRbdPython(token, unlock);
    } catch (e) {
      setError(e.message || "Download failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="public-rbd-download">
      <button className="secondary sm" onClick={onClick} disabled={busy} title={PYTHON_EXPORT_TIP}>
        {busy ? "Preparing…" : "Download as Python"}
      </button>
      {error && <span className="public-rbd-download-err" role="alert">{error}</span>}
    </span>
  );
}

export default function PublicRbd({ a, token, unlock }) {
  const graph = a.graph || {};
  // The diagram alone, full screen, for a big one (read only, as here).
  const fullRef = useRef(null);
  const fullBtnRef = useRef(null);
  const { full, toggle } = useFullScreen(fullRef, { returnFocus: fullBtnRef });
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
            <div ref={fullRef} className={"public-rbd-canvas-wrap" + (full ? " is-full" : "")}>
              <div className="rbd-canvas public-rbd-canvas">
                <ReactFlowProvider>
                  <Canvas graph={graph} full={full} />
                </ReactFlowProvider>
              </div>
              <FullScreenButton ref={fullBtnRef} full={full} onClick={toggle} shortcut="" compact />
            </div>
            <div className="public-rbd-meta">
              <span>Time unit: <b>{unit || "unspecified"}</b></span>
              <span><b>{repairable ? "Repairable" : "Non-repairable"}</b> — {repairable ? "analysed for availability" : "analysed for reliability"}</span>
              <span><b>{nComponents}</b> block{nComponents === 1 ? "" : "s"}</span>
              {(graph.ccf_groups || []).length > 0 && (
                <span><b>{graph.ccf_groups.length}</b> common-cause group{graph.ccf_groups.length === 1 ? "" : "s"}</span>
              )}
              {token && <DownloadPython token={token} unlock={unlock} />}
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
