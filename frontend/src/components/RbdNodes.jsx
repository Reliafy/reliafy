import { createContext, useCallback, useContext } from "react";
import { Handle, Position, useStore } from "reactflow";
import { MaintenanceChips } from "./RbdBlockCosts.jsx";
import { RepairIcon } from "./icons.jsx";
import { unitInText } from "./unitText.js";

// The React Flow node components of a reliability block diagram, shared by the
// builder (interactive) and the public read-only view (/p/:token). Pure
// presentation: what a block shows is the node data plus the three contexts
// below, which the host canvas provides.

// "cold", "warm (0.3)" or "hot" from a standby node's dormancy factor (0 cold,
// 1 hot, in between warm); older diagrams carry only the `cold` flag.
export function standbyKind(data) {
  const d = data.dormancy ?? (data.cold ? 0 : 1);
  if (d <= 0) return "cold";
  if (d >= 1) return "hot";
  return `warm (${d})`;
}

// The RBD's unit is provided to node components so they can flag a model whose
// unit doesn't match.
export const RbdUnitContext = createContext("");
// Whether the RBD is repairable — component blocks then also show/prompt for a
// repair-time distribution.
export const RbdRepairableContext = createContext(false);
// Map of component id -> common-cause beta, so grouped blocks show a CC badge.
export const RbdCcfContext = createContext({});

// Warn only when a model has an explicit unit that differs from the RBD unit.
// A unitless model (e.g. entered as parameters) assumes the RBD unit — good.
export function unitWarning(model, rbdUnit) {
  if (!rbdUnit || !model) return null;
  const u = (model.unit || "").trim();
  if (!u || u === rbdUnit) return null;
  return `Unit mismatch — model is ${unitInText(u)}, RBD is ${unitInText(rbdUnit)}`;
}

function UnitWarn({ title }) {
  return (
    <span className="rbd-unit-warn" title={title} aria-label={title}>
      ⚠
    </span>
  );
}

