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
  RbdRenameContext,
  RbdRepairableContext,
  RbdUnitContext,
  StructureNode,
} from "../components/RbdNodes.jsx";
import { lazy, Suspense } from "react";
import { unitInText } from "../components/unitText.js";
import PageHeader from "../components/ui/PageHeader.jsx";
import Chip from "../components/ui/Chip.jsx";
import Switch from "../components/ui/Switch.jsx";
import { formatPercent } from "../format.js";
import { allInstant, chainPairs, setInstantRepair, trackSelection } from "../rbdBuilderOps.js";
import { safetyStarter } from "../rbdSafetyStarter.js";

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

// Fitting the view fills the canvas's width (block text is sized to read at
// about 0.55), never zooms a small diagram past 0.75 (where block text is the
// page's size), and never zooms out so far that the text is unreadable: past
// that a large diagram is a pan away.
const FIT_OPTIONS = { padding: 0.02, minZoom: 0.45, maxZoom: 0.75, duration: 300 };
// The sized canvas (see sizeCanvas): its least height, the room kept above
// and below the diagram for the zoom controls, and the frame below it (the
// page's bottom padding).
const CANVAS_MIN = 300;
const CANVAS_PAD = 24;
const FRAME_BOTTOM = 20;

// A repairable diagram's crews, groups and safety settings (#156, #157): the
// graph keys that are set.
const POLICY_KEYS = ["repair_crews", "maintenance_groups", "safety_function", "target_sil"];
function policyFields(policies) {
  const out = {};
  for (const k of POLICY_KEYS) if (policies?.[k]) out[k] = policies[k];
  return out;
}

// A toolbar dropdown (#314): the trigger, and a menu of .ovm-item buttons that
// closes on an outside click or on choosing an item. Items stay mounted.
function ToolbarMenu({ label, title, aria, caret = true, className = "", children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div className={"ovm rbd-tb-menu " + className} ref={ref}>
      <button
        type="button"
        className="secondary sm rbd-tb-trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={aria}
        title={title}
        onClick={() => setOpen((o) => !o)}
      >
        {label}{caret && <span className="rbd-tb-caret"><Caret /></span>}
      </button>
      <div
        className="ovm-menu"
        hidden={!open}
        onClick={(e) => { if (e.target.closest(".ovm-item")) setOpen(false); }}
      >
        {children}
      </div>
    </div>
  );
}

const Caret = () => (
  <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
    <path d="M2.5 4.5 6 8l3.5-3.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

const MoreIcon = () => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor" aria-hidden="true">
    <circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" />
  </svg>
);

// Validation as a slim toolbar status (#314): "✓ Valid", "! Valid · 1 warning"
// or "✕ Not valid · 2 problems", toned by the worst item, that opens the full
// check. Before a check (or once the diagram has changed) it's the Validate
// button itself.
function ValidationStatus({ validation, stale, validating, onValidate }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);
  // A failed check opens itself: the problems are the next thing to read.
  useEffect(() => {
    if (validation && !validation.valid && !validation.empty) setOpen(true);
  }, [validation]);
  // Keep the open check on screen (a phone's toolbar puts the status mid-row).
  const popRef = useRef(null);
  useLayoutEffect(() => {
    const el = popRef.current;
    if (!open || !el) return;
    el.style.right = "";
    const { left, right } = el.getBoundingClientRect();
    const gap = 12;
    if (left < gap) el.style.right = `${left - gap}px`;
    else if (right > window.innerWidth - gap) el.style.right = `${right - (window.innerWidth - gap)}px`;
  }, [open]);

  if (validating || !validation || stale) {
    return (
      <button
        type="button"
        className="sm"
        onClick={onValidate}
        disabled={validating}
        title={stale ? "The diagram has changed since the last check" : "Check the diagram"}
      >
        {validating ? "Validating…" : "Validate"}
      </button>
    );
  }
  const errors = validation.errors?.length || 0;
  const warnings = validation.warnings?.length || 0;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const [tone, icon, text] = validation.empty
    ? ["todo", "+", "Nothing to check"]
    : !validation.valid
    ? ["bad", "✕", `Not valid${errors ? ` · ${plural(errors, "problem")}` : ""}`]
    : warnings
    ? ["caveat", "!", `Valid · ${plural(warnings, "warning")}`]
    : ["ok", "✓", "Valid"];
  return (
    <div className="ovm rbd-tb-menu" ref={ref}>
      <button
        type="button"
        className={`rbd-valid-toggle is-${tone}`}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <span aria-hidden="true">{icon}</span> {text}
        <span className="rbd-tb-caret"><Caret /></span>
      </button>
      <div className="ovm-menu rbd-valid-pop" hidden={!open} ref={popRef}>
        <ValidationPanel validation={validation} stale={false} />
        <button type="button" className="secondary sm" onClick={() => { setOpen(false); onValidate(); }}>
          Validate again
        </button>
      </div>
    </div>
  );
}

