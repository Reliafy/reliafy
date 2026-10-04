import { useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  BaseEdge,
  Background,
  Controls,
  Handle,
  Position,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import { rbdFaultTree } from "../api.js";
import ValidationPanel, { graphSignature } from "./RbdValidation.jsx";
import "./RbdFaultTree.css";

// The RBD builder's "Fault tree" tab (#101): a read-only view of the diagram's
// failure logic. The server converts the diagram with RePyability's
// FaultTree.from_rbd — a series block is an OR gate, a parallel block an AND
// gate, a k-of-n block a VOTE gate — and evaluates the top event (the system
// failing) at a time t, with the ranked minimal cut sets and each basic
// event's importance. Drawn top-down on its own React Flow canvas; deep or
// wide trees start collapsed and expand gate by gate.

const NODE_W = 184;
const GAP_X = 22;
const LEVEL_H = 158;
// Nodes shown before the rest of the tree starts collapsed.
const INITIAL_BUDGET = 48;
// A gate with more inputs than this shows its likeliest few, then "+N more".
const WIDE = 8;
const WIDE_SHOWN = 6;
// The tree is framed no smaller than this: a wide tree is panned, not shrunk
// to specks.
const MIN_FRAME_ZOOM = 0.7;
// Rows shown in the tables before "Show all".
const TABLE_ROWS = 15;

const fmtP = (v) =>
  v == null || !Number.isFinite(v)
    ? "—"
    : v === 0 || v === 1
    ? String(v)
    : v >= 1e-3
    ? Number(v.toPrecision(4)).toString()
    : v.toExponential(2);
const fmtX = (v) =>
  v == null || !Number.isFinite(v) ? "—" : Math.abs(v) >= 1e-3 || v === 0 ? Number(v.toPrecision(3)).toString() : v.toExponential(2);
const fmtPct = (v) =>
  v == null || !Number.isFinite(v) ? "—" : v >= 0.001 ? `${(v * 100).toFixed(1)}%` : "<0.1%";
const fullLabel = (e) => [...(e.path || []), e.label].join(" › ");

// Gate symbols, output at the top and inputs along the bottom.
function GateSymbol({ kind, k, n }) {
  return (
    <svg className={`ft-symbol ft-symbol-${kind}`} width="46" height="36" viewBox="0 0 46 36" aria-hidden="true">
      {kind === "and" ? (
        <path d="M5 34 L5 18 A18 16 0 0 1 41 18 L41 34 Z" />
      ) : (
        <path d="M5 34 Q23 24 41 34 Q40 13 23 2 Q6 13 5 34 Z" />
      )}
      {kind === "vote" && (
        <text x="23" y="26" textAnchor="middle">{`${k}/${n}`}</text>
      )}
    </svg>
  );
}

const KIND_NAMES = { or: "OR", and: "AND", vote: "VOTE" };

function GateNode({ data }) {
  const { gate, title, sub, collapsed, hidden } = data;
  return (
    <div className={"ft-gate" + (collapsed ? " collapsed" : "")} title={data.tip}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className={"ft-box" + (gate.role === "top" ? " ft-box-top" : "")}>
        <div className="ft-box-title">{title}</div>
        {sub && <div className="ft-box-sub">{sub}</div>}
        <div className="ft-box-meta">
          <span className="ft-code">{gate.id}</span>
          <span className="ft-p">P = {fmtP(gate.probability)}</span>
        </div>
        {gate.repeated && <span className="ft-tag">repeated</span>}
      </div>
      <div className="ft-stem" />
      <GateSymbol kind={gate.kind} k={gate.k} n={gate.inputs.length} />
      {collapsed && <div className="ft-more-below">+{hidden} below</div>}
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  );
}

function EventNode({ data }) {
  const { event } = data;
  const ccf = event.node_type === "ccf";
  return (
    <div className={"ft-event" + (event.pinned ? " pinned" : "")} title={data.tip}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className={"ft-box" + (ccf ? " ft-box-ccf" : "")}>
        <div className="ft-box-title">{event.label}</div>
        <div className="ft-box-meta">
          <span className="ft-p">P = {fmtP(event.probability)}</span>
        </div>
        {event.pinned && <span className="ft-tag ft-tag-pin">pinned {event.pinned}</span>}
        {!event.pinned && event.repeated && <span className="ft-tag">{ccf ? "shared" : "repeated"}</span>}
      </div>
      <div className="ft-stem" />
      <span className={"ft-circle" + (ccf ? " ft-circle-ccf" : "")}>{ccf ? "CC" : ""}</span>
    </div>
  );
}

function MoreNode({ data }) {
  return (
    <div className="ft-more-node" title="Show every input of this gate">
      <Handle type="target" position={Position.Top} isConnectable={false} />
      +{data.count} more
    </div>
  );
}

const NODE_TYPES = { gate: GateNode, event: EventNode, more: MoreNode };

// A gate's inputs hang off one horizontal bus just above them, so siblings
// share a single rail (React Flow's step edges bend at each pair's midpoint).
function BusEdge({ id, sourceX, sourceY, targetX, targetY }) {
  const bus = targetY - 18;
  return <BaseEdge id={id} path={`M${sourceX},${sourceY} L${sourceX},${bus} L${targetX},${bus} L${targetX},${targetY}`} />;
}

const EDGE_TYPES = { bus: BusEdge };

// What a gate means, in words: its own name for the top event, a sub-system
// or a common-cause member; otherwise read off its inputs.
function gateText(gate, events, gates, name) {
  const n = gate.inputs.length;
  if (gate.role === "top") {
    return { title: name ? `${name} fails` : "System fails", sub: "Top event" };
  }
  if (gate.role === "subsystem") return { title: `${gate.label} fails`, sub: "Sub-system" };
  if (gate.role === "ccf_member") {
    return { title: `${gate.label} fails`, sub: `Independently or by common cause (β = ${gate.beta})` };
  }
  const names = gate.inputs.map((i) => (i.kind === "event" ? events[i.id]?.label : null));
  if (n === 2 && names.every(Boolean)) {
    return gate.kind === "or"
      ? { title: `${names[0]} or ${names[1]} fails`, sub: null }
      : { title: `${names[0]} and ${names[1]} fail`, sub: null };
  }
  if (gate.kind === "or") return { title: `Any of ${n} inputs fails`, sub: null };
  if (gate.kind === "and") return { title: `All ${n} inputs fail`, sub: null };
  return { title: `${gate.k} of ${n} inputs fail`, sub: null };
}

// The drawn tree: gates expand in place (a repeated gate or event is drawn at
// each use), so node keys are paths from the top.
function buildTree(result, collapsed, showAll) {
  const gates = Object.fromEntries(result.gates.map((g) => [g.id, g]));
  const events = Object.fromEntries(result.events.map((e) => [e.id, e]));
  const prob = (i) => (i.kind === "gate" ? gates[i.id]?.probability : events[i.id]?.probability) ?? 0;
  const countBelow = (id, seen = new Set()) => {
    // Distinct gates + events below a gate (for the "+N below" badge).
    for (const i of gates[id].inputs) {
      const key = `${i.kind}:${i.id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      if (i.kind === "gate") countBelow(i.id, seen);
    }
    return seen.size;
  };
  const build = (input, key) => {
    if (input.kind === "event") return { key, kind: "event", event: events[input.id], children: [] };
    const gate = gates[input.id];
    const node = { key, kind: "gate", gate, children: [], collapsed: collapsed.has(key) };
    if (node.collapsed) {
      node.hidden = countBelow(gate.id);
      return node;
    }
    let inputs = gate.inputs;
    let more = 0;
    if (inputs.length > WIDE && !showAll.has(key)) {
      inputs = [...inputs].sort((a, b) => prob(b) - prob(a)).slice(0, WIDE_SHOWN);
      more = gate.inputs.length - inputs.length;
    }
    node.children = inputs.map((i) => build(i, `${key}/${i.kind}:${i.id}`));
    if (more) node.children.push({ key: `${key}/+more`, kind: "more", count: more, gateKey: key, children: [] });
    return node;
  };
  return { root: build({ kind: "gate", id: result.top }, "TOP"), gates, events };
}

// A tidy layered layout: each subtree gets the width of its leaves, and a
// parent sits centred over its children.
function layout(root) {
  const width = (n) => {
    n.w = n.children.length
      ? Math.max(NODE_W, n.children.reduce((s, c) => s + width(c), 0) + GAP_X * (n.children.length - 1))
      : NODE_W;
    return n.w;
  };
  width(root);
  const placed = [];
  const place = (n, x0, depth) => {
    placed.push({ n, x: x0 + n.w / 2 - NODE_W / 2, y: depth * LEVEL_H });
    const total = n.children.reduce((s, c) => s + c.w, 0) + GAP_X * Math.max(n.children.length - 1, 0);
    let x = x0 + (n.w - total) / 2;
    for (const c of n.children) {
      place(c, x, depth + 1);
      x += c.w + GAP_X;
    }
  };
  place(root, 0, 0);
  return placed;
}

// Start with as much of the tree as fits a readable budget, breadth first;
// the gates beyond it start collapsed.
function initialCollapsed(result) {
  const gates = Object.fromEntries(result.gates.map((g) => [g.id, g]));
  const collapsed = new Set();
  let shown = 1;
  const queue = [{ id: result.top, key: "TOP" }];
  while (queue.length) {
    const { id, key } = queue.shift();
    const inputs = gates[id].inputs;
    const n = Math.min(inputs.length, inputs.length > WIDE ? WIDE_SHOWN + 1 : inputs.length);
    if (key !== "TOP" && shown + n > INITIAL_BUDGET) {
      collapsed.add(key);
      continue;
    }
    shown += n;
    for (const i of inputs) {
      if (i.kind === "gate") queue.push({ id: i.id, key: `${key}/gate:${i.id}` });
    }
  }
  return collapsed;
}

function allGateKeys(result) {
  const gates = Object.fromEntries(result.gates.map((g) => [g.id, g]));
  const keys = [];
  const walk = (id, key) => {
    keys.push(key);
    if (keys.length > 5000) return; // a pathological tree: stop listing
    for (const i of gates[id].inputs) if (i.kind === "gate") walk(i.id, `${key}/gate:${i.id}`);
  };
  walk(result.top, "TOP");
  return keys;
}

function TreeCanvas({ result, name, active }) {
  const [collapsed, setCollapsed] = useState(() => initialCollapsed(result));
  const [showAll, setShowAll] = useState(() => new Set());
  const [ready, setReady] = useState(false);
  const [frameRequest, setFrameRequest] = useState(1);
  const framed = useRef(0);
  const box = useRef(null);
  const { setViewport } = useReactFlow();

  const { nodes, edges } = useMemo(() => {
    const { root, gates, events } = buildTree(result, collapsed, showAll);
    const nodes = [];
    const edges = [];
    for (const { n, x, y } of layout(root)) {
      if (n.kind === "gate") {
        const { title, sub } = gateText(n.gate, events, gates, name);
        nodes.push({
          id: n.key, type: "gate", position: { x, y },
          data: {
            gate: n.gate, title, sub, collapsed: n.collapsed, hidden: n.hidden,
            tip: `${KIND_NAMES[n.gate.kind]} gate ${n.gate.id} — click to ${n.collapsed ? "expand" : "collapse"}`,
          },
        });
      } else if (n.kind === "event") {
        const imp = n.event.importance || {};
        nodes.push({
          id: n.key, type: "event", position: { x, y },
          data: {
            event: n.event,
            tip: `${fullLabel(n.event)}\nP = ${fmtP(n.event.probability)} · criticality ${fmtPct(imp.criticality)} · Birnbaum ${fmtX(imp.birnbaum)}`,
          },
        });
      } else {
        nodes.push({ id: n.key, type: "more", position: { x, y }, data: { count: n.count, gateKey: n.gateKey } });
      }
      for (const c of n.children) {
        edges.push({ id: `${n.key}->${c.key}`, source: n.key, target: c.key, type: "bus", className: "ft-edge" });
      }
    }
    return { nodes, edges };
  }, [result, collapsed, showAll, name]);

  // Frame the tree with the top event at the top: the whole tree when it fits
  // at a readable zoom, else centred on the top event (pan to see the rest).
  useEffect(() => {
    const el = box.current;
    if (!ready || !active || framed.current === frameRequest || !el?.clientWidth) return;
    const W = el.clientWidth;
    const H = el.clientHeight;
    let minX = Infinity;
    let maxX = -Infinity;
    let maxY = 0;
    for (const n of nodes) {
      minX = Math.min(minX, n.position.x);
      maxX = Math.max(maxX, n.position.x + NODE_W);
      maxY = Math.max(maxY, n.position.y + 130);
    }
    const fit = Math.min(W / (maxX - minX + 60), H / (maxY + 60));
    const zoom = Math.min(1, Math.max(MIN_FRAME_ZOOM, fit));
    const top = nodes.find((n) => n.id === "TOP");
    const cx = fit >= MIN_FRAME_ZOOM ? (minX + maxX) / 2 : top.position.x + NODE_W / 2;
    setViewport({ x: W / 2 - cx * zoom, y: 24, zoom });
    framed.current = frameRequest;
  }, [ready, active, frameRequest, nodes, setViewport]);

  const onNodeClick = (_, node) => {
    if (node.type === "gate" && node.id !== "TOP") {
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(node.id)) next.delete(node.id);
        else next.add(node.id);
        return next;
      });
    } else if (node.type === "more") {
      setShowAll((prev) => new Set(prev).add(node.data.gateKey));
    }
  };

  return (
    <div className="ft-canvas-wrap">
      <div className="ft-canvas-tools">
        <button
          className="rbd-btn"
          onClick={() => {
            setCollapsed(new Set());
            setFrameRequest((r) => r + 1);
          }}
          title="Expand every gate"
        >
          Expand all
        </button>
        <button
          className="rbd-btn"
          onClick={() => {
            setCollapsed(new Set(allGateKeys(result).filter((k) => k !== "TOP")));
            setFrameRequest((r) => r + 1);
          }}
          title="Show only the top event's inputs"
        >
          Collapse all
        </button>
        <span className="hint">Click a gate to expand or collapse it. Drag to pan, scroll to zoom.</span>
      </div>
      <div className="ft-canvas" ref={box}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          edgeTypes={EDGE_TYPES}
          onNodeClick={onNodeClick}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnDoubleClick={false}
          onInit={() => setReady(true)}
          minZoom={0.1}
          maxZoom={1.5}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={22} color="#e8e7e2" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
    </div>
  );
}

function CutSetTable({ result }) {
  const [all, setAll] = useState(false);
  const cuts = result.cut_sets;
  const events = useMemo(() => Object.fromEntries(result.events.map((e) => [e.id, e])), [result.events]);
  const rows = all ? cuts.listed : cuts.listed.slice(0, TABLE_ROWS);
  const count = cuts.count;
  const heading =
    cuts.basis === "all"
      ? `${count.toLocaleString()} minimal cut set${count === 1 ? "" : "s"}, most likely first`
      : cuts.basis === "most_likely"
      ? `The ${cuts.listed.length} most likely of ${count?.toLocaleString() ?? "many"} minimal cut sets`
      : `Minimal cut sets of up to ${cuts.max_order} events (${count?.toLocaleString() ?? "too many"} in all — too many to list)`;
  return (
    <div className="ft-section">
      <div className="rbd-section-head">Ranked cut sets — {heading}</div>
      {cuts.listed.length === 0 ? (
        <p className="muted-line">No cut sets of up to {cuts.max_order} events.</p>
      ) : (
        <div className="ft-table-scroll">
          <table className="calc-table ft-table ft-cuts">
            <thead>
              <tr>
                <th>#</th>
                <th>Cut set — these fail together</th>
                <th title="Number of basic events in the cut set">Order</th>
                <th title="Probability that every event in the cut set has occurred">Probability</th>
                <th title="The cut set's probability as a share of the top event probability">Share of top event</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c, i) => (
                <tr key={i}>
                  <td className="ft-rank">{i + 1}</td>
                  <td className="ft-cut">
                    {c.events.map((id, j) => (
                      <span key={id}>
                        {j > 0 && <span className="ft-and"> + </span>}
                        {events[id]?.node_type === "ccf" && <span className="ft-cc-badge" title="A common-cause group's shared cause">CC</span>}
                        {fullLabel(events[id] || { label: id })}
                      </span>
                    ))}
                  </td>
                  <td>{c.order}</td>
                  <td>{fmtP(c.probability)}</td>
                  <td>
                    <span className="ft-share">
                      <span className="ft-share-bar">
                        <span style={{ width: `${Math.min(100, (c.share || 0) * 100)}%` }} />
                      </span>
                      {fmtPct(c.share)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cuts.listed.length > TABLE_ROWS && (
        <button className="link-btn ft-show-all" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${cuts.listed.length}`}
        </button>
      )}
      <p className="muted-line ft-note">
        A cut set's probability is the product of its events' — shares can add to more than 100%
        because cut sets overlap.
        {cuts.basis === "all" && ` Their sum (${fmtP(cuts.probability_sum)}) is the rare-event approximation of the exact top event probability.`}
      </p>
    </div>
  );
}

