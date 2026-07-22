import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MiniMap,
  Panel,
  Position,
  ReactFlowProvider,
  addEdge,
  useReactFlow,
  useEdgesState,
  useNodesState,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import LifeModelModal from "../components/LifeModelModal.jsx";
import KNodeModal from "../components/KNodeModal.jsx";
import CountModal from "../components/CountModal.jsx";
import StandbyModal from "../components/StandbyModal.jsx";
import SubsystemModal from "../components/SubsystemModal.jsx";
import RbdSaveModal from "../components/RbdSaveModal.jsx";
import RbdCalculator from "../components/RbdCalculator.jsx";
import ValidationPanel, { graphSignature } from "../components/RbdValidation.jsx";
import { saveRbd, getRbd, validateRbd } from "../api.js";
import { ShareButton } from "../components/ShareDialog.jsx";
import CopyId from "../components/CopyId.jsx";
import { registerRbdCanvas } from "../rbdBridge.js";
import { normalizeRbdGraph } from "../rbdGraph.js";

// The RBD's unit is provided to node components so they can flag a model whose
// unit doesn't match.
const RbdUnitContext = createContext("");

const TIME_UNITS = [
  "Seconds",
  "Minutes",
  "Hours",
  "Days",
  "Weeks",
  "Months",
  "Years",
  "Cycles",
];

// Warn only when a model has an explicit unit that differs from the RBD unit.
// A unitless model (e.g. entered as parameters) assumes the RBD unit — good.
function unitWarning(model, rbdUnit) {
  if (!rbdUnit || !model) return null;
  const u = (model.unit || "").trim();
  if (!u || u === rbdUnit) return null;
  return `Unit mismatch — model is ${u}, RBD is ${rbdUnit}`;
}

function UnitWarn({ title }) {
  return (
    <span className="rbd-unit-warn" title={title} aria-label={title}>
      ⚠
    </span>
  );
}

// Manual working/failed status badge (top-left corner).
function StatusBadge({ state }) {
  if (state !== "working" && state !== "failed") return null;
  const working = state === "working";
  return (
    <span
      className={"rbd-status rbd-status-" + state}
      title={working ? "Working" : "Failed"}
    >
      {working ? "✓" : "✕"}
    </span>
  );
}

const stateClass = (state) =>
  state === "working" || state === "failed" ? " state-" + state : "";

const fmtParam = (v) =>
  Math.abs(v) >= 1e-3 || v === 0 ? Number(v).toPrecision(4) : Number(v).toExponential(2);

function modelSummary(model) {
  // Proportional-hazards models depend on covariates entered on the calculator;
  // summarise by the covariate names rather than the baseline parameters.
  if (model.kind === "regression") {
    const cov = (model.covariates || []).map((c) => c.name).join(", ");
    return `${model.distribution}${cov ? ` · covariates: ${cov}` : ""}`;
  }
  const ps = (model.params || [])
    .map((p) => `${p.name}=${fmtParam(p.value)}`)
    .join(", ");
  return `${model.distribution}${ps ? ` · ${ps}` : ""}`;
}

