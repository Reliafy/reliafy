import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import useMenuDismiss from "./useMenuDismiss.js";
import { Link } from "react-router-dom";
import { CloseIcon } from "./icons.jsx";
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
import LifeModelModal from "./LifeModelModal.jsx";
import CcfModal from "./CcfModal.jsx";
import KNodeModal from "./KNodeModal.jsx";
import CountModal from "./CountModal.jsx";
import StandbyModal from "./StandbyModal.jsx";
import LoadShareModal from "./LoadShareModal.jsx";
import Select from "./Select.jsx";
import SubsystemModal from "./SubsystemModal.jsx";
import RbdSaveModal from "./RbdSaveModal.jsx";
import RbdCalculator from "./RbdCalculator.jsx";
import RbdFaultTree from "./RbdFaultTree.jsx";
import RbdDesignPanel from "./RbdDesignPanel.jsx";
import RbdTargets from "./RbdTargets.jsx";
import RbdCostsModal from "./RbdCostsModal.jsx";
import RbdCrewsModal from "./RbdCrewsModal.jsx";
import RbdMaintenancePlan from "./RbdMaintenancePlan.jsx";
import { applyBlockExtras } from "./RbdBlockCosts.jsx";
import ValidationPanel, { emptyStatus, graphSignature } from "./RbdValidation.jsx";
import {
  saveRbd, getRbd, validateRbd, expandRbdSubsystems, downloadRbdPython, PYTHON_EXPORT_TIP, downloadRbdJson, JSON_EXPORT_TIP,
} from "../api.js";
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
} from "./RbdNodes.jsx";
import { lazy, Suspense } from "react";
import { unitInText } from "./unitText.js";
import Chip from "./ui/Chip.jsx";
import Switch from "./ui/Switch.jsx";
import { formatPercent } from "../format.js";
import {
  allInstant, chainPairs, clearSpot, copyForAlongside, inPlaceItems, insertAfter, insertAlongside, insertFirst, insertOnEdge, setInstantRepair, trackSelection,
} from "../rbdBuilderOps.js";
// Phased missions and undirected networks (#160).
import RbdPhasesModal from "./RbdPhasesModal.jsx";
import RbdPhasesResult from "./RbdPhasesResult.jsx";
import RbdNetworkPanel, { NetworkOnlyNote } from "./RbdNetworkPanel.jsx";
import { MISSION_KEYS, missionFields, undirectedEdges } from "../rbdMission.js";
import { graphWithModel, plainName } from "../modelNext.js";
import Tabs from "./ui/Tabs.jsx";
import useFullScreen from "./useFullScreen.js";
import FullScreenButton from "./FullScreenButton.jsx";
import { hasOpenLayer, isFullScreenKey, isTyping } from "../fullScreen.js";
import { rbdDirty, rbdSaveSnapshot, rbdSaveStatus } from "../rbdSaveState.js";
import { builderWidthClass } from "../rbdEditorLayout.js";
import { applyTreePlan, treeGraph, treeKey, treePositionPath, treeRow } from "../rbdTreePlan.js";
import { getRbdTreePlan } from "../api.js";
import { useRoles } from "../RolesProvider.jsx";

// The "Outage history" tab (an observed-history import and charts) loads on
// first open, so the builder's own bundle doesn't carry it.
const OutageHistory = lazy(() => import("./OutageHistory.jsx"));
// ?tab=outages (the MCP tools' links) opens the builder on that tab.
const initialTab = () =>
  typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tab") === "outages"
    ? "outages"
    : "builder";