// Each common-cause group's shared cause (#229): what it fails, how likely it
// is, and the share of the top event its cut sets carry.
function CommonCause({ result }) {
  const groups = result.common_cause || [];
  if (!groups.length) return null;
  return (
    <div className="ft-section ft-ccf">
      <div className="rbd-section-head">Common cause</div>
      <ul className="ft-ccf-list">
        {groups.map((g) => (
          <li key={g.event}>
            <span className="ft-cc-badge">CC</span>
            <span>
              <b>{g.members.join(", ")}</b>
              {g.path?.length ? <span className="muted"> (in {g.path.join(" › ")})</span> : null} fail together by
              their shared cause with P = {fmtP(g.probability)} (β = {g.beta}, {g.basis} basis). Cut sets holding it
              carry <b>{fmtPct(g.share)}</b> of the top event.
            </span>
          </li>
        ))}
      </ul>
      <p className="muted-line ft-note">
        Each member fails on its own or by its group's shared cause, drawn as one event (CC) under every member, so the
        shared cause alone is a cut set, as PRA codes list it.
      </p>
    </div>
  );
}

const IMP_COLS = [
  { key: "criticality", label: "Criticality", fmt: fmtPct,
    help: "Share of the top event this event accounts for: Birnbaum × P(event) ÷ P(top)." },
  { key: "birnbaum", label: "Birnbaum", fmt: fmtX,
    help: "How much the top event probability rises per unit rise in this event's probability." },
  { key: "fussell_vesely", label: "F-V", fmt: fmtX,
    help: "Fussell–Vesely: the share of the top event carried by the cut sets containing this event." },
  { key: "risk_achievement_worth", label: "RAW", fmt: fmtX,
    help: "Risk achievement worth: how many times likelier the top event is once this event has occurred." },
  { key: "risk_reduction_worth", label: "RRW", fmt: fmtX,
    help: "Risk reduction worth: the factor by which the top event would be less likely if this event could not occur." },
];

