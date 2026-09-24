import { createContext, useContext } from "react";
import { Handle, Position } from "reactflow";

// The React Flow node components of a reliability block diagram, shared by the
// builder (interactive) and the public read-only view (/p/:token). Pure
// presentation: what a block shows is the node data plus the three contexts
// below, which the host canvas provides.

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
// one) with left/right handles for the left-to-right flow.
export function ComponentNode({ id, data }) {
  const rbdUnit = useContext(RbdUnitContext);
  const repairable = useContext(RbdRepairableContext);
  const ccf = useContext(RbdCcfContext);
  const beta = ccf[id];
  const warn = unitWarning(data.model, rbdUnit);
  return (
    <div className={"rbd-comp" + (warn ? " unit-warn" : "") + (beta != null ? " ccf-member" : "") + stateClass(data.state)}>
      <Handle type="target" position={Position.Left} />
      <StatusBadge state={data.state} />
      {warn && <UnitWarn title={warn} />}
      {beta != null && (
        <span className="rbd-ccf-chip" title={`Common-cause group — β = ${beta}`}>CC β={beta}</span>
      )}
      <div className="rbd-comp-title">{data.label}</div>
      {data.model ? (
        <div className="rbd-comp-model">{modelSummary(data.model)}</div>
      ) : (
        <div className="rbd-comp-empty">No life model — double-click to set</div>
      )}
      {repairable && (
        data.repair ? (
          <div className="rbd-comp-repair">🛠 {modelSummary(data.repair)}</div>
        ) : (
          <div className="rbd-comp-empty warn">No repair time — double-click to set</div>
        )
      )}
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

export function StructureNode({ data }) {
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
