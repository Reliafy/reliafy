import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { caption, nodeSize, WARN } from "../dataModel.js";

// The Data model page's diagram: one circle per kind of thing, one arrow per
// connection, drawn with cytoscape.js (MIT), which loads only when this
// diagram is first shown. Drag a circle to move it; scroll or pinch to zoom;
// drag the background to pan. Clicking a circle or an arrow calls onSelect.
//
// The parent drives it through the ref: fit(), relayout(), png() (a data URL)
// and positions() (where each node is, for the Arrows export).

const INK = "#14171c";
const MUTED = "#5f6670";
const ACC = "#2f6df6";
const SURF = "#ffffff";

const STYLE = [
  {
    selector: "node",
    style: {
      "background-color": "data(colour)",
      width: "data(size)",
      height: "data(size)",
      label: "data(caption)",
      color: "#ffffff",
      "font-family": "Inter, system-ui, sans-serif",
      "font-size": 11,
      "font-weight": 600,
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "wrap",
      "text-max-width": "data(textWidth)",
      "border-width": 0,
      "overlay-opacity": 0,
    },
  },
  { selector: "node.dashed", style: { "border-width": 3, "border-style": "dashed", "border-color": INK, "background-opacity": 0.55 } },
  { selector: "node.warn", style: { "border-width": 4, "border-color": WARN } },
  {
    selector: "edge",
    style: {
      width: 1.6,
      "curve-style": "bezier",
      "control-point-step-size": 48,
      "line-color": MUTED,
      "target-arrow-color": MUTED,
      "target-arrow-shape": "triangle",
      "arrow-scale": 1.1,
      label: "data(type)",
      "font-family": "IBM Plex Mono, ui-monospace, monospace",
      "font-size": 10,
      color: INK,
      "text-rotation": "autorotate",
      "text-background-color": SURF,
      "text-background-opacity": 0.92,
      "text-background-padding": 2,
      "loop-direction": "-45deg",
      "loop-sweep": "-60deg",
      "overlay-opacity": 0,
    },
  },
  // A loop (a kind connected to itself) wide enough to see past a big circle.
  { selector: "edge.loop", style: { "control-point-step-size": "data(loopSize)", "loop-sweep": "-50deg", "loop-direction": "-30deg" } },
  { selector: "edge.dashed", style: { "line-style": "dashed", "line-dash-pattern": [6, 4] } },
  { selector: "edge.warn", style: { "line-color": WARN, "target-arrow-color": WARN, width: 2.4, color: WARN } },
  { selector: ".dim", style: { opacity: 0.18 } },
  { selector: "node.hit", style: { "border-width": 4, "border-color": ACC, "border-style": "solid" } },
  { selector: "edge.hit", style: { width: 3.2, "line-color": ACC, "target-arrow-color": ACC } },
  { selector: "node:selected", style: { "border-width": 5, "border-color": ACC, "border-style": "double" } },
  { selector: "edge:selected", style: { width: 3.6, "line-color": ACC, "target-arrow-color": ACC, color: ACC } },
];

const LAYOUT = {
  name: "cose",
  animate: false,
  fit: true,
  padding: 36,
  nodeRepulsion: () => 90000,
  idealEdgeLength: () => 150,
  edgeElasticity: () => 80,
  nodeOverlap: 24,
  gravity: 0.6,
  numIter: 1500,
  randomize: false,
};

function elementsFor(model, showCounts) {
  const max = Math.max(0, ...model.nodes.map((n) => n.count || 0));
  const nodes = model.nodes.map((n) => {
    const size = nodeSize(n.count, max);
    return {
      group: "nodes",
      data: { id: n.id, colour: n.colour, size, textWidth: `${Math.max(40, size - 8)}px`, caption: caption(n, showCounts) },
      classes: [n.dashed && "dashed", n.warn && "warn"].filter(Boolean).join(" "),
    };
  });
  const sizes = new Map(nodes.map((n) => [n.data.id, n.data.size]));
  const edges = model.edges.map((e) => ({
    group: "edges",
    data: { id: e.id, source: e.from, target: e.to, type: e.type, loopSize: Math.round((sizes.get(e.from) || 54) * 0.9 + 30) },
    classes: [e.dashed && "dashed", e.warn && "warn", e.loop && "loop"].filter(Boolean).join(" "),
  }));
  return [...nodes, ...edges];
}

const DataModelDiagram = forwardRef(function DataModelDiagram(
  { model, showCounts, highlight, selected, onSelect, label },
  ref,
) {
  const box = useRef(null);
  const cyRef = useRef(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const [state, setState] = useState("loading");

  // Load the library once and draw.
  useEffect(() => {
    let alive = true;
    let cy = null;
    import("cytoscape")
      .then(({ default: cytoscape }) => {
        if (!alive || !box.current) return;
        cy = cytoscape({
          container: box.current,
          elements: elementsFor(model, showCounts),
          style: STYLE,
          layout: LAYOUT,
          wheelSensitivity: 0.3,
          minZoom: 0.15,
          maxZoom: 3,
          boxSelectionEnabled: false,
          selectionType: "single",
        });
        cy.on("tap", "node", (ev) => onSelectRef.current?.({ kind: "node", id: ev.target.id() }));
        cy.on("tap", "edge", (ev) => onSelectRef.current?.({ kind: "edge", id: ev.target.id() }));
        cy.on("tap", (ev) => {
          if (ev.target === cy) onSelectRef.current?.(null);
        });
        cyRef.current = cy;
        setState("ready");
      })
      .catch(() => alive && setState("failed"));
    return () => {
      alive = false;
      cyRef.current = null;
      cy?.destroy();
    };
    // Drawn afresh when the model changes (a new view); counts and highlight below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const byId = new Map(model.nodes.map((n) => [n.id, n]));
    cy.nodes().forEach((n) => {
      const m = byId.get(n.id());
      if (m) n.data("caption", caption(m, showCounts));
    });
  }, [showCounts, model, state]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("dim hit");
    if (!highlight) return;
    cy.elements().addClass("dim");
    cy.nodes().filter((n) => highlight.nodes.has(n.id())).removeClass("dim").addClass("hit");
    cy.edges().filter((e) => highlight.edges.has(e.id())).removeClass("dim").addClass("hit");
  }, [highlight, state]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().unselect();
    if (selected) cy.getElementById(selected.id).select();
  }, [selected, state]);

  useImperativeHandle(ref, () => ({
    fit: () => cyRef.current?.fit(undefined, 36),
    relayout: () => cyRef.current?.layout({ ...LAYOUT, randomize: true }).run(),
    png: () => cyRef.current?.png({ full: true, scale: 2, bg: SURF }),
    positions: () => {
      const out = {};
      cyRef.current?.nodes().forEach((n) => {
        out[n.id()] = { ...n.position() };
      });
      return out;
    },
    ready: () => Boolean(cyRef.current),
  }), []);

  return (
    <div className="dm-canvas-wrap">
      <div ref={box} className="dm-canvas" role="img" aria-label={label} data-state={state} />
      {state === "loading" && <div className="dm-canvas-note muted">Drawing the diagram…</div>}
      {state === "failed" && (
        <div className="dm-canvas-note">The diagram couldn't be drawn here. The Table view shows the same thing.</div>
      )}
    </div>
  );
});

export default DataModelDiagram;