function ImportanceTable({ result }) {
  const [all, setAll] = useState(false);
  const sorted = useMemo(
    () => [...result.events].sort(
      (a, b) => (b.importance?.criticality ?? -1) - (a.importance?.criticality ?? -1)
    ),
    [result.events]
  );
  const rows = all ? sorted : sorted.slice(0, TABLE_ROWS);
  const fvPartial = result.cut_sets.basis === "low_order";
  return (
    <div className="ft-section">
      <div className="rbd-section-head">Basic events — importance to the top event</div>
      <div className="ft-table-scroll">
        <table className="calc-table ft-table">
          <thead>
            <tr>
              <th>Basic event</th>
              <th title="Probability that the event has occurred">P(event)</th>
              {IMP_COLS.map((c) => (
                <th key={c.key} title={c.help + (c.key === "fussell_vesely" && fvPartial ? " (from the cut sets listed above; there are too many to use them all)" : "")}>
                  {c.label}{c.key === "fussell_vesely" && fvPartial ? "*" : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td className="calc-row-label">
                  {fullLabel(e)}
                  {e.pinned && <span className="rbd-avail-pin">pinned {e.pinned}</span>}
                </td>
                <td>{fmtP(e.probability)}</td>
                {IMP_COLS.map((c) => (
                  <td key={c.key}>{c.fmt(e.importance?.[c.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sorted.length > TABLE_ROWS && (
        <button className="link-btn ft-show-all" onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${sorted.length}`}
        </button>
      )}
    </div>
  );
}

export default function RbdFaultTree({ graph, validation, stale, active, name }) {
  const [result, setResult] = useState(null);
  const [phase, setPhase] = useState("idle"); // idle | loading | error
  const [error, setError] = useState(null);
  const [tInput, setTInput] = useState(""); // blank = the calculator's importance time
  const [fetchedSig, setFetchedSig] = useState(null);

  // The tree needs no separate validate step (the server explains what it
  // can't convert) — only a current check that failed holds it back.
  const blocked = !!validation && !stale && !validation.can_calculate;
  const canCalculate = !blocked;
  const unit = graph.unit || "";
  const u = unit ? ` ${unit}` : "";
  const sig = useMemo(
    () => graphSignature(graph) + JSON.stringify([graph.repairable, graph.ccf_groups]),
    [graph]
  );

  const load = async (t) => {
    setPhase("loading");
    setError(null);
    try {
      const res = await rbdFaultTree(graph, t === "" || t == null ? null : Number(t));
      setResult(res);
      setFetchedSig(sig);
      setPhase("idle");
    } catch (err) {
      setError(err.message);
      setResult(null);
      setFetchedSig(sig);
      setPhase("error");
    }
  };

  // Build the tree when the tab is shown and the diagram has changed since.
  useEffect(() => {
    if (active && canCalculate && fetchedSig !== sig && phase !== "loading") load(tInput);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, canCalculate, sig, phase]);

  const availability = result?.kind === "availability";
  const tDirty = result && !availability && tInput !== "" && Number(tInput) !== result.t;

  return (
    <div className="rbd-fault-tree">
      {blocked && <ValidationPanel validation={validation} stale={false} />}

      {canCalculate && (
        <div className="ft-head">
          {!graph.repairable && (
            <form
              className="ft-controls"
              onSubmit={(e) => {
                e.preventDefault();
                load(tInput);
              }}
            >
              <label className="calc-t">
                <span>Evaluate at t{unit ? ` (${unit})` : ""}</span>
                <input
                  type="number"
                  min="0"
                  step="any"
                  placeholder={result?.t_default != null ? Number(result.t_default.toPrecision(4)).toString() : "auto"}
                  value={tInput}
                  onChange={(e) => setTInput(e.target.value)}
                />
              </label>
              <button type="submit" disabled={phase === "loading"}>
                {phase === "loading" ? "Evaluating…" : "Evaluate"}
              </button>
              {tInput !== "" && (
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setTInput("");
                    load("");
                  }}
                  title="Evaluate at the calculator's design point again"
                >
                  Reset
                </button>
              )}
            </form>
          )}
          {result && (
            <div className="ft-metrics">
              <div className="ft-metric ft-metric-main">
                <span className="k">
                  {availability ? "Top event · unavailability" : `Top event · F(${fmtX(result.t)}${u})`}
                </span>
                <span className="v">{fmtP(result.top_event_probability)}</span>
              </div>
              <div className="ft-metric">
                <span className="k">{availability ? "Availability" : "Reliability R(t)"}</span>
                <span className="v">{fmtP(result.top_event_probability == null ? null : 1 - result.top_event_probability)}</span>
              </div>
              <div className="ft-metric">
                <span className="k">Gates · events</span>
                <span className="v">{result.n_gates} · {result.n_events}</span>
              </div>
              <div className="ft-metric">
                <span className="k">Minimal cut sets</span>
                <span className="v">{result.cut_sets.count?.toLocaleString() ?? "—"}</span>
              </div>
            </div>
          )}
        </div>
      )}
      {tDirty && <p className="hint ft-note">Evaluate to apply the new time.</p>}

      {error && <div className="card error">{error}</div>}
      {phase === "loading" && !result && <p className="muted-line">Building the fault tree…</p>}

      {result && canCalculate && (
        <>
          <p className="muted-line ft-note">
            {availability
              ? "Repairable diagram: each basic event is a block's long-run unavailability, so the top event is the system's steady-state unavailability."
              : result.t === result.t_default
              ? "At the calculator's design point, where system reliability is about 90%."
              : null}
            {" "}Series blocks become OR gates, parallel blocks AND gates, and k-of-n blocks VOTE gates on the failures that defeat them.
            {result.notes?.map((n) => ` ${n}`)}
          </p>

          <ReactFlowProvider>
            <TreeCanvas key={fetchedSig} result={result} name={name} active={active} />
          </ReactFlowProvider>

          <CommonCause result={result} />
          <CutSetTable result={result} />
          <ImportanceTable result={result} />
        </>
      )}
    </div>
  );
}