// Marks a life model the assistant filled in as a guessed starting point
// (data.model.placeholder) — the numbers are illustrative until replaced.
function PlaceholderBadge() {
  const title = "Placeholder parameters — set real values before trusting the results";
  return (
    <span className="rbd-placeholder-chip" title={title} aria-label={title}>
      Placeholder
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

export function modelSummary(model) {
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
// one) with left/right handles for the left-to-right flow. A repeated block —
// a linked copy of another component (data.repeat_of) — shows that component.
export function ComponentNode(props) {
  return props.data?.repeat_of ? <RepeatedNode {...props} /> : <ComponentCard {...props} />;
}

// A linked copy reads the original's data live from the canvas, so editing
// the original (its label, model, repair time or pinned state) shows on every
// copy at once.
function RepeatedNode({ data }) {
  const source = data.repeat_of;
  const original = useStore(useCallback((s) => s.nodeInternals.get(source)?.data, [source]));
  const shown = original || { label: data.label };
  return <ComponentCard id={source} data={shown} repeat missing={!original} />;
}

function ComponentCard({ id, data, repeat = false, missing = false }) {
  const rbdUnit = useContext(RbdUnitContext);
  const repairable = useContext(RbdRepairableContext);
  const ccf = useContext(RbdCcfContext);
  const beta = ccf[id];
  const warn = unitWarning(data.model, rbdUnit);
  const placeholder = !!data.model?.placeholder;
  const repeatTitle = `Repeated block — the same component as “${data.label}”, drawn again. ` +
    "It works or fails wherever it is drawn; edit the original to change it.";
  return (
    <div className={"rbd-comp" + (repeat ? " repeat" : "") + (warn ? " unit-warn" : "") + (placeholder ? " placeholder" : "") + (beta != null ? " ccf-member" : "") + stateClass(data.state)}
         title={repeat ? repeatTitle : undefined}>
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      {warn && <UnitWarn title={warn} />}
      {placeholder && <PlaceholderBadge />}
      {beta != null && (
        <span className="rbd-ccf-chip" title={`Common-cause group — β = ${beta}`}>CC β={beta}</span>
      )}
      <div className="rbd-comp-title">
        {repeat && <span className="rbd-repeat-mark" aria-label="Repeated block">↺ </span>}
        {data.label}
      </div>
      {missing && <div className="rbd-comp-empty warn">The block it repeats was removed</div>}
      {missing ? null : data.model ? (
        <div className="rbd-comp-model" title={modelSummary(data.model)}>{modelSummary(data.model)}</div>
      ) : (
        <div className="rbd-comp-empty">No life model — double-click to set</div>
      )}
      {repairable && !missing && (
        data.instant_repair ? (
          <div className="rbd-comp-repair"><RepairIcon /> Instant repair</div>
        ) : data.repair ? (
          <div className="rbd-comp-repair" title={`Repair: ${modelSummary(data.repair)}`}><RepairIcon /> {modelSummary(data.repair)}</div>
        ) : (
          <div className="rbd-comp-empty warn">No repair time — double-click to set</div>
        )
      )}
      {repairable && <MaintenanceChips data={data} unit={rbdUnit} />}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

// n-out-of-k voting block: the system through this node works if at least n of
// the k branches connected to its output work. n and k are edited in a modal
// (right-click the node); the single output handle can fan out to multiple
// downstream nodes.
export function KNode({ data }) {
  const valid =
    Number(data.n) >= 1 && Number(data.k) >= 1 && Number(data.n) <= Number(data.k);
  // n = 1 is a junction: any one branch is enough. Same node and same maths (a
  // perfectly reliable gate), but drawn as a bare dot, because "1-out-of-k
  // voting" is a confusing way to describe merging branches back together and
  // there is no number worth showing inside it.
  const isJunction = valid && Number(data.n) === 1;
  if (isJunction) {
    return (
      <div className={"rbd-junction" + stateClass(data.state)}
           title="Junction — merges branches back into one path">
        <Handle type="target" position={Position.Left} />
        <StatusBadge state={data.state} />
        <Handle type="source" position={Position.Right} />
      </div>
    );
  }
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
export const BLOCK_TYPES = {
  standby: { label: "Standby", sub: "redundancy", cls: "rbd-standby" },
  loadshare: { label: "Load-sharing", sub: "shared load", cls: "rbd-loadshare" },
  series: { label: "Series", sub: "subsystem", cls: "rbd-series", count: true },
  parallel: { label: "Parallel", sub: "subsystem", cls: "rbd-parallel", count: true },
  subsystem: { label: "Sub-system", sub: "nested RBD", cls: "rbd-subsystem" },
};

export const BLOCK_HAS_MODEL = (kind) => kind === "series" || kind === "parallel";

export function StructureNode({ data: nodeData, type }) {
  // `kind` is set by the builder; graphs built elsewhere (import, the MCP
  // server, the assistant) carry only the node's type, which is the same thing.
  const data = nodeData.kind ? nodeData : { ...nodeData, kind: type };
  const meta = BLOCK_TYPES[data.kind] || {};
  const rbdUnit = useContext(RbdUnitContext);
  const repairable = useContext(RbdRepairableContext) && data.kind === "standby";
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
          {standbyKind(data) +
            ` · ${data.spares ?? 1} spare${(data.spares ?? 1) === 1 ? "" : "s"}`}
        </div>
        {data.model && (
          <div className="rbd-block-model">{modelSummary(data.model)}</div>
        )}
        {/* Repairable: each unit is repaired after it fails (#156). */}
        {repairable && (data.repair ? (
          <div className="rbd-comp-repair">
            <RepairIcon /> {modelSummary(data.repair)}{data.repair_one_at_a_time ? " · one at a time" : ""}
          </div>
        ) : (
          <div className="rbd-comp-empty warn">No repair time — double-click to set</div>
        ))}
      </>
    );
  } else if (data.kind === "loadshare") {
    body = (
      <>
        <div className="rbd-block-sub">
          {`${data.units ?? 2} units · load ${data.load ?? "?"} · k=${data.k ?? 1}`}
        </div>
        <div className={data.model ? "rbd-block-model" : "rbd-block-sub"}>
          {data.model ? modelSummary(data.model) : "No load-life model"}
        </div>
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
  const placeholder = !!data.model?.placeholder;

  return (
    <div
      className={
        "rbd-block " + (meta.cls || "") + (warn ? " unit-warn" : "") + (placeholder ? " placeholder" : "") + stateClass(data.state)
      }
    >
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      {warn && <UnitWarn title={warn} />}
      {placeholder && <PlaceholderBadge />}
      <div className="rbd-block-title">
        {data.label}
        {count ? <span className="rbd-block-count">×{count}</span> : null}
      </div>
      {body}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}


// Node type -> component map for a React Flow canvas showing an RBD.
export const RBD_NODE_TYPES = {
  component: ComponentNode,
  knode: KNode,
  standby: StructureNode,
  loadshare: StructureNode,
  series: StructureNode,
  parallel: StructureNode,
  subsystem: StructureNode,
};