// Shared samples are stored with a "(sample)" suffix; the header says so with a chip.
const SAMPLE_SUFFIX = /\s*\(sample\)\s*$/i;

function Builder({ rbdId, imported, onNew, onOpenLibrary, onSaved, onMeta, onTab }) {
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
  // The canvas fills the frame; the result tabs scroll with the page (#311).
  useEffect(() => { onTab?.(tab); }, [onTab, tab]);
  // A tab's empty state (#271) sends the user back to the canvas — or, on a
  // read-only diagram, to save a copy (or, unsaved, to save it): the dialog
  // opens over the Builder.
  const toBuilder = useCallback(() => setTab("builder"), []);
  const saveFromTab = useCallback((which) => {
    setTab("builder");
    setModal(which);
  }, []);
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
  // The canvas is as tall as the diagram needs at the zoom that fits its
  // width, so a wide, flat diagram has no band of empty canvas above and
  // below it; between CANVAS_MIN and the frame. A phone, or a diagram with
  // next to nothing on it (room to build), keeps the whole frame. Returns
  // whether the canvas could be measured (not while its tab is hidden).
  const [canvasH, setCanvasH] = useState(null);
  const sizedRef = useRef(false);
  const sizeCanvas = useCallback(() => {
    const el = wrapper.current;
    const W = el?.clientWidth || 0;
    if (!W) return false;
    const placed = getNodes().filter((n) => n.width && n.height);
    if (W < 640 || placed.length <= 3) {
      setCanvasH(null);
      return true;
    }
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const n of placed) {
      const p = n.positionAbsolute || n.position;
      x0 = Math.min(x0, p.x);
      x1 = Math.max(x1, p.x + n.width);
      y0 = Math.min(y0, p.y);
      y1 = Math.max(y1, p.y + n.height);
    }
    const k = 1 + FIT_OPTIONS.padding;
    const zoom = Math.min(FIT_OPTIONS.maxZoom, Math.max(FIT_OPTIONS.minZoom, W / ((x1 - x0) * k)));
    const want = Math.ceil((y1 - y0) * k * zoom) + 2 * CANVAS_PAD;
    const room = window.innerHeight - el.getBoundingClientRect().top - FRAME_BOTTOM;
    setCanvasH(Math.round(Math.max(CANVAS_MIN, Math.min(want, room))));
    return true;
  }, [getNodes]);
  const fitWhenMeasured = useCallback((expected) => {
    const ids = (expected || []).map((n) => n.id);
    let frames = 0;
    const attempt = () => {
      const byId = new Map(getNodes().map((n) => [n.id, n]));
      const ready = ids.every((id) => byId.get(id)?.width && byId.get(id)?.height);
      if ((ready && frames > 0) || frames > 60) {
        sizedRef.current = sizeCanvas();
        // Fit once React Flow has seen the canvas's new height.
        window.requestAnimationFrame(() => window.requestAnimationFrame(() => fitViewRef.current(FIT_OPTIONS)));
      } else {
        frames += 1;
        window.requestAnimationFrame(attempt);
      }
    };
    window.requestAnimationFrame(attempt);
  }, [getNodes, sizeCanvas]);
  // A diagram loaded while another tab showed is sized when the canvas is.
  useEffect(() => {
    if (tab === "builder" && !sizedRef.current) fitWhenMeasured();
  }, [tab, fitWhenMeasured]);
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
      return v;
    } catch (err) {
      const v = {
        valid: false,
        analytic: false,
        can_calculate: false,
        errors: [err.message],
        warnings: [],
        non_analytic_nodes: {},
      };
      setValidation(v);
      setCheckedSig(graphSignature({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }));
      return v;
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
  // Clicked one at a time (#299), the blocks are wired in the order clicked:
  // a series chain, whatever their positions on screen.
  const clickOrder = useRef({ ids: [], ordered: true });
  const onSelectionChange = useCallback(({ nodes: selected }) => {
    clickOrder.current = trackSelection(clickOrder.current, (selected || []).map((n) => n.id));
  }, []);
  const connectSelected = useCallback(() => {
    const chosen = nodes.filter((n) => n.selected);
    if (chosen.length < 2) {
      setConnectHint("Click two or more blocks in order (shift-click), then press C.");
      return;
    }
    const order = clickOrder.current;
    const chosenIds = new Set(chosen.map((n) => n.id));
    if (order.ordered && order.ids.length === chosen.length && order.ids.every((id) => chosenIds.has(id))) {
      let added = 0;
      setEdges((eds) => {
        const next = chainPairs(order.ids).reduce(
          (acc, [source, target]) => addEdge({ source, target, ...EDGE_OPTIONS }, acc),
          eds
        );
        added = next.length - eds.length;
        return next;
      });
      setConnectHint(
        added
          ? `Connected ${added} link${added === 1 ? "" : "s"} in the order you clicked.`
          : "Those blocks are already connected."
      );
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

  // A new block in a diagram whose every block is repaired instantly is too
  // (#299: set once for the whole diagram).
  const addComponent = useCallback(
    (flowPos) => {
      const n = idRef.current++;
      const id = `c${n}`;
      setNodes((nds) =>
        nds.concat({
          id,
          type: "component",
          data: {
            label: `Component ${n}`, model: null,
            ...(repairable && allInstant(nds) ? { instant_repair: true } : {}),
          },
          position: flowPos || { x: 240, y: 40 + ((n * 70) % 200) },
          ...HORIZONTAL,
        })
      );
    },
    [setNodes, repairable]
  );

  const addKNode = useCallback(
    (flowPos, n, k, label = null) => {
      const i = idRef.current++;
      setNodes((nds) =>
        nds.concat({
          id: `k${i}`,
          type: "knode",
          data: { n, k, ...(label ? { label } : {}) },
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
    ({ n, k, label }) => {
      if (knodeCtx?.mode === "edit") {
        setNodes((nds) =>
          nds.map((node) => {
            if (node.id !== knodeCtx.nodeId) return node;
            const { label: _old, ...rest } = node.data;
            return { ...node, data: { ...rest, n, k, ...(label ? { label } : {}) } };
          })
        );
      } else {
        addKNode(knodeCtx?.flowPos, n, k, label);
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
  // ``asNew`` (Save as new) saves a copy under a new id and opens it.
  const onSaveRbd = useCallback(
    async (name, asNew = false) => {
      const graph = { nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField };
      const saved = await saveRbd(name, graph, asNew ? null : savedRbdId, asNew ? null : savedRbdUpdatedAt);
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
    ({ model, repair, extras, label }) => {
      setNodes((nds) =>
        nds.map((node) =>
          node.id === modalNodeId
            ? { ...node, data: applyBlockExtras({
                ...node.data, model, ...(repair !== undefined ? { repair } : {}), ...(label ? { label } : {}),
              }, extras) }
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
            label: node.data?.label || "",
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

  // Inline rename (#289): double-click a block's name, or select it and
  // press F2. A repeated block renames the block it repeats.
  const [renaming, setRenaming] = useState(null);
  const rename = useMemo(() => ({
    renaming,
    start: (id) => { closeMenu(); setRenaming(id); },
    cancel: () => setRenaming(null),
    commit: (id, label) => {
      const name = String(label || "").trim();
      if (name) {
        setNodes((nds) => {
          const target = originalId(nds, id);
          return nds.map((n) => (n.id === target ? { ...n, data: { ...n.data, label: name } } : n));
        });
      }
      setRenaming(null);
    },
  }), [renaming, closeMenu, setNodes]);
  useEffect(() => {
    if (tab !== "builder" || modal || renaming) return undefined;
    const onKey = (e) => {
      if (e.key !== "F2") return;
      const el = e.target;
      if (el?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName)) return;
      const chosen = liveRef.current.nodes.filter((n) => n.selected && n.type !== "input" && n.type !== "output");
      // One block selected, or of several the one clicked last.
      const last = clickOrder.current.ids[clickOrder.current.ids.length - 1];
      const target = chosen.length === 1 ? chosen[0].id : chosen.some((n) => n.id === last) ? last : null;
      if (!target) return;
      e.preventDefault();
      rename.start(target);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, modal, renaming, rename]);

  // "+ Add block" (#299): the block lands in the middle of the canvas in view,
  // a step down and right of the last one so a few in a row don't stack.
  const addOffset = useRef(0);
  const centrePos = useCallback(() => {
    const r = wrapper.current?.getBoundingClientRect();
    if (!r) return undefined;
    const step = (addOffset.current++ % 5) * 40;
    const p = screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
    return { x: p.x - 80 + step, y: p.y - 30 + step };
  }, [screenToFlowPosition]);

  // The toolbar's Safety function switch (#298): on, the diagram is a
  // repairable safety function (its results lead with PFDavg and the SIL);
  // off, it isn't, and its target SIL goes with it.
  const setSafety = useCallback((on) => {
    setPolicies((p) => policyFields({ ...p, safety_function: on || null, target_sil: on ? p.target_sil : null }));
    if (on) setRepairable(true);
  }, []);

  // "Repaired instantly", once for the whole diagram (#299).
  const everyInstant = useMemo(() => allInstant(nodes), [nodes]);
  const toggleAllInstant = useCallback(() => {
    setNodes((nds) => setInstantRepair(nds, !allInstant(nds)));
  }, [setNodes]);

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
  const withBasis = (g, beta, basis, mgl) => {
    const { basis: _old, mgl: _letters, ...rest } = g;
    // The multiple Greek letter model's letters after β, when chosen (#84).
    const out = basis === "probability" ? { ...rest, beta, basis } : { ...rest, beta };
    return mgl?.length ? { ...out, mgl } : out;
  };
  const submitCcf = ({ beta, basis, mgl }) => {
    setCcfGroups((prev) => {
      if (ccfCtx?.groupId) return prev.map((g) => (g.id === ccfCtx.groupId ? withBasis(g, beta, basis, mgl) : g));
      const id = `ccf-${Date.now().toString(36)}-${Math.round(Math.random() * 1e4)}`;
      return [...prev, withBasis({ id, members: ccfCtx.members }, beta, basis, mgl)];
    });
    setModal(null);
    setCcfCtx(null);
  };
  const editCcf = (g) => {
    setCcfCtx({ members: g.members, beta: g.beta, basis: g.basis, mgl: g.mgl, groupId: g.id });
    setModal("ccf");
  };
  const removeCcf = (gid) => setCcfGroups((prev) => prev.filter((g) => g.id !== gid));

  return (
    <RbdUnitContext.Provider value={rbdUnit}>
    <RbdRepairableContext.Provider value={repairable}>
    <RbdCcfContext.Provider value={ccfMap}>
    <RbdRenameContext.Provider value={rename}>
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
    <div className="rbd-builder" style={{ display: tab === "builder" ? undefined : "none" }}>
    {/* One row above the canvas (#314): the diagram's settings on the left;
        Validate, Save ▾ and ⋯ on the right. On a phone the settings move into ⋯. */}
    <div className="rbd-toolbar">
      {/* Add a block without right-clicking (#299); on a phone the only way. */}
      <ToolbarMenu label={<span>+ Add<span className="rbd-add-word"> block</span></span>} title="Add a block to the middle of the canvas"
                   aria="Add block" className="rbd-add-menu">
        <button className="ovm-item" onClick={() => addComponent(centrePos())}>Component</button>
        <button className="ovm-item" onClick={() => addKNode(centrePos(), 1, 2)}
                title="Merge parallel branches back into one — any branch is enough">
          Junction
        </button>
        <button className="ovm-item" onClick={() => {
          setKnodeCtx({ mode: "add", flowPos: centrePos(), n: 2, k: 3 });
          setModal("knode");
        }}>
          Voting node (MooN)…
        </button>
        <button className="ovm-item" onClick={() => addBlock("standby", centrePos())}>Standby group</button>
        {!repairable && (
          <>
            <button className="ovm-item" onClick={() => addBlock("loadshare", centrePos())}>Load-sharing</button>
            <button className="ovm-item" onClick={() => addBlock("series", centrePos())}>Series (n identical)</button>
            <button className="ovm-item" onClick={() => addBlock("parallel", centrePos())}>Parallel (n identical)</button>
            <button className="ovm-item" onClick={() => addBlock("subsystem", centrePos())}>Sub-system</button>
          </>
        )}
      </ToolbarMenu>
      <div className="rbd-toolbar-row rbd-tb-settings">
        <label className="rbd-unit-field">
          <span>Unit</span>
          <input
            className="rbd-unit-input"
            list="rbd-time-units"
            placeholder="e.g. Hours"
            value={rbdUnit}
            onChange={(e) => setRbdUnit(e.target.value)}
          />
        </label>
        <Select
          className="rbd-mode-select"
          value={repairable ? "repairable" : "non"}
          onChange={(v) => setRepairable(v === "repairable")}
          title="Repairable diagrams analyse availability (uptime) — every component also needs a repair-time distribution. Non-repairable diagrams analyse reliability over time."
          options={[
            { value: "non", label: "Non-repairable" },
            { value: "repairable", label: "Repairable" },
          ]}
        />
        {/* A safety function (#298): on, the results lead with PFDavg and the SIL. */}
        <Switch
          className="rbd-safety-switch"
          checked={repairable && !!policies.safety_function}
          onChange={setSafety}
          label="Safety function"
          title="A safety instrumented function (IEC 61511): its results lead with PFDavg and the SIL band. Turning it on makes the diagram repairable."
        />
        {repairable && policies.safety_function && (
          <Chip onClick={() => setModal("safety")} title="The SIL this function must meet. Click to change it.">
            {policies.target_sil ? `Target SIL ${policies.target_sil}` : "Set a target SIL"}
          </Chip>
        )}
        {/* Common-cause groups: a chip that drops the list beneath it. */}
        {ccfGroups.length > 0 && (
          <div className="rbd-ccf-menu">
            <Chip
              className={ccfListOpen ? "open" : ""}
              onClick={() => setCcfListOpen((o) => !o)}
              title="Common-cause groups in this diagram"
            >
              ⚭ {ccfGroups.length} common-cause group{ccfGroups.length === 1 ? "" : "s"}
            </Chip>
            {ccfListOpen && (
              <div className="rbd-ccf-list">
                <div className="rbd-ccf-list-h">Common-cause groups</div>
                {ccfGroups.map((g) => (
                  <div className="rbd-ccf-row" key={g.id}>
                    <span className="rbd-ccf-row-members" title={(g.members || []).map(labelFor).join(", ")}>
                      {(g.members || []).map(labelFor).join(" · ")}
                    </span>
                    <button className="rbd-ccf-row-beta" onClick={() => editCcf(g)} title="Edit β">β {formatPercent(g.beta)}{g.mgl?.length ? " · MGL" : ""}{g.basis === "probability" ? " (prob.)" : ""}</button>
                    <button className="rbd-ccf-row-x" onClick={() => removeCcf(g.id)} title="Ungroup" aria-label="Ungroup">×</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
      <datalist id="rbd-time-units">
        {TIME_UNITS.map((u) => (
          <option value={u} key={u} />
        ))}
      </datalist>
      <div className="rbd-toolbar-actions">
        <ValidationStatus
          validation={validation}
          stale={validationStale}
          validating={validating}
          onValidate={runValidate}
        />
        <ToolbarMenu label="Save" title="Save, or download the saved diagram">
          <button className="ovm-item" onClick={() => setModal("saverbd")}>Save…</button>
          {savedRbdId && (
            <button className="ovm-item" onClick={() => setModal("saveasnew")}>Save as new…</button>
          )}
          <button
            className="ovm-item"
            onClick={exportPython}
            disabled={!savedRbdId || !!exporting}
            title={savedRbdId ? PYTHON_EXPORT_TIP : "Save the diagram first"}
          >
            {exporting === "python" ? "Preparing…" : "Download as Python"}
          </button>
          <button
            className="ovm-item"
            onClick={() => exportAs("json")}
            disabled={!savedRbdId || !!exporting}
            title={savedRbdId ? JSON_EXPORT_TIP : "Save the diagram first"}
          >
            {exporting === "json" ? "Preparing…" : "Download as RePyability JSON"}
          </button>
        </ToolbarMenu>
        <ToolbarMenu label={<MoreIcon />} title="More" aria="More diagram settings" caret={false}>
          {/* On a phone the toolbar's settings live here (#301). */}
          <div className="rbd-ovm-settings">
            <label>
              <span>Unit</span>
              <input
                list="rbd-time-units"
                placeholder="e.g. Hours"
                value={rbdUnit}
                onChange={(e) => setRbdUnit(e.target.value)}
              />
            </label>
            <label>
              <span>System</span>
              <select value={repairable ? "repairable" : "non"} onChange={(e) => setRepairable(e.target.value === "repairable")}>
                <option value="non">Non-repairable</option>
                <option value="repairable">Repairable</option>
              </select>
            </label>
          </div>
          <button className="ovm-item" onClick={autoLayout}>Auto-arrange</button>
          {repairable && (
            <button
              className="ovm-item"
              role="menuitemcheckbox"
              aria-checked={everyInstant}
              onClick={toggleAllInstant}
              title={everyInstant
                ? "Every block is repaired instantly: it still fails and costs, but is never down. Click to use each block's repair time again."
                : "Repair every block instantly — it still fails and costs, but is never down (e.g. proof-tested channels, or no repair-time data). Each block's repair time is kept for later."}
            >
              Every block repaired instantly{everyInstant ? " ✓" : ""}
            </button>
          )}
          {repairable && (
            <button
              className="ovm-item"
              onClick={() => setModal("costs")}
              title={
                diagramCosts?.downtime_rate != null
                  ? `System downtime costs ${Number(diagramCosts.downtime_rate).toLocaleString()} per ${(unitInText(rbdUnit) || "time unit").replace(/s$/, "")}`
                  : "System downtime cost and ownership horizon (block costs are on each block)"
              }
            >
              Costs…{diagramCosts ? " ✓" : ""}
            </button>
          )}
          {repairable && (
            <button
              className="ovm-item"
              onClick={() => setModal("crews")}
              title="Repair crews shared by the blocks, and maintenance groups' set-up costs"
            >
              Crews and groups…
              {policies.repair_crews?.crews
                ? ` (${policies.repair_crews.crews} crew${policies.repair_crews.crews === 1 ? "" : "s"})`
                : ""}
            </button>
          )}
          <button
            className="ovm-item"
            onClick={() => setModal("safety")}
            title="A safety instrumented function: report PFDavg and the SIL"
          >
            Safety function…{repairable && policies.safety_function ? " ✓" : ""}
          </button>
        </ToolbarMenu>
      </div>
    </div>
    <div
      className={"rbd-canvas" + (canvasH ? " is-sized" : "")}
      ref={wrapper}
      style={canvasH ? { height: canvasH } : undefined}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodesChange={handleNodesChange}
        onEdgesChange={onEdgesChange}
        onSelectionChange={onSelectionChange}
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
        <Panel position="top-center" className="rbd-float-panel">
        {selectedComponentIds.length >= 2 && (
          <div className="rbd-toolbar-float">
            <button className="secondary sm ccf" onClick={openCcfForSelection}
                    title="Couple these redundant components by a shared failure cause">
              ⚭ Common-cause group ({selectedComponentIds.length})
            </button>
          </div>
        )}
        </Panel>
        <Background gap={22} />
        <Controls showInteractive={false} onFitView={() => fitWhenMeasured()} />
        {/* Only for a large diagram (#314): on a small one it covers blocks. */}
        {nodes.length > 15 && <MiniMap pannable zoomable />}
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
                Add voting node (MooN)
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
                          label: node?.data.label || "",
                        });
                        setModal("knode");
                        closeMenu();
                      }}
                    >
                      Edit vote (MooN)
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

      {/* One short line until the first connection (#314); the C shortcut's
          feedback flashes here too. */}
      {(connectHint || edges.length === 0) && (
        <div className="rbd-hint">
          {connectHint ? (
            <span className="rbd-hint-flash">{connectHint}</span>
          ) : (
            "Add blocks with + Add block or a right-click · drag to connect · double-click to edit"
          )}
        </div>
      )}

      {modal === "lifemodel" && (
        <LifeModelModal
          initial={nodes.find((n) => n.id === modalNodeId)?.data}
          repairable={repairable}
          crews={!!policies.repair_crews}
          groups={groupNames}
          safety={repairable && !!policies.safety_function}
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
      {(modal === "crews" || modal === "safety") && (
        <RbdCrewsModal
          section={modal}
          initial={policies}
          groupNames={groupNames}
          repairable={repairable}
          onClose={() => setModal(null)}
          onSubmit={(p) => {
            setPolicies(policyFields(p));
            // A safety function is a repairable diagram's analysis (#298).
            if (p.safety_function) setRepairable(true);
            setModal(null);
          }}
        />
      )}
      {modal === "saverbd" && (
        <RbdSaveModal
          initialName={savedRbdName}
          onClose={() => setModal(null)}
          onSubmit={onSaveRbd}
        />
      )}
      {modal === "saveasnew" && (
        <RbdSaveModal
          asNew
          initialName={savedRbdName ? `${savedRbdName.replace(SAMPLE_SUFFIX, "")} (copy)` : ""}
          onClose={() => setModal(null)}
          onSubmit={(name) => onSaveRbd(name, true)}
        />
      )}
    </div>
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "calc" ? undefined : "none" }}
    >
      <RbdCalculator
        graph={{ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        validation={validation}
        stale={validationStale}
        onValidate={runValidate}
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
        readOnly={savedRbdReadOnly}
        onSaveCopy={savedRbdId ? () => saveFromTab("saveasnew") : null}
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
            onSave={() => saveFromTab("saverbd")}
            onSaveCopy={savedRbdId ? () => saveFromTab("saveasnew") : null}
            onApplyModels={(updates) =>
              // Models fitted from the log, put on their blocks (unsaved).
              setNodes((nds) => nds.map((n) => (updates[n.id] ? { ...n, data: { ...n.data, ...updates[n.id] } } : n)))
            }
          />
        </Suspense>
      </div>
    )}
    </div>
    </RbdRenameContext.Provider>
    </RbdCcfContext.Provider>
    </RbdRepairableContext.Provider>
    </RbdUnitContext.Provider>
  );
}

export default function RbdBuilder() {
  const { id } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  // An imported diagram, or the safety function starter (#298), opens unsaved.
  const starterKind = id ? null : location.state?.starter || null;
  const starter = useMemo(() => (starterKind === "safety" ? safetyStarter() : null),
    // A fresh copy each time the starter is opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [starterKind, location.key]);
  const imported = id ? null : location.state?.imported || starter;
  const [notesHidden, setNotesHidden] = useState(false);
  const [meta, setMeta] = useState({});
  const [tab, setTab] = useState("builder");
  return (
    <div className={"app rbd-app" + (tab === "builder" ? "" : " rbd-app-scroll")}>
      <PageHeader
        crumbs={[{ label: "RBDs", to: "/rbds" }]}
        title={(meta.name || "").replace(SAMPLE_SUFFIX, "") || (id ? "" : "Untitled RBD")}
        badges={SAMPLE_SUFFIX.test(meta.name || "") && <Chip>Sample</Chip>}
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
          {imported.starter ? (
            <p>
              <b>A starter safety function</b> — not saved yet. Calculate it as it is, or rename the blocks and set
              each one’s λDU and proof test to your loop’s, then Save.
              {" "}<button className="link" onClick={() => setNotesHidden(true)}>Dismiss</button>
            </p>
          ) : (
            <p>
              <b>Imported from {imported.source_format || "file"}</b> — not saved yet. Check the blocks, then Save to keep it.
              {" "}<button className="link" onClick={() => setNotesHidden(true)}>Dismiss</button>
            </p>
          )}
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
            key={id || (starter ? `starter-${location.key}` : "new")}
            rbdId={id}
            imported={imported}
            onNew={() => navigate("/rbds/b")}
            onOpenLibrary={() => navigate("/rbds")}
            onSaved={(savedId) => navigate(`/rbds/b/${savedId}`, { replace: true })}
            onMeta={setMeta}
            onTab={setTab}
          />
        </ReactFlowProvider>
      </div>
    </div>
  );
}