// The result tabs; on a phone the row scrolls, with a cue on the hidden side.
const RBD_TABS = [
  { id: "builder", label: "Builder" },
  { id: "calc", label: "Calculator", wt: "rbd-tab-calc" },
  { id: "tree", label: "Fault tree" },
  { id: "design", label: "Design", title: "How many copies of each block: most reliable within a budget, or cheapest to reach a target" },
  { id: "targets", label: "Targets", title: "What each block needs for the system to meet a target" },
  { id: "outages", label: "Outage history" },
];

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
// On a phone the whole diagram fits on load, however small that makes it: a
// diagram cut off at both edges looks broken, and a pinch zooms in. The same
// in a pane beside the tree (``whole``), which is narrow at any screen width.
const PHONE_CANVAS = 600;
function fitOptionsFor(width, whole = false) {
  return whole || (width && width <= PHONE_CANVAS) ? { ...FIT_OPTIONS, minZoom: 0.2 } : FIT_OPTIONS;
}
// The sized canvas (see sizeCanvas): its least height (the unsized canvas's
// own) and the frame below it (the page's bottom padding).
const CANVAS_MIN = 440;
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
// closes like every menu (useMenuDismiss) or on choosing an item. Items stay mounted.
function ToolbarMenu({ label, title, aria, caret = true, className = "", wt, children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const close = useCallback(() => setOpen(false), []);
  useMenuDismiss(open, close, ref);
  return (
    <div className={"ovm rbd-tb-menu " + className} ref={ref} data-wt={wt}>
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
    ? ["todo", emptyStatus(validation).icon, emptyStatus(validation).text]
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
export const SAMPLE_SUFFIX = /\s*\(sample\)\s*$/i;

function Builder({ rbdId, imported, embedded = false, pane = null, onSaved, onMeta, onTab, onDirty, addModel = null, onModelAdded, onLoadError }) {
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
  // The demand the blocks' capacities serve (#122): {demand, unit, period}.
  const [production, setProduction] = useState(null);
  // A phased mission's phases and a network's terminals (#160): {phases, network}.
  const [mission, setMission] = useState({});
  // The diagram's Use and Environment values, which blocks with covariates left open at their
  // positions take (covariate_binding.py): [{name, role, unit, value}].
  const [conditions, setConditions] = useState([]);
  const network = !!mission.network;
  // Carried with the diagram wherever the costs are (save, validate, analyse).
  const costsField = useMemo(
    () => ({
      ...(diagramCosts ? { costs: diagramCosts } : {}),
      ...policyFields(policies),
      ...(production ? { production } : {}),
      ...mission,
      ...(conditions.length ? { conditions } : {}),
    }),
    [diagramCosts, policies, production, mission, conditions]
  );
  // The diagram's kind: a block diagram (non-repairable or repairable) or a
  // network. Phases are kept (a network ignores them) so switching back
  // doesn't lose them.
  const setMode = useCallback((v) => {
    setRepairable(v === "repairable");
    setMission((m) => {
      const { network: _n, ...rest } = m;
      return v === "network" ? { ...rest, network: { source: "input", target: "output" } } : rest;
    });
  }, []);
  const [ccfCtx, setCcfCtx] = useState(null); // { members, beta, groupId? } for the modal
  // ?tab=outages is the page's: in the Explorer, ?tab= is the Explorer's own.
  // The Maintenance plan (repairable): a table under the canvas, the one place planned work is edited.
  const [planOpen, setPlanOpen] = useState(false);
  const [tab, setTab] = useState(() => (embedded ? "builder" : initialTab())); // 'builder' | 'calc' | 'tree' | 'design' | 'targets' | 'outages'
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
  // The diagram the route last loaded (an id, or the imported graph): loaded
  // once each. A save sets it to the saved id, so the route catching up with
  // the save doesn't load the diagram again.
  const loadedRef = useRef(null);
  // Full screen (the toolbar and canvas cover the screen). One Builder either
  // way: only its container's classes change, so nothing on the canvas resets.
  const builderRef = useRef(null);
  const fullBtnRef = useRef(null); // the button on show: on the canvas, or Exit in the toolbar
  const { full, toggle: toggleFull, exit: exitFull } = useFullScreen(builderRef, { returnFocus: fullBtnRef });
  // Saved or not, for the full-screen status (the page's title is hidden there):
  // the diagram as last opened or saved, against the canvas now.
  const [savedSnap, setSavedSnap] = useState(null);
  const rebaseRef = useRef(true);
  // Always-current snapshot of the canvas, so the AI assistant can read the
  // live diagram via the bridge without stale-closure issues.
  const liveRef = useRef({ nodes: [], edges: [], unit: "" });
  liveRef.current = { nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField };
  const { screenToFlowPosition, fitView, getNodes, getEdges, deleteElements } = useReactFlow();
  // The builder's own width (NARROW_BUILDER): measured, as the pane beside the tree is narrower
  // than the screen (and full screen wider than the page). 0 while another tab shows.
  const shellRef = useRef(null);
  const [builderW, setBuilderW] = useState(0);
  useLayoutEffect(() => {
    const el = builderRef.current;
    if (!el) return undefined;
    setBuilderW(el.clientWidth);
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(() => setBuilderW(el.clientWidth));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  // A key for the builder: on the page, anywhere; in the Explorer, only from inside the builder
  // (or with nothing focused, after a click on the canvas), so the tree's keys stay the tree's.
  const ownsKey = useCallback((e) => {
    if (!embedded) return true;
    const t = e.target;
    return !t || t === document.body || t === document.documentElement || !!shellRef.current?.contains(t);
  }, [embedded]);
  // Fit once React Flow has measured the nodes just set (#309). A saved
  // diagram reopened with blocks off-screen: its load ran in a callback from
  // the first render, whose fitView was React Flow's no-op stand-in (the
  // viewport wasn't ready), and fitting in the next frame came before the
  // nodes had sizes. So: the current fitView, once every one of ``expected``
  // is in the flow with a size (a second at most).
  const fitViewRef = useRef(fitView);
  fitViewRef.current = fitView;
  // The canvas runs down to the bottom of the frame (never under CANVAS_MIN),
  // so a wide, flat diagram doesn't leave the page empty below the card; the
  // fit then centres it. A phone, or a diagram with next to nothing on it
  // (room to build), keeps the whole frame. Returns whether the canvas could
  // be measured (not while its tab is hidden).
  const [canvasH, setCanvasH] = useState(null);
  const sizedRef = useRef(false);
  const sizeCanvas = useCallback(() => {
    const el = wrapper.current;
    const W = el?.clientWidth || 0;
    if (!W) return false;
    const placed = getNodes().filter((n) => n.width && n.height);
    // In the Explorer's table area the canvas fills the pane (CSS), whatever the diagram.
    if (embedded || W < 640 || placed.length <= 3) {
      setCanvasH(null);
      return true;
    }
    const room = window.innerHeight - el.getBoundingClientRect().top - FRAME_BOTTOM;
    setCanvasH(Math.round(Math.max(CANVAS_MIN, room)));
    return true;
  }, [getNodes, embedded]);
  const fitWhenMeasured = useCallback((expected) => {
    const ids = (expected || []).map((n) => n.id);
    let frames = 0;
    const attempt = () => {
      const byId = new Map(getNodes().map((n) => [n.id, n]));
      const ready = ids.every((id) => byId.get(id)?.width && byId.get(id)?.height);
      if ((ready && frames > 0) || frames > 60) {
        sizedRef.current = sizeCanvas();
        // Fit once React Flow has seen the canvas's new height.
        window.requestAnimationFrame(() => window.requestAnimationFrame(
          () => fitViewRef.current(fitOptionsFor(wrapper.current?.clientWidth, embedded))));
      } else {
        frames += 1;
        window.requestAnimationFrame(attempt);
      }
    };
    window.requestAnimationFrame(attempt);
  }, [getNodes, sizeCanvas, embedded]);
  // A diagram loaded while another tab showed is sized when the canvas is.
  useEffect(() => {
    if (tab === "builder" && !sizedRef.current) fitWhenMeasured();
  }, [tab, fitWhenMeasured]);
  // In a pane beside the tree the canvas changes size after the diagram is first fitted (the tree
  // takes its width once its rows are read), which left the diagram fitted to a canvas that was
  // no longer there: part of it off one side. So there it is fitted again whenever the canvas
  // changes size, until the reader moves the view themselves.
  const movedRef = useRef(false);
  useEffect(() => {
    const el = wrapper.current;
    if (!embedded || !el || typeof ResizeObserver === "undefined") return undefined;
    let w = el.clientWidth;
    let h = el.clientHeight;
    let timer = 0;
    const ro = new ResizeObserver(() => {
      if (el.clientWidth === w && el.clientHeight === h) return;
      w = el.clientWidth;
      h = el.clientHeight;
      if (movedRef.current || !w || !h) return;
      window.clearTimeout(timer);
      timer = window.setTimeout(() => fitViewRef.current({ ...fitOptionsFor(w, true), duration: 0 }), 60);
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      window.clearTimeout(timer);
    };
  }, [embedded]);
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

  // A diagram linked to a position (built from it, or a New blank RBD there): each block standing
  // for a position takes its planned work from that position's tasks (rbdTreePlan.js), read now
  // and again when the blocks change or the window comes back into view. Nothing is copied into
  // the diagram: calculations use calcNodes, saving uses nodes.
  const maintenanceOn = !!useRoles()?.has?.maintenance;
  const [treePlan, setTreePlan] = useState(null);
  const [treeTick, setTreeTick] = useState(0);
  const blocksKey = useMemo(() => treeKey(nodes, rbdUnit), [nodes, rbdUnit]);
  useEffect(() => {
    if (!maintenanceOn || !savedRbdId) {
      setTreePlan(null);
      return undefined;
    }
    let live = true;
    const t = setTimeout(() => {
      getRbdTreePlan(savedRbdId, treeGraph(liveRef.current.nodes, liveRef.current.unit))
        .then((d) => live && setTreePlan(d?.position ? d : null))
        .catch(() => live && setTreePlan(null));
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [maintenanceOn, savedRbdId, blocksKey, treeTick]);
  useEffect(() => {
    if (!maintenanceOn || !savedRbdId) return undefined;
    const again = () => { if (document.visibilityState !== "hidden") setTreeTick((n) => n + 1); };
    window.addEventListener("focus", again);
    document.addEventListener("visibilitychange", again);
    return () => { window.removeEventListener("focus", again); document.removeEventListener("visibilitychange", again); };
  }, [maintenanceOn, savedRbdId]);
  const calcNodes = useMemo(() => (repairable ? applyTreePlan(nodes, treePlan) : nodes), [nodes, treePlan, repairable]);

  // Validate the current diagram against the backend (RePyability). A
  // position-independent signature lets us flag the result as stale once the
  // diagram changes.
  const sig = useMemo(
    () => graphSignature({ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }),
    [calcNodes, edges, rbdUnit, repairable, ccfGroups, costsField]
  );
  const validationStale = validation != null && sig !== checkedSig;
  const saveGraph = useMemo(
    () => ({ nodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }),
    [nodes, edges, rbdUnit, repairable, ccfGroups, costsField]
  );
  useEffect(() => {
    if (!rebaseRef.current) return;
    rebaseRef.current = false;
    setSavedSnap(rbdSaveSnapshot(saveGraph));
  }, [saveGraph]);
  // Changed since it was opened or saved: shown in full screen and in the Explorer's pane (where
  // the page's title isn't), and told to the pane, which asks before leaving unsaved changes.
  const tracked = full || embedded || !!onDirty;
  // Not changed while a diagram just loaded waits for its snapshot (the effect above).
  const rebasing = rebaseRef.current;
  const dirty = useMemo(
    () => rbdDirty({ tracked, rebasing, graph: saveGraph, savedSnap }),
    [tracked, rebasing, saveGraph, savedSnap]
  );
  useEffect(() => { onDirty?.(dirty); }, [onDirty, dirty]);
  const saveStatus = useMemo(() => {
    if (!full && !embedded) return null;
    return rbdSaveStatus({ savedId: savedRbdId, readOnly: savedRbdReadOnly, dirty });
  }, [full, embedded, dirty, savedRbdId, savedRbdReadOnly]);

  const runValidate = useCallback(async () => {
    setValidating(true);
    try {
      const v = await validateRbd({ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField });
      setValidation(v);
      setCheckedSig(graphSignature({ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }));
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
      setCheckedSig(graphSignature({ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }));
      return v;
    } finally {
      setValidating(false);
    }
  }, [calcNodes, edges, rbdUnit, repairable, ccfGroups, costsField]);

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
      if (e.metaKey || e.ctrlKey || e.altKey || !ownsKey(e)) return;
      const el = e.target;
      if (el?.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el?.tagName)) return;
      e.preventDefault();
      connectSelected();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, modal, menu, connectSelected, ownsKey]);

  // Full screen is the Builder's: another tab (the results) shows on the page.
  useEffect(() => {
    if (tab !== "builder") exitFull();
  }, [tab, exitFull]);
  // Entering or leaving full screen fits the diagram to the new size (and,
  // back on the page, sizes the canvas to it again).
  const fullSeen = useRef(full);
  useEffect(() => {
    if (fullSeen.current === full) return;
    fullSeen.current = full;
    fitWhenMeasured();
  }, [full, fitWhenMeasured]);

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
          // Cold: a duty unit with a spare that starts when it's switched in,
          // the usual standby (a hot one is plain active redundancy). The
          // chance it starts shows on the block and in its dialog.
          cold: true,
          dormancy: 0,
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
                  repair_one_at_a_time: config.repair_one_at_a_time, capacity: config.capacity,
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
      loadedRef.current = saved.id;
      setSavedSnap(rbdSaveSnapshot(graph));
      setSavedRbdId(saved.id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(saved.updated_at || null);
      setSavedRbdReadOnly(false);
      setModal(null);
      onSaved?.(saved.id);
    },
    [nodes, edges, rbdUnit, repairable, ccfGroups, costsField, savedRbdId, savedRbdUpdatedAt, onSaved]
  );

  // Save (#303): a diagram the user has named and can write saves straight
  // away; an unsaved one, or a shared sample (saved as a copy), asks for a
  // name. A failed save opens the dialog with the reason.
  const [saveError, setSaveError] = useState(null);
  const quickSave = useCallback(async () => {
    setSaveError(null);
    if (!savedRbdId || savedRbdReadOnly || !savedRbdName.trim()) {
      setTab("builder");
      setModal("saverbd");
      return;
    }
    try {
      await onSaveRbd(savedRbdName);
      setConnectHint("Saved.");
    } catch (e) {
      setSaveError(e);
      setTab("builder");
      setModal("saverbd");
    }
  }, [savedRbdId, savedRbdReadOnly, savedRbdName, onSaveRbd]);

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
      setProduction(graph?.production || null);
      setMission(missionFields(graph));
      setConditions(graph?.conditions || []);
      setSavedRbdId(id);
      setSavedRbdName(name);
      setSavedRbdUpdatedAt(updatedAt);
      setSavedRbdReadOnly(readOnly);
      rebaseRef.current = true;
      fitWhenMeasured(loadedNodes);
    },
    [setNodes, setEdges, fitWhenMeasured]
  );

  // ``model`` (a model's "Add to an RBD", #294): opened with its block added.
  const openRbd = useCallback(
    async (id, model = null) => {
      const full = await getRbd(id);
      const added = model ? graphWithModel(full.graph, model) : null;
      loadGraph(added ? added.graph : full.graph, full.id, full.name, full.updated_at || null, !!full.read_only);
      setModal(null);
      if (added) onModelAdded?.(plainName(model.name), added.wired);
    },
    [loadGraph, onModelAdded]
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
    setProduction(null);
    setMission({});
    setConditions([]);
    setSavedRbdId(null);
    setSavedRbdName("");
    setSavedRbdUpdatedAt(null);
    setSavedRbdReadOnly(false);
    rebaseRef.current = true;
    fitWhenMeasured(INITIAL_NODES);
  }, [setNodes, setEdges, fitWhenMeasured]);

  // Replace the canvas with an assistant-provided graph: normalise it (handles,
  // edge styling, non-repairable models) and lay it out left-to-right, then keep the new
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
    if (graph.production !== undefined) setProduction(graph.production || null);
    if (graph.conditions !== undefined) setConditions(graph.conditions || []);
    if (MISSION_KEYS.some((k) => graph[k] !== undefined)) setMission(missionFields(graph));
    fitWhenMeasured(norm.nodes);
  }, [setNodes, setEdges, fitWhenMeasured]);

  // Expand the sub-system blocks into their own blocks, wired as inside them (the server reads each
  // sub-system's RBD): what a repairable diagram and its Maintenance plan need. Unsaved until Save.
  const expandSubsystems = useCallback(async () => {
    const got = await expandRbdSubsystems(saveGraph);
    if (got.expanded?.length) applyGraph(got.graph);
    return got.notes || [];
  }, [saveGraph, applyGraph]);

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
  useEffect(() => {
    if (rbdId && loadedRef.current !== rbdId) {
      loadedRef.current = rbdId;
      // A diagram that isn't there (a mistyped or old link) must not look
      // like an empty, lost diagram: the page says so instead.
      openRbd(rbdId, addModel).catch((err) => onLoadError?.(err));
    } else if (!rbdId && imported?.graph && loadedRef.current !== imported) {
      loadedRef.current = imported;
      loadGraph(imported.graph, null, imported.name || "");
    } else if (!rbdId && addModel && loadedRef.current !== addModel) {
      loadedRef.current = addModel;
      loadGraph(graphWithModel(null, addModel).graph, null, "");
      onModelAdded?.(plainName(addModel.name), true);
    }
  }, [rbdId, imported, openRbd, loadGraph, addModel, onModelAdded, onLoadError]);

  // Assign a non-repairable model (saved or from parameters) to the node the modal targets.
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
  useMenuDismiss(Boolean(menu), closeMenu, menuRef);
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
      if (e.key !== "F2" || !ownsKey(e)) return;
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
  }, [tab, modal, renaming, rename, ownsKey]);

  // F toggles full screen, on the same terms as C (not while typing, nor with
  // a menu or dialog open, nor with a modifier down: Cmd/Ctrl+F still finds).
  useEffect(() => {
    if (tab !== "builder" || modal || menu || renaming) return undefined;
    const onKey = (e) => {
      if (!isFullScreenKey(e) || hasOpenLayer(document)) return;
      // In the Explorer, F from outside the builder is the Explorer's own full screen.
      if (embedded && !shellRef.current?.contains(e.target)) return;
      e.preventDefault();
      toggleFull();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tab, modal, menu, renaming, toggleFull, embedded]);

  // Delete and Backspace remove what's selected. React Flow listens on the whole document; in the
  // Explorer that would take a block off the diagram for a key pressed in the tree, so there the
  // builder listens itself, on the same terms as C.
  useEffect(() => {
    if (!embedded || tab !== "builder" || modal || menu || renaming) return undefined;
    const onKey = (e) => {
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      if (e.metaKey || e.ctrlKey || e.altKey || isTyping(e) || !ownsKey(e) || hasOpenLayer(document)) return;
      const chosenNodes = getNodes().filter((n) => n.selected);
      const chosenEdges = getEdges().filter((x) => x.selected);
      if (!chosenNodes.length && !chosenEdges.length) return;
      e.preventDefault();
      deleteElements({ nodes: chosenNodes, edges: chosenEdges });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [embedded, tab, modal, menu, renaming, ownsKey, getNodes, getEdges, deleteElements]);

  // "+ Add block" (#299): the block lands in the middle of the canvas in view,
  // a step down and right of the last one so a few in a row don't stack.
  const addOffset = useRef(0);
  const centrePos = useCallback(() => {
    const r = wrapper.current?.getBoundingClientRect();
    if (!r) return undefined;
    const step = (addOffset.current++ % 5) * 40;
    const p = screenToFlowPosition({ x: r.left + r.width / 2, y: r.top + r.height / 2 });
    return clearSpot(nodes, { x: p.x - 80 + step, y: p.y - 30 + step });
  }, [screenToFlowPosition, nodes]);

  // "+ Add block" in place (#282): with a block, a line of blocks or a
  // connection selected, the new component is wired in — after the block or
  // on the connection (in series), or alongside the block or line (in
  // parallel, merged through a junction; a network shares the connections).
  // It becomes the selection.
  const inPlace = useMemo(() => inPlaceItems(nodes, edges), [nodes, edges]);
  const addInPlace = useCallback((key) => {
    const choice = inPlaceItems(nodes, edges);
    const item = choice?.items.find((i) => i.key === key);
    if (!item || item.reason) return;
    const n = idRef.current++;
    // Alongside one block: a copy of it (model and all), the usual "another
    // of these" redundancy; anything else starts as an empty component.
    const copy = key === "alongside" ? copyForAlongside(nodes, choice.ids[0], newId(nodes.find((x) => x.id === choice.ids[0])?.type || "component")) : null;
    const block = copy ? { ...copy, ...HORIZONTAL } : {
      id: `c${n}`,
      type: "component",
      data: { label: `Component ${n}`, model: null, ...(repairable && allInstant(nodes) ? { instant_repair: true } : {}) },
      position: { x: 0, y: 0 },
      ...HORIZONTAL,
    };
    const graph = { nodes, edges };
    const out = key === "after" ? insertAfter(graph, choice.ids[0], block)
      : key === "split" ? insertOnEdge(graph, choice.edge, block)
      : insertAlongside(graph, choice.ids, block, { junctionId: newId("knode"), junctions: !network });
    setNodes(out.nodes);
    setEdges(out.edges.map((e) => (e.type ? e : { ...EDGE_OPTIONS, ...e })));
    // The canvas is as tall as the diagram: fit it again with the new block in.
    fitWhenMeasured([block]);
    const name = (id) => nodes.find((x) => x.id === id)?.data?.label || "the block";
    setConnectHint(
      key === "after" ? `Added ${block.data.label} after ${name(choice.ids[0])}, in series.`
        : key === "split" ? `Added ${block.data.label} on the line, in series.`
        : key === "alongside" ? `Added ${block.data.label}, a copy of ${name(choice.ids[0])}, alongside it in parallel. Change its model if it differs.`
        : `Added ${block.data.label} alongside the ${choice.ids.length} selected blocks, in parallel.`
    );
  }, [nodes, edges, repairable, network, newId, setNodes, setEdges, fitWhenMeasured]);

  // "+ Add block > Component": on a new diagram (only Input and Output) the
  // first block is wired Input → block → Output and selected, so "add after"
  // and "add alongside" build on a connected diagram; otherwise it lands in
  // the middle of the canvas, unwired, as before.
  const addComponentFromMenu = useCallback(() => {
    const n = idRef.current;
    const block = {
      id: `c${n}`,
      type: "component",
      data: { label: `Component ${n}`, model: null, ...(repairable && allInstant(nodes) ? { instant_repair: true } : {}) },
      position: { x: 0, y: 0 },
      ...HORIZONTAL,
    };
    const out = insertFirst({ nodes, edges }, block, EDGE_OPTIONS);
    if (!out) {
      addComponent(centrePos());
      return;
    }
    idRef.current += 1;
    setNodes(out.nodes);
    setEdges(out.edges);
    fitWhenMeasured([block]);
    setConnectHint(`Added ${block.data.label} between Input and Output, in series.`);
  }, [nodes, edges, repairable, addComponent, centrePos, setNodes, setEdges, fitWhenMeasured]);

  // The toolbar's Safety function switch (#298): on, the diagram is a
  // repairable safety function (its results lead with PFDavg and the SIL);
  // off, it isn't, and its target SIL goes with it.
  const setSafety = useCallback((on) => {
    setPolicies((p) => policyFields({ ...p, safety_function: on || null, target_sil: on ? p.target_sil : null }));
    if (on) {
      setRepairable(true);
      // A safety function is a block diagram, never a network (#160).
      setMission(({ network: _n, ...rest }) => rest);
    }
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
  // The Maintenance plan: open it (on one block, from its dialog), edit a block's data in it, and
  // fit the diagram again once the canvas has given the plan its room.
  const refitSoon = useCallback(() => {
    window.setTimeout(() => fitView(fitOptionsFor(wrapper.current?.clientWidth || window.innerWidth, embedded)), 80);
  }, [fitView, embedded]);
  const togglePlan = useCallback((on) => {
    setPlanOpen((was) => (typeof on === "boolean" ? on : !was));
    refitSoon();
  }, [refitSoon]);
  const openPlanFor = useCallback((id) => {
    setNodes((nds) => nds.map((n) => (n.selected === (n.id === id) ? n : { ...n, selected: n.id === id })));
    togglePlan(true);
  }, [setNodes, togglePlan]);
  const setPlanNode = useCallback((id, data) => {
    setNodes((nds) => nds.map((n) => (n.id === id ? { ...n, data } : n)));
  }, [setNodes]);
  const clearSelection = useCallback(() => {
    setNodes((nds) => nds.map((n) => (n.selected ? { ...n, selected: false } : n)));
  }, [setNodes]);
  // A network's connections are drawn without arrows (#160).
  const flowEdges = useMemo(() => (network ? undirectedEdges(edges) : edges), [network, edges]);

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
    <div className="rbd-shell" ref={shellRef}>
    <Tabs tabs={RBD_TABS} value={tab} onChange={setTab} label="Diagram views" className="rbd-tabs" />
    <div
      ref={builderRef}
      className={"rbd-builder" + (full ? " is-full" : "") + (planOpen && repairable ? " has-plan" : "") + builderWidthClass(builderW)}
      style={{ display: tab === "builder" ? undefined : "none" }}
      role={full ? "region" : undefined}
      aria-label={full ? "Diagram editor, full screen" : undefined}
    >
    {/* One row above the canvas (#314): the diagram's settings on the left;
        Validate, Save ▾ and ⋯ on the right. On a phone the settings move into ⋯. */}
    <div className="rbd-toolbar">
      {/* Add a block without right-clicking (#299); on a phone the only way. */}
      <ToolbarMenu label={<span>+ Add<span className="rbd-add-word"> block</span></span>} title="Add a block: wired in after or alongside what's selected, or in the middle of the canvas"
                   aria="Add block" className="rbd-add-menu" wt="rbd-add">
        {/* In place first, when something is selected (#282); then anywhere. */}
        {inPlace && (
          <>
            {inPlace.items.map((i) => (
              <button key={i.key} className="ovm-item" disabled={!!i.reason} title={i.reason || undefined}
                      onClick={() => addInPlace(i.key)}>
                {i.label}
              </button>
            ))}
            <div className="rbd-menu-sep" role="separator" />
          </>
        )}
        <button className="ovm-item" onClick={addComponentFromMenu}>Component</button>
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
          value={repairable ? "repairable" : network ? "network" : "non"}
          onChange={setMode}
          title="Repairable diagrams analyse availability (uptime) — every component also needs a repair-time distribution. Non-repairable diagrams analyse reliability over time. A network's connections work both ways: it analyses whether two points stay connected."
          options={[
            { value: "non", label: "Non-repairable" },
            { value: "repairable", label: "Repairable" },
            { value: "network", label: "Network" },
          ]}
        />
        {/* A safety function (#298): on, the results lead with PFDavg and the SIL. A network isn't one. */}
        {!network && (
        <Switch
          className="rbd-safety-switch"
          checked={repairable && !!policies.safety_function}
          onChange={setSafety}
          label="Safety function"
          title="A safety instrumented function (IEC 61511): its results lead with PFDavg and the SIL band. Turning it on makes the diagram repairable."
        />
        )}
        {repairable && policies.safety_function && (
          <Chip onClick={() => setModal("safety")} title="The SIL this function must meet. Click to change it.">
            {policies.target_sil ? `Target SIL ${policies.target_sil}` : "Set a target SIL"}
          </Chip>
        )}
        {repairable && (
          <Chip tone={planOpen ? "accent" : "neutral"} onClick={() => togglePlan()} aria-pressed={planOpen}
                title="Every block's planned work and duty in one table, under the diagram" data-wt="rbd-plan-chip">
            Maintenance plan
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
      <div className="rbd-tb-flash" role="status" title={connectHint || undefined}>{connectHint}</div>
      <div className="rbd-toolbar-actions">
        {/* Full screen hides the page's title: the diagram's name and whether
            it's saved stay in sight here. */}
        {saveStatus && (
          <span className={`rbd-full-status is-${saveStatus.tone}`} title={saveStatus.title} role="status">
            <span className="rbd-full-name">{(savedRbdName || "").replace(SAMPLE_SUFFIX, "") || "Untitled RBD"}</span>
            <span className="rbd-full-dot" aria-hidden="true" />
            <span className="rbd-full-saved">{saveStatus.text}</span>
          </span>
        )}
        <ValidationStatus
          validation={validation}
          stale={validationStale}
          validating={validating}
          onValidate={runValidate}
        />
        <ToolbarMenu label="Save" title="Save, or download the saved diagram">
          <button className="ovm-item" onClick={quickSave}>
            {savedRbdId && !savedRbdReadOnly && savedRbdName.trim() ? "Save" : "Save…"}
          </button>
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
              <select value={repairable ? "repairable" : network ? "network" : "non"} onChange={(e) => setMode(e.target.value)}>
                <option value="non">Non-repairable</option>
                <option value="repairable">Repairable</option>
                <option value="network">Network</option>
              </select>
            </label>
          </div>
          <button className="ovm-item" onClick={autoLayout}>Auto-arrange</button>
          {!repairable && !network && (
            <button
              className="ovm-item"
              onClick={() => setModal("phases")}
              title="A mission through phases (take-off, cruise, landing), each with its own duration and the blocks it needs"
            >
              Phased mission…{mission.phases?.length ? " ✓" : ""}
            </button>
          )}
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
            <button className="ovm-item" role="menuitemcheckbox" aria-checked={planOpen} onClick={() => togglePlan()}
                    title="Every block's planned work and duty in one table, under the diagram">
              Maintenance plan{planOpen ? " ✓" : ""}
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
          {pane?.fullPath && (
            <Link className="ovm-item" to={pane.fullPath} onClick={(e) => pane.onOpenFull?.(e, pane.fullPath)}>Open full page</Link>
          )}
        </ToolbarMenu>
        {pane?.onClose && (
          <button type="button" className="ghost sm rw-x rbd-pane-x" onClick={pane.onClose}
                  aria-label={pane.closeLabel || "Close"} title="Back to the table (Esc)"><CloseIcon /></button>
        )}
      </div>
      {/* In full screen, Exit is the toolbar's last button, always on show.
          (The way in is on the canvas's corner: the toolbar is full.) */}
      {full && <FullScreenButton ref={fullBtnRef} full onClick={toggleFull} />}
    </div>
    <div
      className={"rbd-canvas" + (canvasH && !full && !(planOpen && repairable) ? " is-sized" : "")}
      data-wt="rbd-canvas"
      ref={wrapper}
      style={canvasH && !full && !(planOpen && repairable) ? { height: canvasH } : undefined}
    >
      <ReactFlow
        nodes={nodes}
        edges={flowEdges}
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
        onMoveStart={(e) => {
          if (e) movedRef.current = true; // a drag, wheel or pinch (a fit has no event)
          closeMenu();
        }}
        deleteKeyCode={embedded ? null : ["Backspace", "Delete"]}
        // Shift-click adds to the selection (as the hints/guides say), alongside
        // the platform Cmd/Ctrl. Shift-drag still box-selects.
        multiSelectionKeyCode={["Meta", "Control", "Shift"]}
        defaultEdgeOptions={EDGE_OPTIONS}
        fitView
        fitViewOptions={fitOptionsFor(typeof window !== "undefined" ? window.innerWidth : 0, embedded)}
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
        {!full && (
          <Panel position="top-right" className="rbd-full-panel">
            <FullScreenButton ref={fullBtnRef} full={false} onClick={toggleFull} compact />
          </Panel>
        )}
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
              {!network && (
                <>
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
                </>
              )}
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
                {treePlan?.blocks?.[originalId(nodes, menu.id)] && (() => {
                  const pos = treePlan.blocks[originalId(nodes, menu.id)].position;
                  const path = treePositionPath(pos.id, repairable ? "maintenance" : "models");
                  return (
                    <>
                      <Link className="rbd-menu-link" to={path} title={`${pos.name}, in the Explorer`}
                            onClick={(e) => { closeMenu(); pane?.onOpenFull?.(e, path); }}>
                        Open in the tree
                      </Link>
                      <div className="rbd-menu-sep" />
                    </>
                  );
                })()}
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
                      {menu.repeat ? "Edit non-repairable model (original)" : "Edit non-repairable model"}
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
                {menu.nodeType === "component" && !repairable && !network && (
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

      {/* One short line until the first connection (#314). What an action
          did flashes in the toolbar, off the canvas, so it never covers the
          blocks it talks about. */}
      {edges.length === 0 && (
        <div className="rbd-hint">
          Add blocks with + Add block or a right-click · select a block or a line first to wire it in · drag to connect · double-click to edit
        </div>
      )}

      {modal === "lifemodel" && (
        <LifeModelModal
          initial={nodes.find((n) => n.id === modalNodeId)?.data}
          repairable={repairable}
          crews={!!policies.repair_crews}
          groups={groupNames}
          safety={repairable && !!policies.safety_function}
          capacity={nodes.find((n) => n.id === modalNodeId)?.type === "component"}
          jointBlock={nodes.find((n) => n.id === modalNodeId)?.type === "component"}
          conditions={conditions}
          nodeId={modalNodeId}
          onClose={() => {
            setModal(null);
            setModalNodeId(null);
          }}
          onSubmit={setNodeModel}
          tree={repairable ? treeRow(treePlan, modalNodeId) : null}
          onTreeLink={pane?.onOpenFull || null}
          onEditPlan={repairable && nodes.find((n) => n.id === modalNodeId)?.type === "component"
            ? (payload) => { const id = modalNodeId; setNodeModel(payload); openPlanFor(id); }
            : null}
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
      {modal === "phases" && (
        <RbdPhasesModal
          initial={mission.phases}
          nodes={nodes}
          edges={edges}
          unit={rbdUnit}
          onClose={() => setModal(null)}
          onSubmit={(phases) => {
            setMission((m) => {
              const { phases: _p, ...rest } = m;
              return phases ? { ...rest, phases } : rest;
            });
            setModal(null);
          }}
        />
      )}
      {modal === "saverbd" && (
        <RbdSaveModal
          initialName={savedRbdName}
          initialError={saveError}
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
    {planOpen && repairable && (
      <RbdMaintenancePlan
        nodes={nodes}
        unit={rbdUnit}
        crews={!!policies.repair_crews}
        groupNames={groupNames}
        selected={selectedComponentIds}
        onChange={setPlanNode}
        onShowAll={clearSelection}
        onCrewsAndGroups={() => setModal("crews")}
        onClose={() => togglePlan(false)}
        tree={treePlan}
        onTreeLink={pane?.onOpenFull || null}
        onExpand={expandSubsystems}
      />
    )}
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "calc" ? undefined : "none" }}
    >
      {network ? (
        <RbdNetworkPanel
          graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
          active={tab === "calc"}
          name={savedRbdName}
          onNetworkChange={(n) => setMission((m) => ({ ...m, network: n }))}
          onBuild={toBuilder}
        />
      ) : (
      <RbdCalculator
        graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        validation={validation}
        stale={validationStale}
        onValidate={runValidate}
        rbdId={savedRbdId}
        name={savedRbdName}
        onBuild={toBuilder}
        onProduction={setProduction}
        onNodeData={(updates) =>
          // #52: covariate schedules set in the calculator, put on their blocks (unsaved); and the
          // values of covariates left open at the blocks' positions (null takes one off).
          setNodes((nds) => nds.map((n) => (updates[n.id] ? { ...n, data: applyBlockExtras(n.data, updates[n.id]) } : n)))
        }
        onConditions={setConditions}
      />
      )}
      <RbdPhasesResult
        graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        active={tab === "calc"}
        name={savedRbdName}
        onEdit={savedRbdReadOnly ? null : () => setModal("phases")}
      />
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "tree" ? undefined : "none" }}
    >
      {network ? <NetworkOnlyNote what="A fault tree" onCalc={() => setTab("calc")} /> : (
      <RbdFaultTree
        graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        validation={validation}
        stale={validationStale}
        active={tab === "tree"}
        name={savedRbdName}
        onBuild={toBuilder}
      />
      )}
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "design" ? undefined : "none" }}
    >
      {network ? <NetworkOnlyNote what="Redundancy design" onCalc={() => setTab("calc")} /> : (
      <RbdDesignPanel
        graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        onApply={applyDesign}
        onBuild={toBuilder}
        readOnly={savedRbdReadOnly}
        onSaveCopy={savedRbdId ? () => saveFromTab("saveasnew") : null}
        onView={() => {
          setTab("builder");
          // Once the canvas is shown again (it can't be fitted while hidden).
          window.setTimeout(() => fitView(fitOptionsFor(wrapper.current?.clientWidth || window.innerWidth, embedded)), 60);
        }}
      />
      )}
    </div>
    <div
      className="rbd-calc-panel"
      style={{ display: tab === "targets" ? undefined : "none" }}
    >
      {network ? <NetworkOnlyNote what="Target allocation" onCalc={() => setTab("calc")} /> : (
      <RbdTargets
        graph={{ nodes: calcNodes, edges, unit: rbdUnit, repairable, ccf_groups: ccfGroups, ...costsField }}
        onBuild={toBuilder}
      />
      )}
    </div>
    {tab === "outages" && (
      <div className="rbd-calc-panel">
        <Suspense fallback={<p className="muted-line">Loading…</p>}>
          <OutageHistory
            rbdId={savedRbdId}
            graph={{ nodes, edges, unit: rbdUnit }}
            readOnly={savedRbdReadOnly}
            onBuild={toBuilder}
            onSave={quickSave}
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


// The RBD editor: the builder's tabs (Builder, Calculator, Fault tree, Design, Targets, Outage
// history) for the diagram `rbdId` (none: a new one, or `imported`, unsaved). The RBD page
// (views/RbdBuilder.jsx) and the Explorer's table area (RbdPane.jsx) both show this one
// component, so a change here is a change to both (Derryn, 9 Nov 2026).
//
//   embedded   in the Explorer's table area: it fills the pane, takes keys only from inside
//              itself, shows the diagram's name and whether it's saved in its toolbar, and leaves
//              the address's ?tab= alone
//   onSaved(id)      saved (a new id after Save as new, or a first save)
//   onMeta({id, name, readOnly})   onTab(tab)   onDirty(changed since opened or saved)
//   onLoadError(err) the diagram couldn't be opened (not there, not yours, offline)
//   addModel, onModelAdded   a model's "Add to an RBD" (#294), on the page
export default function RbdEditor({ embedded = false, ...props }) {
  return (
    <div className={embedded ? "rbd-wrap rbd-wrap-embedded" : "card rbd-wrap"}>
      <ReactFlowProvider>
        <Builder embedded={embedded} {...props} />
      </ReactFlowProvider>
    </div>
  );
}