// Custom component block: shows the assigned life model (or a prompt to set
// one) with left/right handles for the left-to-right flow.
function ComponentNode({ data }) {
  const rbdUnit = useContext(RbdUnitContext);
  const warn = unitWarning(data.model, rbdUnit);
  return (
    <div className={"rbd-comp" + (warn ? " unit-warn" : "") + stateClass(data.state)}>
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      {warn && <UnitWarn title={warn} />}
      <div className="rbd-comp-title">{data.label}</div>
      {data.model ? (
        <div className="rbd-comp-model">{modelSummary(data.model)}</div>
      ) : (
        <div className="rbd-comp-empty">No life model — right-click to set</div>
      )}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// n-out-of-k voting block: the system through this node works if at least n of
// the k branches connected to its output work. n and k are edited in a modal
// (right-click the node); the single output handle can fan out to multiple
// downstream nodes.
function KNode({ data }) {
  const valid =
    Number(data.n) >= 1 && Number(data.k) >= 1 && Number(data.n) <= Number(data.k);
  return (
    <div className={"rbd-knode" + (valid ? "" : " invalid") + stateClass(data.state)}>
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      <div className="rbd-knode-title">
        {(data.n || "n") + "-out-of-" + (data.k || "k")}
      </div>
      <div className="rbd-knode-sub">voting · right-click to edit</div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// Structural block types (standby / series / parallel / sub-system). Each is a
// distinct labelled block; the sub-system represents a nested RBD. Series and
// parallel blocks hold a life model and a count n of identical units.
const BLOCK_TYPES = {
  standby: { label: "Standby", sub: "redundancy", cls: "rbd-standby" },
  series: { label: "Series", sub: "subsystem", cls: "rbd-series", count: true },
  parallel: { label: "Parallel", sub: "subsystem", cls: "rbd-parallel", count: true },
  subsystem: { label: "Sub-system", sub: "nested RBD", cls: "rbd-subsystem" },
};

const BLOCK_HAS_MODEL = (kind) => kind === "series" || kind === "parallel";

function StructureNode({ data }) {
  const meta = BLOCK_TYPES[data.kind] || {};
  const rbdUnit = useContext(RbdUnitContext);
  // Series/parallel/standby carry a life model whose unit can be checked.
  const warn = unitWarning(data.model, rbdUnit);

  let body;
  if (BLOCK_HAS_MODEL(data.kind)) {
    body = data.model ? (
      <div className="rbd-block-model">{modelSummary(data.model)}</div>
    ) : (
      <div className="rbd-block-sub">No life model</div>
    );
  } else if (data.kind === "standby") {
    body = (
      <>
        <div className="rbd-block-sub">
          {(data.cold ? "cold" : "hot") +
            ` · ${data.spares ?? 1} spare${(data.spares ?? 1) === 1 ? "" : "s"}`}
        </div>
        {data.model && (
          <div className="rbd-block-model">{modelSummary(data.model)}</div>
        )}
      </>
    );
  } else if (data.kind === "subsystem") {
    body = (
      <div className={data.rbd ? "rbd-block-model" : "rbd-block-sub"}>
        {data.rbd ? data.rbd.name : "No RBD selected"}
      </div>
    );
  } else {
    body = <div className="rbd-block-sub">{meta.sub}</div>;
  }

  const count = BLOCK_HAS_MODEL(data.kind) && data.n ? data.n : null;

  return (
    <div
      className={
        "rbd-block " + (meta.cls || "") + (warn ? " unit-warn" : "") + stateClass(data.state)
      }
    >
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      {warn && <UnitWarn title={warn} />}
      <div className="rbd-block-title">
        {data.label}
        {count ? <span className="rbd-block-count">×{count}</span> : null}
      </div>
      {body}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// Short id prefixes per node type (ids stay unique via a shared counter).
const TYPE_PREFIX = {
  component: "c",
  knode: "k",
  standby: "sb",
  series: "sr",
  parallel: "pl",
  subsystem: "ss",
};

// Left-to-right reliability block diagram. Fixed input/output nodes; the user
// adds component blocks between them, connects them, and deletes nodes/edges.
const HORIZONTAL = { sourcePosition: "right", targetPosition: "left" };

const COL_GAP = 280;
const ROW_GAP = 150;

// Tidy left-to-right layered layout: each node's column is its longest path
// from the inputs (series spread across columns); nodes sharing a column
// (parallel branches) are stacked and vertically centred. Input is pinned to
// the first column, Output to the last.
function autoLayoutNodes(nodes, edges) {
  const ids = new Set(nodes.map((n) => n.id));
  const indeg = new Map(nodes.map((n) => [n.id, 0]));
  const adj = new Map(nodes.map((n) => [n.id, []]));
  for (const e of edges) {
    if (!ids.has(e.source) || !ids.has(e.target)) continue;
    adj.get(e.source).push(e.target);
    indeg.set(e.target, indeg.get(e.target) + 1);
  }

  // Longest-path layering via Kahn's algorithm.
  const rank = new Map();
  const remaining = new Map(indeg);
  const queue = [];
  for (const n of nodes) {
    if (remaining.get(n.id) === 0) {
      rank.set(n.id, 0);
      queue.push(n.id);
    }
  }
  while (queue.length) {
    const id = queue.shift();
    const r = rank.get(id) ?? 0;
    for (const t of adj.get(id)) {
      rank.set(t, Math.max(rank.get(t) ?? 0, r + 1));
      remaining.set(t, remaining.get(t) - 1);
      if (remaining.get(t) === 0) queue.push(t);
    }
  }
  for (const n of nodes) if (!rank.has(n.id)) rank.set(n.id, 0); // cycles fallback

  let maxRank = 0;
  for (const v of rank.values()) maxRank = Math.max(maxRank, v);
  if (ids.has("input")) rank.set("input", 0);
  if (ids.has("output")) rank.set("output", Math.max(maxRank, 1));
  maxRank = 0;
  for (const v of rank.values()) maxRank = Math.max(maxRank, v);

  const cols = new Map();
  for (const n of nodes) {
    const r = rank.get(n.id);
    if (!cols.has(r)) cols.set(r, []);
    cols.get(r).push(n);
  }

  const out = [];
  for (const [r, list] of cols) {
    list.sort(
      (a, b) => (a.position?.y ?? 0) - (b.position?.y ?? 0) || a.id.localeCompare(b.id)
    );
    const m = list.length;
    list.forEach((n, i) => {
      out.push({
        ...n,
        position: { x: r * COL_GAP, y: (i - (m - 1) / 2) * ROW_GAP },
      });
    });
  }
  return out;
}

const INITIAL_NODES = [
  {
    id: "input",
    type: "input",
    data: { label: "Input" },
    position: { x: 0, y: 120 },
    deletable: false,
    sourcePosition: "right",
    className: "rbd-node rbd-io",
  },
  {
    id: "output",
    type: "output",
    data: { label: "Output" },
    position: { x: 520, y: 120 },
    deletable: false,
    targetPosition: "left",
    className: "rbd-node rbd-io",
  },
];

const EDGE_OPTIONS = {
  type: "smoothstep",
  markerEnd: { type: MarkerType.ArrowClosed, width: 18, height: 18 },
};

function Builder({ rbdId, onNew, onOpenLibrary, onSaved }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [menu, setMenu] = useState(null); // { kind, x, y, flow?, id? }
  const [modal, setModal] = useState(null); // 'lifemodel'|'knode'|'count'|...|null
  const [modalNodeId, setModalNodeId] = useState(null);
  const [knodeCtx, setKnodeCtx] = useState(null); // { mode, flowPos?, nodeId?, n, k }
  const [countCtx, setCountCtx] = useState(null); // { nodeId, kind, label, n }
  const [standbyCtx, setStandbyCtx] = useState(null); // node data for the modal
  const [subsystemNodeId, setSubsystemNodeId] = useState(null);
  const [savedRbdId, setSavedRbdId] = useState(null);
  const [savedRbdName, setSavedRbdName] = useState("");
  const [savedRbdUpdatedAt, setSavedRbdUpdatedAt] = useState(null);
  const [savedRbdReadOnly, setSavedRbdReadOnly] = useState(false);
  const [rbdUnit, setRbdUnit] = useState("");
  const [tab, setTab] = useState("builder"); // 'builder' | 'calc'
  const [validation, setValidation] = useState(null);
  const [validating, setValidating] = useState(false);
  const [checkedSig, setCheckedSig] = useState(null);
  const idRef = useRef(1);
  const wrapper = useRef(null);
  // Always-current snapshot of the canvas, so the AI assistant can read the
  // live diagram via the bridge without stale-closure issues.
  const liveRef = useRef({ nodes: [], edges: [], unit: "" });
  liveRef.current = { nodes, edges, unit: rbdUnit };
  const { screenToFlowPosition, fitView } = useReactFlow();
  const nodeTypes = useMemo(
    () => ({
      component: ComponentNode,
      knode: KNode,
      standby: StructureNode,
      series: StructureNode,
      parallel: StructureNode,
      subsystem: StructureNode,
    }),
    []
  );
  const newId = useCallback(
    (type) => `${TYPE_PREFIX[type] || "n"}${idRef.current++}`,
    []
  );

  // Validate the current diagram against the backend (RePyability). A
  // position-independent signature lets us flag the result as stale once the
  // diagram changes.
  const sig = useMemo(
    () => graphSignature({ nodes, edges, unit: rbdUnit }),
    [nodes, edges, rbdUnit]
  );
  const validationStale = validation != null && sig !== checkedSig;

  const runValidate = useCallback(async () => {
    setValidating(true);
    try {
      const v = await validateRbd({ nodes, edges, unit: rbdUnit });
      setValidation(v);
      setCheckedSig(graphSignature({ nodes, edges, unit: rbdUnit }));
    } catch (err) {
      setValidation({
        valid: false,
        analytic: false,
        can_calculate: false,
        errors: [err.message],
        warnings: [],
        non_analytic_nodes: {},
      });
      setCheckedSig(graphSignature({ nodes, edges, unit: rbdUnit }));
    } finally {
      setValidating(false);
    }
  }, [nodes, edges, rbdUnit]);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, ...EDGE_OPTIONS }, eds)),
    [setEdges]
  );

  const autoLayout = useCallback(() => {
    setNodes((nds) => autoLayoutNodes(nds, edges));
    // Recenter/zoom once the new positions have been applied.
    window.requestAnimationFrame(() =>
      fitView({ padding: 0.35, duration: 300 })
    );
  }, [setNodes, edges, fitView]);

  // Manually mark a node working/failed, or clear it (state = null).
  const setNodeState = useCallback(
    (id, state) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, state } } : node
        )
      );
    },
    [setNodes]
  );

  const addComponent = useCallback(
    (flowPos) => {
      const n = idRef.current++;
      const id = `c${n}`;
      setNodes((nds) =>
        nds.concat({
          id,
          type: "component",
          data: { label: `Component ${n}`, model: null },
          position: flowPos || { x: 240, y: 40 + ((n * 70) % 200) },
          ...HORIZONTAL,
        })
      );
    },
    [setNodes]
  );

  const addKNode = useCallback(
    (flowPos, n, k) => {
      const i = idRef.current++;
      setNodes((nds) =>
        nds.concat({
          id: `k${i}`,
          type: "knode",
          data: { n, k },
          position: flowPos || { x: 240, y: 40 + ((i * 70) % 200) },
        })
      );
    },
    [setNodes]
  );

  // Add a structural block (standby / series / parallel / sub-system).
  const addBlock = useCallback(
    (kind, flowPos) => {
      const id = newId(kind);
      const data = { kind, label: BLOCK_TYPES[kind].label };
      if (BLOCK_TYPES[kind].count) {
        data.n = 2;
        data.model = null;
      } else if (kind === "standby") {
        Object.assign(data, {
          model: null,
          spares: 1,
          cold: false,
          startProb: 1,
          standbyModel: null,
        });
      } else if (kind === "subsystem") {
        data.rbd = null;
      }
      setNodes((nds) =>
        nds.concat({
          id,
          type: kind,
          data,
          position: flowPos || { x: 240, y: 40 + ((idRef.current * 70) % 200) },
          ...HORIZONTAL,
        })
      );
    },
    [setNodes, newId]
  );

  // Duplicate a node (offset, deselected, deep-copied data).
  const cloneNode = useCallback(
    (id) => {
      setNodes((nds) => {
        const node = nds.find((n) => n.id === id);
        if (!node) return nds;
        return nds.concat({
          ...node,
          id: newId(node.type),
          position: { x: node.position.x + 40, y: node.position.y + 40 },
          selected: false,
          data: JSON.parse(JSON.stringify(node.data)),
        });
      });
    },
    [setNodes, newId]
  );

  // Apply the n/k from the modal: add a new node or update the edited one.
  const submitKnode = useCallback(
    ({ n, k }) => {
      if (knodeCtx?.mode === "edit") {
        setNodes((nds) =>
          nds.map((node) =>
            node.id === knodeCtx.nodeId
              ? { ...node, data: { ...node.data, n, k } }
              : node
          )
        );
      } else {
        addKNode(knodeCtx?.flowPos, n, k);
      }
      setModal(null);
      setKnodeCtx(null);
    },
    [knodeCtx, setNodes, addKNode]
  );

  // Set the count n on a series/parallel block.
  const submitCount = useCallback(
    ({ n }) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === countCtx?.nodeId
            ? { ...node, data: { ...node.data, n } }
            : node
        )
      );
      setModal(null);
      setCountCtx(null);
    },
    [countCtx, setNodes]
  );

  // Apply the standby configuration to the targeted standby node.
  const submitStandby = useCallback(
    (config) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === standbyCtx?.nodeId
            ? { ...node, data: { ...node.data, ...config } }
            : node
        )
      );
      setModal(null);
      setStandbyCtx(null);
    },
    [standbyCtx, setNodes]
  );

  // Assign a saved RBD to the targeted sub-system node.
  const pickSubsystem = useCallback(
    (rbd) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === subsystemNodeId
            ? { ...node, data: { ...node.data, rbd } }
            : node
        )
      );
      setModal(null);
      setSubsystemNodeId(null);
    },
    [subsystemNodeId, setNodes]
  );

  // Persist the current diagram as a saved RBD (updates the open one if any).
  const onSaveRbd = useCallback(
    async (name) => {
      const graph = { nodes, edges, unit: rbdUnit };
      const saved = await saveRbd(name, graph, savedRbdId, savedRbdUpdatedAt);
      setSavedRbdId(saved.id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(saved.updated_at || null);
      setSavedRbdReadOnly(false);
      setModal(null);
      onSaved?.(saved.id);
    },
    [nodes, edges, rbdUnit, savedRbdId, savedRbdUpdatedAt, onSaved]
  );

  // Replace the canvas with a saved graph; bump the id counter past loaded ids.
  const loadGraph = useCallback(
    (graph, id, name, updatedAt = null, readOnly = false) => {
      // Re-apply the input/output handle sides (and io styling): a saved graph
      // may not carry sourcePosition/targetPosition, so without this React Flow
      // would default the input's handle to the bottom and the output's to the
      // top instead of right/left for the left-to-right flow.
      const loadedNodes = (graph?.nodes || []).map((n) => {
        const base = { ...n, selected: false };
        if (n.type === "input") {
          return { ...base, sourcePosition: "right", deletable: false, className: "rbd-node rbd-io" };
        }
        if (n.type === "output") {
          return { ...base, targetPosition: "left", deletable: false, className: "rbd-node rbd-io" };
        }
        return base;
      });
      const nums = loadedNodes
        .map((n) => parseInt(String(n.id).replace(/^\D+/, ""), 10))
        .filter((x) => !Number.isNaN(x));
      idRef.current = (nums.length ? Math.max(...nums) : 0) + 1;
      setNodes(loadedNodes);
      setEdges(graph?.edges || []);
      setRbdUnit(graph?.unit || "");
      setSavedRbdId(id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(updatedAt);
      setSavedRbdReadOnly(readOnly);
      window.requestAnimationFrame(() => fitView({ padding: 0.35, duration: 300 }));
    },
    [setNodes, setEdges, fitView]
  );

  const openRbd = useCallback(
    async (id) => {
      const full = await getRbd(id);
      loadGraph(full.graph, full.id, full.name, full.updated_at || null, !!full.read_only);
      setModal(null);
    },
    [loadGraph]
  );

  const newRbd = useCallback(() => {
    idRef.current = 1;
    setNodes(INITIAL_NODES);
    setEdges([]);
    setRbdUnit("");
    setSavedRbdId(null);
    setSavedRbdName("");
    setSavedRbdUpdatedAt(null);
    setSavedRbdReadOnly(false);
    window.requestAnimationFrame(() => fitView({ padding: 0.35, duration: 300 }));
  }, [setNodes, setEdges, fitView]);

  // Replace the canvas with an assistant-provided graph: normalise it (handles,
  // edge styling, life models) and lay it out left-to-right, then keep the new
  // id counter clear of any ids it introduced.
  const applyGraph = useCallback((graph) => {
    const norm = normalizeRbdGraph(graph);
    const nums = norm.nodes
      .map((n) => parseInt(String(n.id).replace(/^\D+/, ""), 10))
      .filter((x) => !Number.isNaN(x));
    idRef.current = Math.max(idRef.current, (nums.length ? Math.max(...nums) : 0) + 1);
    setNodes(norm.nodes);
    setEdges(norm.edges);
    if (graph.unit != null) setRbdUnit(graph.unit);
    window.requestAnimationFrame(() => fitView({ padding: 0.35, duration: 300 }));
  }, [setNodes, setEdges, fitView]);

  // Expose the live canvas to the AI assistant while the builder is mounted.
  useEffect(() => {
    return registerRbdCanvas({
      getGraph: () => ({ ...liveRef.current }),
      applyGraph,
    });
  }, [applyGraph]);

  // Load the saved RBD named in the route (once per id); a route with no id is
  // a fresh diagram.
  const loadedRef = useRef(null);
  useEffect(() => {
    if (rbdId && loadedRef.current !== rbdId) {
      loadedRef.current = rbdId;
      openRbd(rbdId).catch(() => {});
    }
  }, [rbdId, openRbd]);

  // Assign a life model (saved or from parameters) to the node the modal targets.
  const setNodeModel = useCallback(
    (model) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === modalNodeId
            ? { ...node, data: { ...node.data, model } }
            : node
        )
      );
      setModal(null);
      setModalNodeId(null);
    },
    [setNodes, modalNodeId]
  );

  const closeMenu = useCallback(() => setMenu(null), []);

  // Keep the right-click menu on screen: after it mounts we know its size, so
  // clamp it into the viewport — which flips it up when it would run off the
  // bottom (and left when it would run off the right edge).
  const menuRef = useRef(null);
  useLayoutEffect(() => {
    const el = menuRef.current;
    if (!menu || !el) return;
    const gap = 8;
    const { width, height } = el.getBoundingClientRect();
    const left = Math.max(gap, Math.min(menu.x, window.innerWidth - width - gap));
    const top = Math.max(gap, Math.min(menu.y, window.innerHeight - height - gap));
    el.style.left = `${left}px`;
    el.style.top = `${top}px`;
  }, [menu]);

  const onPaneContextMenu = useCallback(
    (event) => {
      event.preventDefault();
      setMenu({
        kind: "pane",
        x: event.clientX,
        y: event.clientY,
        flow: screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      });
    },
    [screenToFlowPosition]
  );

  const onNodeContextMenu = useCallback((event, node) => {
    event.preventDefault();
    setMenu({
      kind: "node",
      x: event.clientX,
      y: event.clientY,
      id: node.id,
      nodeType: node.type,
      state: node.data?.state || null,
      protectedNode: node.deletable === false,
    });
  }, []);

  const onEdgeContextMenu = useCallback((event, edge) => {
    event.preventDefault();
    setMenu({ kind: "edge", x: event.clientX, y: event.clientY, id: edge.id });
  }, []);

  // Double-clicking a node opens its primary edit window (the same action the
  // right-click menu offers): the life-model editor for component/series/
  // parallel blocks, and the dedicated editor for knode/standby/sub-system.
  const onNodeDoubleClick = useCallback(
    (event, node) => {
      event.preventDefault();
      closeMenu();
      switch (node.type) {
        case "component":
        case "series":
        case "parallel":
          setModalNodeId(node.id);
          setModal("lifemodel");
          break;
        case "knode":
          setKnodeCtx({
            mode: "edit",
            nodeId: node.id,
            n: node.data?.n ?? 2,
            k: node.data?.k ?? 3,
          });
          setModal("knode");
          break;
        case "standby":
          setStandbyCtx({ nodeId: node.id, ...node.data });
          setModal("standby");
          break;
        case "subsystem":
          setSubsystemNodeId(node.id);
          setModal("subsystem");
          break;
        default:
          break; // input/output have nothing to edit
      }
    },
    [closeMenu]
  );

  const deleteNode = useCallback(
    (id) => {
      setNodes((nds) => nds.filter((n) => n.id !== id));
      setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    },
    [setNodes, setEdges]
  );

  const deleteEdge = useCallback(
    (id) => setEdges((eds) => eds.filter((e) => e.id !== id)),
    [setEdges]
  );

  return (
    <RbdUnitContext.Provider value={rbdUnit}>
    <div className="rbd-shell">
    <div className="tabs rbd-tabs">
      <button
        className={"tab" + (tab === "builder" ? " active" : "")}
        onClick={() => setTab("builder")}
      >
        Builder
      </button>
      <button
        className={"tab" + (tab === "calc" ? " active" : "")}
        onClick={() => setTab("calc")}
      >
        Calculator
      </button>
    </div>
    <div
      className="rbd-canvas"
      ref={wrapper}
      style={{ display: tab === "builder" ? undefined : "none" }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onPaneContextMenu={onPaneContextMenu}
        onNodeContextMenu={onNodeContextMenu}
        onNodeDoubleClick={onNodeDoubleClick}
        onEdgeContextMenu={onEdgeContextMenu}
        onPaneClick={closeMenu}
        onMoveStart={closeMenu}
        deleteKeyCode={["Backspace", "Delete"]}
        defaultEdgeOptions={EDGE_OPTIONS}
        fitView
        fitViewOptions={{ padding: 0.35 }}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Panel position="top-left">
          <span className="rbd-name">{savedRbdName || "Untitled RBD"}</span>
          <label className="rbd-unit-field">
            <span>Unit</span>
            <input
              className="rbd-unit-input"
              list="rbd-time-units"
              placeholder="e.g. Hours"
              value={rbdUnit}
              onChange={(e) => setRbdUnit(e.target.value)}
            />
            <datalist id="rbd-time-units">
              {TIME_UNITS.map((u) => (
                <option value={u} key={u} />
              ))}
            </datalist>
          </label>
        </Panel>
        <Panel position="top-right">
          <button className="rbd-btn" onClick={() => setModal("saverbd")}>
            Save RBD
          </button>
          {savedRbdId && (
            <ShareButton
              collection="rbds"
              artifactId={savedRbdId}
              name={savedRbdName || "Untitled RBD"}
              readOnly={savedRbdReadOnly}
            />
          )}
          <button className="rbd-btn" onClick={autoLayout}>
            Auto-arrange
          </button>
          <button
            className="rbd-btn rbd-btn-primary"
            onClick={runValidate}
            disabled={validating}
          >
            {validating ? "Validating…" : "Validate"}
          </button>
        </Panel>
        {validation && (
          <Panel position="top-center">
            <div className="rbd-validate-card">
              <button
                className="rbd-validate-close"
                onClick={() => setValidation(null)}
                aria-label="Dismiss"
                title="Dismiss"
              >
                ×
              </button>
              <ValidationPanel validation={validation} stale={validationStale} />
            </div>
          </Panel>
        )}
        <Background gap={22} color="#e8e7e2" />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable />
      </ReactFlow>

      {menu && (
        <div
          ref={menuRef}
          className="rbd-menu"
          style={{ top: menu.y, left: menu.x }}
          onMouseLeave={closeMenu}
        >
          {menu.kind === "pane" && (
            <>
              <button
                onClick={() => {
                  addComponent(menu.flow);
                  closeMenu();
                }}
              >
                Add component
              </button>
              <button
                onClick={() => {
                  setKnodeCtx({ mode: "add", flowPos: menu.flow, n: 2, k: 3 });
                  setModal("knode");
                  closeMenu();
                }}
              >
                Add n-out-of-k node
              </button>
              <button onClick={() => { addBlock("standby", menu.flow); closeMenu(); }}>
                Add standby node
              </button>
              <button onClick={() => { addBlock("series", menu.flow); closeMenu(); }}>
                Add series node
              </button>
              <button onClick={() => { addBlock("parallel", menu.flow); closeMenu(); }}>
                Add parallel node
              </button>
              <button onClick={() => { addBlock("subsystem", menu.flow); closeMenu(); }}>
                Add sub-system
              </button>
              <div className="rbd-menu-sep" />
              <button onClick={() => { autoLayout(); closeMenu(); }}>
                Auto-arrange
              </button>
            </>
          )}
          {menu.kind === "node" &&
            (menu.protectedNode ? (
              <span className="rbd-menu-note">Input/output can’t be removed</span>
            ) : (
              <>
                {(menu.nodeType === "component" ||
                  menu.nodeType === "series" ||
                  menu.nodeType === "parallel") && (
                  <>
                    <button
                      onClick={() => {
                        setModalNodeId(menu.id);
                        setModal("lifemodel");
                        closeMenu();
                      }}
                    >
                      Edit life model
                    </button>
                    {(menu.nodeType === "series" ||
                      menu.nodeType === "parallel") && (
                      <button
                        onClick={() => {
                          const node = nodes.find((nd) => nd.id === menu.id);
                          setCountCtx({
                            nodeId: menu.id,
                            kind: node?.type,
                            label: node?.data.label,
                            n: node?.data.n ?? 2,
                          });
                          setModal("count");
                          closeMenu();
                        }}
                      >
                        Set count (n)
                      </button>
                    )}
                    <div className="rbd-menu-sep" />
                  </>
                )}
                {menu.nodeType === "knode" && (
                  <>
                    <button
                      onClick={() => {
                        const node = nodes.find((nd) => nd.id === menu.id);
                        setKnodeCtx({
                          mode: "edit",
                          nodeId: menu.id,
                          n: node?.data.n ?? 2,
                          k: node?.data.k ?? 3,
                        });
                        setModal("knode");
                        closeMenu();
                      }}
                    >
                      Edit n and k
                    </button>
                    <div className="rbd-menu-sep" />
                  </>
                )}
                {menu.nodeType === "standby" && (
                  <>
                    <button
                      onClick={() => {
                        const node = nodes.find((nd) => nd.id === menu.id);
                        setStandbyCtx({ nodeId: menu.id, ...node?.data });
                        setModal("standby");
                        closeMenu();
                      }}
                    >
                      Edit standby
                    </button>
                    <div className="rbd-menu-sep" />
                  </>
                )}
                {menu.nodeType === "subsystem" && (
                  <>
                    <button
                      onClick={() => {
                        setSubsystemNodeId(menu.id);
                        setModal("subsystem");
                        closeMenu();
                      }}
                    >
                      Select RBD…
                    </button>
                    <div className="rbd-menu-sep" />
                  </>
                )}
                {menu.state !== "working" && (
                  <button
                    onClick={() => {
                      setNodeState(menu.id, "working");
                      closeMenu();
                    }}
                  >
                    Set working
                  </button>
                )}
                {menu.state !== "failed" && (
                  <button
                    onClick={() => {
                      setNodeState(menu.id, "failed");
                      closeMenu();
                    }}
                  >
                    Set failed
                  </button>
                )}
                {menu.state && (
                  <button
                    onClick={() => {
                      setNodeState(menu.id, null);
                      closeMenu();
                    }}
                  >
                    Clear status
                  </button>
                )}
                <div className="rbd-menu-sep" />
                <button
                  onClick={() => {
                    cloneNode(menu.id);
                    closeMenu();
                  }}
                >
                  Clone
                </button>
                <button
                  onClick={() => {
                    deleteNode(menu.id);
                    closeMenu();
                  }}
                >
                  Delete node
                </button>
              </>
            ))}
          {menu.kind === "edge" && (
            <button
              onClick={() => {
                deleteEdge(menu.id);
                closeMenu();
              }}
            >
              Delete edge
            </button>
          )}
        </div>
      )}

      <div className="rbd-hint">
        Right-click the canvas to add a component · right-click a node or edge to
        delete · drag between handles to connect
      </div>

      {modal === "lifemodel" && (
        <LifeModelModal
          initial={nodes.find((n) => n.id === modalNodeId)?.data}
          onClose={() => {
            setModal(null);
            setModalNodeId(null);
          }}
          onSubmit={setNodeModel}
        />
      )}
      {modal === "knode" && (
        <KNodeModal
          initial={knodeCtx}
          onClose={() => {
            setModal(null);
            setKnodeCtx(null);
          }}
          onSubmit={submitKnode}
        />
      )}
      {modal === "count" && (
        <CountModal
          initial={countCtx}
          onClose={() => {
            setModal(null);
            setCountCtx(null);
          }}
          onSubmit={submitCount}
        />
      )}
      {modal === "standby" && (
        <StandbyModal
          initial={standbyCtx}
          onClose={() => {
            setModal(null);
            setStandbyCtx(null);
          }}
          onSubmit={submitStandby}
        />
      )}
      {modal === "subsystem" && (
        <SubsystemModal
          onClose={() => {
            setModal(null);
            setSubsystemNodeId(null);
          }}
          onPick={pickSubsystem}
        />
      )}
      {modal === "saverbd" && (
        <RbdSaveModal
          initialName={savedRbdName}
          onClose={() => setModal(null)}
          onSubmit={onSaveRbd}
        />
      )}
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "calc" ? undefined : "none" }}
    >
      <RbdCalculator
        graph={{ nodes, edges, unit: rbdUnit }}
        validation={validation}
        stale={validationStale}
      />
    </div>
    </div>
    </RbdUnitContext.Provider>
  );
}

export default function RbdBuilder() {
  const { id } = useParams();
  const navigate = useNavigate();
  return (
    <div className="app rbd-app">
      <header>
        <div>
          <div className="crumb">
            <Link className="crumb-link" to="/rbds">RBDs</Link> / <b>Builder</b>
          </div>
          <h1>Reliability block diagram</h1>
          <CopyId id={id} />
        </div>
      </header>
      <div className="card rbd-wrap">
        <ReactFlowProvider>
          <Builder
            key={id || "new"}
            rbdId={id}
            onNew={() => navigate("/rbds/b")}
            onOpenLibrary={() => navigate("/rbds/list")}
            onSaved={(savedId) => navigate(`/rbds/b/${savedId}`, { replace: true })}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
