import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlowProvider,
  addEdge,
  useReactFlow,
  useEdgesState,
  useNodesState,
  MarkerType,
} from "reactflow";
import "reactflow/dist/style.css";
import LifeModelModal from "../components/LifeModelModal.jsx";
import CcfModal from "../components/CcfModal.jsx";
import KNodeModal from "../components/KNodeModal.jsx";
import CountModal from "../components/CountModal.jsx";
import StandbyModal from "../components/StandbyModal.jsx";
import LoadShareModal from "../components/LoadShareModal.jsx";
import Select from "../components/Select.jsx";
import SubsystemModal from "../components/SubsystemModal.jsx";
import RbdSaveModal from "../components/RbdSaveModal.jsx";
import RbdCalculator from "../components/RbdCalculator.jsx";
import RbdFaultTree from "../components/RbdFaultTree.jsx";
import RbdDesignPanel from "../components/RbdDesignPanel.jsx";
import RbdCostsModal from "../components/RbdCostsModal.jsx";
import RbdCrewsModal from "../components/RbdCrewsModal.jsx";
import { applyBlockExtras } from "../components/RbdBlockCosts.jsx";
import ValidationPanel, { graphSignature } from "../components/RbdValidation.jsx";
import {
  saveRbd, getRbd, validateRbd, downloadRbdPython, PYTHON_EXPORT_TIP, downloadRbdJson, JSON_EXPORT_TIP,
} from "../api.js";
import { ShareButton } from "../components/ShareDialog.jsx";
import { registerRbdCanvas } from "../rbdBridge.js";
import { normalizeRbdGraph } from "../rbdGraph.js";
import { isRepeat, makeRepeat, originalId, promoteRepeats } from "../rbdRepeats.js";
// The node components (and the contexts they read) live in RbdNodes.jsx so
// the public read-only view renders the very same blocks.
import {
  BLOCK_TYPES,
  ComponentNode,
  KNode,
  RbdCcfContext,
  RbdRepairableContext,
  RbdUnitContext,
  StructureNode,
} from "../components/RbdNodes.jsx";
import { lazy, Suspense } from "react";
import { unitInText } from "../components/unitText.js";
import PageHeader from "../components/ui/PageHeader.jsx";

// The "Outage history" tab (an observed-history import and charts) loads on
// first open, so the builder's own bundle doesn't carry it.
const OutageHistory = lazy(() => import("../components/OutageHistory.jsx"));
// ?tab=outages (the MCP tools' links) opens the builder on that tab.
const initialTab = () =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "outages"
    ? "outages"
    : "builder";

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

// Short id prefixes per node type (ids stay unique via a shared counter).
const TYPE_PREFIX = {
  component: "c",
  knode: "k",
  standby: "sb",
  loadshare: "ls",
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

// Fitting the view never zooms out so far that block text is unreadable: a
// large diagram fits at 0.6 and the rest is a pan away.
const FIT_OPTIONS = { padding: 0.35, minZoom: 0.6, duration: 300 };

// A repairable diagram's crews, groups and safety settings (#156, #157): the
// graph keys that are set.
const POLICY_KEYS = ["repair_crews", "maintenance_groups", "safety_function", "target_sil"];
function policyFields(policies) {
  const out = {};
  for (const k of POLICY_KEYS) if (policies?.[k]) out[k] = policies[k];
  return out;
}

function Builder({ rbdId, imported, onNew, onOpenLibrary, onSaved, onMeta }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [menu, setMenu] = useState(null); // { kind, x, y, flow?, id? }
  const [connectHint, setConnectHint] = useState(""); // transient note from the C shortcut
  const [ccfListOpen, setCcfListOpen] = useState(false);
  const [modal, setModal] = useState(null); // 'lifemodel'|'knode'|'count'|...|null
  const [modalNodeId, setModalNodeId] = useState(null);
  const [knodeCtx, setKnodeCtx] = useState(null); // { mode, flowPos?, nodeId?, n, k }
  const [countCtx, setCountCtx] = useState(null); // { nodeId, kind, label, n }
  const [standbyCtx, setStandbyCtx] = useState(null); // node data for the modal
  const [loadshareCtx, setLoadshareCtx] = useState(null); // load-sharing node data
  const [subsystemNodeId, setSubsystemNodeId] = useState(null);
  const [savedRbdId, setSavedRbdId] = useState(null);
  const [savedRbdName, setSavedRbdName] = useState("");
  const [savedRbdUpdatedAt, setSavedRbdUpdatedAt] = useState(null);
  const [savedRbdReadOnly, setSavedRbdReadOnly] = useState(false);
  // The page header shows the diagram's name and holds Share / Copy ID.
  useEffect(() => {
    onMeta?.({ id: savedRbdId, name: savedRbdName, readOnly: savedRbdReadOnly });
  }, [onMeta, savedRbdId, savedRbdName, savedRbdReadOnly]);
  const [rbdUnit, setRbdUnit] = useState("");
  // Repairable RBD: a distinct modelling choice — components carry a repair-time
  // distribution and the system is analysed for availability, not reliability.
  const [repairable, setRepairable] = useState(false);
  // Common-cause groups: [{id, members:[nodeId], beta}] — redundant components
  // coupled by a shared failure cause (reliability analysis only).
  const [ccfGroups, setCcfGroups] = useState([]);
  // Diagram-level costs of a repairable diagram (#99): {downtime_rate, horizon}.
  const [diagramCosts, setDiagramCosts] = useState(null);
  // Repair crews, maintenance groups and a safety function (#156, #157):
  // {repair_crews, maintenance_groups, safety_function, target_sil}.
  const [policies, setPolicies] = useState({});
  // Carried with the diagram wherever the costs are (save, validate, analyse).
  const costsField = useMemo(
    () => ({ ...(diagramCosts ? { costs: diagramCosts } : {}), ...policyFields(policies) }),
    [diagramCosts, policies]
  );
  const [ccfCtx, setCcfCtx] = useState(null); // { members, beta, groupId? } for the modal
  const [tab, setTab] = useState(initialTab); // 'builder' | 'calc' | 'tree' | 'design' | 'outages'
  // A tab's empty state (#271) sends the user back to the canvas.
  const toBuilder = useCallback(() => setTab("builder"), []);
  const [validation, setValidation] = useState(null);
  const [validating, setValidating] = useState(false);
  const [checkedSig, setCheckedSig] = useState(null);
  const idRef = useRef(1);
  const wrapper = useRef(null);
  // Always-current snapshot of the canvas, so the AI assistant can read the
  // live diagram via the bridge without stale-closure issues.
  const liveRef = useRef({ nodes: [], edges: [], unit: "" });
  liveRef.current = { nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField };
  const { screenToFlowPosition, fitView, getNodes } = useReactFlow();
  // Fit once React Flow has measured the nodes just set (#309). A saved
  // diagram reopened with blocks off-screen: its load ran in a callback from
  // the first render, whose fitView was React Flow's no-op stand-in (the
  // viewport wasn't ready), and fitting in the next frame came before the
  // nodes had sizes. So: the current fitView, once every one of ``expected``
  // is in the flow with a size (a second at most).
  const fitViewRef = useRef(fitView);
  fitViewRef.current = fitView;
  const fitWhenMeasured = useCallback((expected) => {
    const ids = (expected || []).map((n) => n.id);
    let frames = 0;
    const attempt = () => {
      const byId = new Map(getNodes().map((n) => [n.id, n]));
      const ready = ids.every((id) => byId.get(id)?.width && byId.get(id)?.height);
      if ((ready && frames > 0) || frames > 60) fitViewRef.current(FIT_OPTIONS);
      else {
        frames += 1;
        window.requestAnimationFrame(attempt);
      }
    };
    window.requestAnimationFrame(attempt);
  }, [getNodes]);
  const nodeTypes = useMemo(
    () => ({
      component: ComponentNode,
      knode: KNode,
      standby: StructureNode,
      loadshare: StructureNode,
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
    () => graphSignature({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }),
    [nodes, edges, rbdUnit, repairable, ccfGroups, costsField]
  );
  const validationStale = validation != null && sig !== checkedSig;

  const runValidate = useCallback(async () => {
    setValidating(true);
    try {
      const v = await validateRbd({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField });
      setValidation(v);
      setCheckedSig(graphSignature({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }));
    } catch (err) {
      setValidation({
        valid: false,
        analytic: false,
        can_calculate: false,
        errors: [err.message],
        warnings: [],
        non_analytic_nodes: {},
      });
      setCheckedSig(graphSignature({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }));
    } finally {
      setValidating(false);
    }
  }, [nodes, edges, rbdUnit, repairable, ccfGroups, costsField]);

  const onConnect = useCallback(
    (params) => setEdges((eds) => addEdge({ ...params, ...EDGE_OPTIONS }, eds)),
    [setEdges]
  );

  // Wire up the selected blocks without dragging between handles (press C).
  //
  // An RBD is stages in series, each holding components in parallel — so the
  // selection is grouped into columns by x and consecutive columns are joined
  // every-to-every. Two blocks side by side become one link; one block plus two
  // stacked ones becomes a fan-out into a redundant stage; box-select a region
  // and it wires the whole thing up in one press. addEdge skips connections that
  // already exist, so pressing it twice is harmless.
  const connectSelected = useCallback(() => {
    const chosen = nodes.filter((n) => n.selected);
    if (chosen.length < 2) {
      setConnectHint("Select two or more blocks first, then press C.");
      return;
    }
    const columns = [];
    for (const n of [...chosen].sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0))) {
      const last = columns[columns.length - 1];
      // Same column if within half a column gap of the one being built.
      if (last && Math.abs((n.position?.x ?? 0) - last.x) < COL_GAP / 2) last.items.push(n);
      else columns.push({ x: n.position?.x ?? 0, items: [n] });
    }
    if (columns.length < 2) {
      setConnectHint("Those blocks are stacked in one column — nothing to connect in series.");
      return;
    }
    const pairs = [];
    for (let i = 0; i < columns.length - 1; i += 1)
      for (const s of columns[i].items)
        for (const t of columns[i + 1].items) pairs.push([s.id, t.id]);

    let added = 0;
    setEdges((eds) => {
      const next = pairs.reduce(
        (acc, [source, target]) => addEdge({ source, target, ...EDGE_OPTIONS }, acc),
        eds
      );
      added = next.length - eds.length;
      return next;
    });
    setConnectHint(
      added
        ? `Connected ${added} link${added === 1 ? "" : "s"}.`
        : "Those blocks are already connected."
    );
  }, [nodes, setEdges]);

  // C connects the selection. Ignored while typing, while a menu or modal is
  // open, and whenever a modifier is down so Cmd/Ctrl+C still copies.
  useEffect(() => {
    if (tab !== "builder" || modal || menu) return undefined;
    const onKey = (e) => {
      if (e.key !== "c" && e.key !== "C") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const el = e.target;
      if (el?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName)) return;
      e.preventDefault();
      connectSelected();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, modal, menu, connectSelected]);

  // Clear the transient "connected N links" note after a moment.
  useEffect(() => {
    if (!connectHint) return undefined;
    const t = setTimeout(() => setConnectHint(""), 2600);
    return () => clearTimeout(t);
  }, [connectHint]);

  // "Download as Python": the saved diagram as a standalone SurPyval +
  // RePyability script. Free for every viewer (samples and shared diagrams
  // too). Also triggered by a `reliafy:rbd-export` window event, e.g. from the
  // availability upgrade card.
  // "Download as RePyability JSON" (#174) sits beside it: the same diagram as
  // RePyability's to_json document, which Reliafy's Import also reads back.
  const [exporting, setExporting] = useState(null); // "python" | "json" while downloading
  const exportingRef = useRef(false);
  const exportAs = useCallback(async (kind) => {
    const python = kind === "python";
    if (!savedRbdId) {
      setConnectHint(`Save the diagram first to download it as ${python ? "Python" : "RePyability JSON"}.`);
      return;
    }
    if (exportingRef.current) return;
    exportingRef.current = true;
    setExporting(kind);
    try {
      const file = await (python ? downloadRbdPython : downloadRbdJson)(savedRbdId);
      setConnectHint(`Downloaded ${file} (the last saved version).`);
    } catch (e) {
      setConnectHint(e.message || `Couldn't download the ${python ? "script" : "file"}.`);
    } finally {
      exportingRef.current = false;
      setExporting(null);
    }
  }, [savedRbdId]);
  const exportPython = useCallback(() => exportAs("python"), [exportAs]);

  useEffect(() => {
    const onExport = () => exportPython();
    window.addEventListener("reliafy:rbd-export", onExport);
    return () => window.removeEventListener("reliafy:rbd-export", onExport);
  }, [exportPython]);

  const autoLayout = useCallback(() => {
    setNodes((nds) => autoLayoutNodes(nds, edges));
    // Recenter/zoom once the new positions have been applied.
    fitWhenMeasured();
  }, [setNodes, edges, fitWhenMeasured]);

  // Manually mark a node working/failed, or clear it (state = null).
  const setNodeState = useCallback(
    (id, state) => {
      setNodes((nds) => {
        const target = originalId(nds, id); // a repeated block pins its original
        return nds.map((node) =>
          node.id === target ? { ...node, data: { ...node.data, state } } : node
        );
      });
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
      } else if (kind === "loadshare") {
        Object.assign(data, { model: null, load: "", units: 2, k: 1 });
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

  // Repeated block (#102): a linked copy of a component, drawn again elsewhere
  // (e.g. one power supply feeding two trains) and analysed as the same one.
  const repeatNode = useCallback(
    (id) => {
      const copyId = newId("component");
      setNodes((nds) => {
        const copy = makeRepeat(nds, id, copyId);
        return copy ? nds.concat(copy) : nds;
      });
    },
    [setNodes, newId]
  );

  // Removing a component hands its model to its first copy (see
  // promoteRepeats) — whether it's deleted from the menu or with the keyboard.
  const handleNodesChange = useCallback(
    (changes) => {
      const removed = changes.filter((c) => c.type === "remove").map((c) => c.id);
      if (removed.length) setNodes((nds) => promoteRepeats(nds, removed));
      onNodesChange(changes);
    },
    [setNodes, onNodesChange]
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
            ? {
                ...node,
                // A repairable group's costs, priority and own repairer (#156):
                // a null removes the key, as for a component's extras.
                data: applyBlockExtras({ ...node.data, ...config }, {
                  costs: config.costs, crew_priority: config.crew_priority,
                  repair_one_at_a_time: config.repair_one_at_a_time,
                }),
              }
            : node
        )
      );
      setModal(null);
      setStandbyCtx(null);
    },
    [standbyCtx, setNodes]
  );

  // Apply the load-sharing configuration to the targeted node.
  const submitLoadshare = useCallback(
    (config) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === loadshareCtx?.nodeId
            ? { ...node, data: { ...node.data, ...config } }
            : node
        )
      );
      setModal(null);
      setLoadshareCtx(null);
    },
    [loadshareCtx, setNodes]
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
      const graph = { nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField };
      const saved = await saveRbd(name, graph, savedRbdId, savedRbdUpdatedAt);
      setSavedRbdId(saved.id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(saved.updated_at || null);
      setSavedRbdReadOnly(false);
      setModal(null);
      onSaved?.(saved.id);
    },
    [nodes, edges, rbdUnit, repairable, ccfGroups, costsField, savedRbdId, savedRbdUpdatedAt, onSaved]
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
      setRepairable(!!graph?.repairable);
      setCcfGroups(graph?.ccf_groups || []);
      setDiagramCosts(graph?.costs || null);
      setPolicies(policyFields(graph));
      setSavedRbdId(id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(updatedAt);
      setSavedRbdReadOnly(readOnly);
      fitWhenMeasured(loadedNodes);
    },
    [setNodes, setEdges, fitWhenMeasured]
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
    setRepairable(false);
    setCcfGroups([]);
    setDiagramCosts(null);
    setPolicies({});
    setSavedRbdId(null);
    setSavedRbdName("");
    setSavedRbdUpdatedAt(null);
    setSavedRbdReadOnly(false);
    fitWhenMeasured(INITIAL_NODES);
  }, [setNodes, setEdges, fitWhenMeasured]);

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
    if (graph.repairable != null) setRepairable(!!graph.repairable);
    if (graph.ccf_groups != null) setCcfGroups(graph.ccf_groups);
    if (graph.costs !== undefined) setDiagramCosts(graph.costs || null);
    if (POLICY_KEYS.some((k) => graph[k] !== undefined)) setPolicies(policyFields(graph));
    fitWhenMeasured(norm.nodes);
  }, [setNodes, setEdges, fitWhenMeasured]);

  // Put a redundancy design (Design tab) on the canvas as it is — unsaved, and
  // keeping the user's layout — clearing the id counter past any new ids.
  const applyDesign = useCallback((graph) => {
    const nums = graph.nodes
      .map((n) => parseInt(String(n.id).replace(/^\D+/, ""), 10))
      .filter((x) => !Number.isNaN(x));
    idRef.current = Math.max(idRef.current, (nums.length ? Math.max(...nums) : 0) + 1);
    setNodes(graph.nodes);
    setEdges(graph.edges);
    // A common-cause member's copies join its group (and Undo restores it).
    if (graph.ccf_groups != null) setCcfGroups(graph.ccf_groups);
  }, [setNodes, setEdges]);

  // Expose the live canvas to the AI assistant while the builder is mounted.
  useEffect(() => {
    return registerRbdCanvas({
      getGraph: () => ({ ...liveRef.current }),
      applyGraph,
    });
  }, [applyGraph]);

  // Load the saved RBD named in the route (once per id); a route with no id is
  // a fresh diagram — or one just imported from another tool's file, which
  // opens unsaved (Save keeps it, under the usual plan limits).
  const loadedRef = useRef(null);
  useEffect(() => {
    if (rbdId && loadedRef.current !== rbdId) {
      loadedRef.current = rbdId;
      openRbd(rbdId).catch(() => {});
    } else if (!rbdId && imported?.graph && loadedRef.current !== imported) {
      loadedRef.current = imported;
      loadGraph(imported.graph, null, imported.name || "");
    }
  }, [rbdId, imported, openRbd, loadGraph]);

  // Assign a life model (saved or from parameters) to the node the modal targets.
  const setNodeModel = useCallback(
    ({ model, repair, extras }) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === modalNodeId
            ? { ...node, data: applyBlockExtras({ ...node.data, model, ...(repair !== undefined ? { repair } : {}) }, extras) }
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
    // A repeated block shows (and sets) its original's pinned state.
    const shown = liveRef.current.nodes.find((n) => n.id === originalId(liveRef.current.nodes, node.id));
    setMenu({
      kind: "node",
      x: event.clientX,
      y: event.clientY,
      id: node.id,
      nodeType: node.type,
      repeat: isRepeat(node),
      state: shown?.data?.state || null,
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
          // A repeated block edits the component it repeats.
          setModalNodeId(originalId(liveRef.current.nodes, node.id));
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
        case "loadshare":
          setLoadshareCtx({ nodeId: node.id, ...node.data });
          setModal("loadshare");
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
      setNodes((nds) => promoteRepeats(nds, [id]).filter((n) => n.id !== id));
      setEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id));
    },
    [setNodes, setEdges]
  );

  const deleteEdge = useCallback(
    (id) => setEdges((eds) => eds.filter((e) => e.id !== id)),
    [setEdges]
  );

  // The maintenance groups the blocks name (#157), for the group pickers.
  const groupNames = useMemo(
    () => [...new Set(nodes.map((n) => n.data?.maintenance_group).filter(Boolean))].sort(),
    [nodes]
  );

  // Common-cause: id -> beta (for the node badge), and the currently-selected
  // component nodes (the candidates for a new group).
  const ccfMap = useMemo(() => {
    const m = {};
    for (const g of ccfGroups) for (const id of g.members || []) m[id] = g.beta;
    return m;
  }, [ccfGroups]);
  const selectedComponentIds = useMemo(
    // A repeated block is its original, not another member.
    () => nodes.filter((n) => n.selected && n.type === "component" && !isRepeat(n)).map((n) => n.id),
    [nodes]
  );
  const labelFor = (id) => nodes.find((n) => n.id === id)?.data?.label || id;

  const openCcfForSelection = () => {
    if (selectedComponentIds.length < 2) return;
    setCcfCtx({ members: selectedComponentIds, beta: 0.1 });
    setModal("ccf");
  };
  // A group keeps a basis only when it isn't the rate (the default, #210).
  const withBasis = (g, beta, basis) => {
    const { basis: _old, ...rest } = g;
    return basis === "probability" ? { ...rest, beta, basis } : { ...rest, beta };
  };
  const submitCcf = ({ beta, basis }) => {
    setCcfGroups((prev) => {
      if (ccfCtx?.groupId) return prev.map((g) => (g.id === ccfCtx.groupId ? withBasis(g, beta, basis) : g));
      const id = `ccf-${Date.now().toString(36)}-${Math.round(Math.random() * 1e4)}`;
      return [...prev, withBasis({ id, members: ccfCtx.members }, beta, basis)];
    });
    setModal(null);
    setCcfCtx(null);
  };
  const editCcf = (g) => {
    setCcfCtx({ members: g.members, beta: g.beta, basis: g.basis, groupId: g.id });
    setModal("ccf");
  };
  const removeCcf = (gid) => setCcfGroups((prev) => prev.filter((g) => g.id !== gid));

  return (
    <RbdUnitContext.Provider value={rbdUnit}>
    <RbdRepairableContext.Provider value={repairable}>
    <RbdCcfContext.Provider value={ccfMap}>
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
      <button
        className={"tab" + (tab === "tree" ? " active" : "")}
        onClick={() => setTab("tree")}
      >
        Fault tree
      </button>
      <button
        className={"tab" + (tab === "design" ? " active" : "")}
        onClick={() => setTab("design")}
        title="How many copies of each block: most reliable within a budget, or cheapest to reach a target"
      >
        Design
      </button>
      <button
        className={"tab" + (tab === "outages" ? " active" : "")}
        onClick={() => setTab("outages")}
      >
        Outage history
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
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onPaneContextMenu={onPaneContextMenu}
        onNodeContextMenu={onNodeContextMenu}
        onNodeDoubleClick={onNodeDoubleClick}
        onEdgeContextMenu={onEdgeContextMenu}
        onPaneClick={closeMenu}
        onMoveStart={closeMenu}
        deleteKeyCode={["Backspace", "Delete"]}
        // Shift-click adds to the selection (as the hints/guides say), alongside
        // the platform Cmd/Ctrl. Shift-drag still box-selects.
        multiSelectionKeyCode={["Meta", "Control", "Shift"]}
        defaultEdgeOptions={EDGE_OPTIONS}
        fitView
        fitViewOptions={FIT_OPTIONS}
        minZoom={0.2}
        proOptions={{ hideAttribution: true }}
      >
        <Panel position="top-left" className="rbd-toolbar">
          <div className="rbd-toolbar-row">
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
          <div className="rbd-unit-field" title="Repairable diagrams analyse availability (uptime) — every component also needs a repair-time distribution. Non-repairable diagrams analyse reliability over time.">
            <span>System</span>
            <Select
              value={repairable ? "repairable" : "non"}
              onChange={(v) => setRepairable(v === "repairable")}
              // Short labels: the toolbar row has to share the canvas width with
              // the action buttons opposite. What each mode means is on the
              // field's tooltip and in the results tab.
              options={[
                { value: "non", label: "Non-repairable" },
                { value: "repairable", label: "Repairable" },
              ]}
            />
          </div>
          {repairable && (
            <button
              className={"rbd-costs-toggle" + (diagramCosts ? " set" : "")}
              onClick={() => setModal("costs")}
              title={
                diagramCosts?.downtime_rate != null
                  ? `System downtime costs ${Number(diagramCosts.downtime_rate).toLocaleString()} per ${(unitInText(rbdUnit) || "time unit").replace(/s$/, "")} — click to edit`
                  : "System downtime cost and ownership horizon (block costs are on each block)"
              }
            >
              Costs
            </button>
          )}
          {repairable && (
            <button
              className={"rbd-costs-toggle" + (Object.keys(policyFields(policies)).length ? " set" : "")}
              onClick={() => setModal("crews")}
              title="Repair crews shared by the blocks, maintenance groups' set-up costs, and a safety function's PFDavg / SIL"
            >
              {policies.repair_crews?.crews
                ? `${policies.repair_crews.crews} crew${policies.repair_crews.crews === 1 ? "" : "s"}`
                : "Crews"}
              {policies.safety_function ? " · SIF" : ""}
            </button>
          )}
          {/* Common-cause groups sit with the other diagram-level settings, as a
              chip that expands on demand. They used to float bottom-left, where
              they collided with the zoom controls and the hint bubble; a chip
              keeps the overlay one row tall so it doesn't cover the top of the
              diagram either. */}
          {ccfGroups.length > 0 && (
            <div className="rbd-ccf-menu">
              <button
                className={"rbd-ccf-toggle" + (ccfListOpen ? " open" : "")}
                onClick={() => setCcfListOpen((o) => !o)}
                title="Common-cause groups in this diagram"
              >
                ⚭ {ccfGroups.length} CC group{ccfGroups.length === 1 ? "" : "s"}
              </button>
              {ccfListOpen && (
                <div className="rbd-ccf-list">
                  <div className="rbd-ccf-list-h">Common-cause groups</div>
                  {ccfGroups.map((g) => (
                    <div className="rbd-ccf-row" key={g.id}>
                      <span className="rbd-ccf-row-members" title={(g.members || []).map(labelFor).join(", ")}>
                        {(g.members || []).map(labelFor).join(" · ")}
                      </span>
                      <button className="rbd-ccf-row-beta" onClick={() => editCcf(g)} title="Edit β">β={g.beta}{g.basis === "probability" ? " (prob.)" : ""}</button>
                      <button className="rbd-ccf-row-x" onClick={() => removeCcf(g.id)} title="Ungroup" aria-label="Ungroup">×</button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          </div>
          <div className="rbd-toolbar-actions">
          <button className="secondary sm" onClick={() => setModal("saverbd")}>
            Save RBD
          </button>
          <span
            className="rbd-export-wrap"
            title={savedRbdId ? PYTHON_EXPORT_TIP : "Save the diagram first"}
          >
            <button
              className="secondary sm"
              onClick={exportPython}
              disabled={!savedRbdId || !!exporting}
            >
              {exporting === "python" ? "Preparing…" : "Download as Python"}
            </button>
          </span>
          <span
            className="rbd-export-wrap"
            title={savedRbdId ? JSON_EXPORT_TIP : "Save the diagram first"}
          >
            <button
              className="secondary sm"
              onClick={() => exportAs("json")}
              disabled={!savedRbdId || !!exporting}
            >
              {exporting === "json" ? "Preparing…" : "Download as RePyability JSON"}
            </button>
          </span>
          <button className="secondary sm" onClick={autoLayout}>
            Auto-arrange
          </button>
          <button
            className="sm"
            onClick={runValidate}
            disabled={validating}
          >
            {validating ? "Validating…" : "Validate"}
          </button>
          </div>
        {selectedComponentIds.length >= 2 && (
          <div className="rbd-toolbar-float">
            <button className="secondary sm ccf" onClick={openCcfForSelection}
                    title="Couple these redundant components by a shared failure cause">
              ⚭ Common-cause group ({selectedComponentIds.length})
            </button>
          </div>
        )}
        {validation && (
          <div className="rbd-toolbar-float">
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
          </div>
        )}
        </Panel>
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
                  addKNode(menu.flow, 1, 2);
                  closeMenu();
                }}
                title="Merge parallel branches back into one — any branch is enough"
              >
                Add junction
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
              {/* A standby group works in both: repairable, its units are each repaired (#156). */}
              <button onClick={() => { addBlock("standby", menu.flow); closeMenu(); }}>
                Add standby node
              </button>
              {!repairable && (
                <>
                  <button onClick={() => { addBlock("loadshare", menu.flow); closeMenu(); }}>
                    Add load-sharing node
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
                </>
              )}
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
                        setModalNodeId(originalId(nodes, menu.id));
                        setModal("lifemodel");
                        closeMenu();
                      }}
                    >
                      {menu.repeat ? "Edit life model (original)" : "Edit life model"}
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
                {menu.nodeType === "loadshare" && (
                  <>
                    <button
                      onClick={() => {
                        const node = nodes.find((nd) => nd.id === menu.id);
                        setLoadshareCtx({ nodeId: menu.id, ...node?.data });
                        setModal("loadshare");
                        closeMenu();
                      }}
                    >
                      Edit load-sharing
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
                {menu.nodeType === "component" && !repairable && (
                  <button
                    onClick={() => {
                      repeatNode(menu.id);
                      closeMenu();
                    }}
                    title="Draw the same component again elsewhere (e.g. one power supply feeding two trains): it works or fails in every place at once"
                  >
                    Repeat block
                  </button>
                )}
                <button
                  onClick={() => {
                    cloneNode(menu.id);
                    closeMenu();
                  }}
                  title={menu.repeat ? "Another linked copy of the same component" : "An independent copy with its own model"}
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
        {connectHint ? (
          <span className="rbd-hint-flash">{connectHint}</span>
        ) : (
          <>
            Right-click the canvas to add a component · drag between handles, or
            select blocks and press <kbd>C</kbd>, to connect · double-click a block to edit
            {repairable
              ? " · double-click each component to set its repair time, costs and maintenance"
              : " · shift-click 2+ redundant components to add a common-cause group"}
          </>
        )}
      </div>

      {modal === "lifemodel" && (
        <LifeModelModal
          initial={nodes.find((n) => n.id === modalNodeId)?.data}
          repairable={repairable}
          crews={!!policies.repair_crews}
          groups={groupNames}
          onClose={() => {
            setModal(null);
            setModalNodeId(null);
          }}
          onSubmit={setNodeModel}
        />
      )}
      {modal === "ccf" && ccfCtx && (
        <CcfModal
          initial={ccfCtx}
          memberLabels={(ccfCtx.members || []).map(labelFor)}
          repairable={repairable}
          onClose={() => { setModal(null); setCcfCtx(null); }}
          onSubmit={submitCcf}
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
      {modal === "loadshare" && (
        <LoadShareModal
          initial={loadshareCtx}
          onClose={() => { setModal(null); setLoadshareCtx(null); }}
          onSubmit={submitLoadshare}
        />
      )}
      {modal === "standby" && (
        <StandbyModal
          initial={standbyCtx}
          repairable={repairable}
          crews={!!policies.repair_crews}
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
      {modal === "costs" && (
        <RbdCostsModal
          initial={diagramCosts}
          unit={rbdUnit}
          onClose={() => setModal(null)}
          onSubmit={(c) => { setDiagramCosts(c); setModal(null); }}
        />
      )}
      {modal === "crews" && (
        <RbdCrewsModal
          initial={policies}
          groupNames={groupNames}
          onClose={() => setModal(null)}
          onSubmit={(p) => { setPolicies(policyFields(p)); setModal(null); }}
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
        graph={{ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        validation={validation}
        stale={validationStale}
        rbdId={savedRbdId}
        name={savedRbdName}
        onBuild={toBuilder}
      />
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "tree" ? undefined : "none" }}
    >
      <RbdFaultTree
        graph={{ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        validation={validation}
        stale={validationStale}
        active={tab === "tree"}
        name={savedRbdName}
        onBuild={toBuilder}
      />
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "design" ? undefined : "none" }}
    >
      <RbdDesignPanel
        graph={{ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        onApply={applyDesign}
        onBuild={toBuilder}
        onView={() => {
          setTab("builder");
          // Once the canvas is shown again (it can't be fitted while hidden).
          window.setTimeout(() => fitView(FIT_OPTIONS), 60);
        }}
      />
    </div>
    {tab === "outages" && (
      <div className="rbd-calc-panel">
        <Suspense fallback={<p className="muted-line">Loading…</p>}>
          <OutageHistory
            rbdId={savedRbdId}
            graph={{ nodes, edges, unit: rbdUnit }}
            readOnly={savedRbdReadOnly}
            onBuild={toBuilder}
            onApplyModels={(updates) =>
              // Models fitted from the log, put on their blocks (unsaved).
              setNodes((nds) => nds.map((n) => (updates[n.id] ? { ...n, data: { ...n.data, ...updates[n.id] } } : n)))
            }
          />
        </Suspense>
      </div>
    )}
    </div>
    </RbdCcfContext.Provider>
    </RbdRepairableContext.Provider>
    </RbdUnitContext.Provider>
  );
}

export default function RbdBuilder() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const imported = id ? null : location.state?.imported || null;
  const [notesHidden, setNotesHidden] = useState(false);
  const [meta, setMeta] = useState({});
  return (
    <div className="app rbd-app">
      <PageHeader
        crumbs={[{ label: "RBDs", to: "/rbds" }, { label: "Saved diagrams", to: "/rbds/list" }]}
        title={meta.name || (id ? "" : "Untitled RBD")}
        id={meta.id || id}
        menu={meta.id && (
          <ShareButton
            collection="rbds"
            artifactId={meta.id}
            name={meta.name || "Untitled RBD"}
            readOnly={meta.readOnly}
            className="ovm-item"
          />
        )}
      />
      {imported && !notesHidden && (
        <div className="card note rbd-import-note">
          <p>
            <b>Imported from {imported.source_format || "file"}</b> — not saved yet. Check the blocks, then Save to keep it.
            {" "}<button className="link" onClick={() => setNotesHidden(true)}>Dismiss</button>
          </p>
          {imported.warnings?.length > 0 && (
            <ul>
              {imported.warnings.map((w, i) => <li key={i}>{w}</li>)}
            </ul>
          )}
        </div>
      )}
      <div className="card rbd-wrap">
        <ReactFlowProvider>
          <Builder
            key={id || "new"}
            rbdId={id}
            imported={imported}
            onNew={() => navigate("/rbds/b")}
            onOpenLibrary={() => navigate("/rbds/list")}
            onSaved={(savedId) => navigate(`/rbds/b/${savedId}`, { replace: true })}
            onMeta={setMeta}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
