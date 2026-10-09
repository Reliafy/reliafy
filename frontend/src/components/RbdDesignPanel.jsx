import { useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import { ACCENT, DATA_INK, SURFACE, fitLine, optimumMarker, referenceShape } from "../plotTheme.js";
import { applyRbdDesign, designRbd } from "../api.js";
import RbdCheapestDesign from "./RbdCheapestDesign.jsx";
import RbdIntervals, { maintainedBlocks } from "./RbdIntervals.jsx";
import RbdEmptyState, { TabEmptyState } from "./RbdEmptyState.jsx";
import { diagramGap } from "../rbdReadiness.js";
import LifeModelModal from "./LifeModelModal.jsx";
import Select from "./Select.jsx";
import { modelSummary } from "./RbdNodes.jsx";
import { graphSignature } from "./RbdValidation.jsx";
import "./RbdDesignPanel.css";
import { unitInText } from "./unitText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";

// "Design for a target" (redundancy allocation, #98): how many copies of each
// block a non-repairable diagram needs — the most reliable design within a
// budget, or the cheapest that reaches a target reliability at a mission time
// — and the cost–reliability trade-off around it. A chosen design is drawn
// onto the canvas (unsaved) for the user to review and save.

// Blocks that can be given copies: single components, and parallel blocks of
// identical units (whose n becomes the number of copies).
const DESIGNABLE = new Set(["component", "parallel"]);
const MAX_COPIES = 8;
const MAX_TYPES = 3; // alternatives next to the block's own model
const KIND_NAMES = {
  knode: "k-out-of-n",
  standby: "standby",
  loadshare: "load-sharing",
  series: "series",
  subsystem: "sub-system",
};
const STRATEGIES = [
  { value: "active", label: "Active" },
  { value: "cold", label: "Cold standby" },
  { value: "choose", label: "Best of both" },
];

const fmtR = (v) => (v == null || !Number.isFinite(v) ? "—" : v >= 0.9999 ? v.toFixed(6) : v.toFixed(4));
const fmtN = (v) =>
  v == null || !Number.isFinite(v) ? "—" : Number(v.toPrecision(6)).toLocaleString(undefined, { maximumFractionDigits: 4 });
const num = (v) => (v === "" || v == null ? null : Number(v));

// A starting mission time: a quarter of the shortest characteristic life
// among the designable blocks (Weibull alpha, exponential 1/rate).
function suggestTime(blocks) {
  const lives = [];
  for (const n of blocks) {
    const m = n.data?.model;
    const p = Object.fromEntries((m?.params || []).map((x) => [x.name, Number(x.value)]));
    if (m?.distribution_id === "weibull" && p.alpha > 0) lives.push(p.alpha);
    else if (m?.distribution_id === "exponential" && p.failure_rate > 0) lives.push(1 / p.failure_rate);
  }
  if (!lives.length) return "";
  return String(Number((Math.min(...lives) / 4).toPrecision(2)));
}

function defaults(node) {
  const current = node.type === "parallel" ? Math.max(Number(node.data?.n) || 1, 1) : 1;
  return {
    include: true,
    cost: "1",
    weight: "",
    volume: "",
    max: String(Math.min(Math.max(3, current + 1), MAX_COPIES)),
    required: "1",
    strategy: "active",
    switching: "1",
    types: [],
  };
}

// How a design builds one block, in words.
function arrangement(b) {
  if (b.copies === 1) return "1 unit";
  if (b.strategy === "cold") {
    const spares = b.copies - 1;
    return `1 running + ${spares} cold spare${spares === 1 ? "" : "s"}`;
  }
  if (b.required > 1) return `${b.required}-out-of-${b.copies} active`;
  return `${b.copies} active in parallel`;
}

// ``readOnly``: a sample or a view-only share — ``onSaveCopy`` saves a copy to edit.
export default function RbdDesignPanel({ graph, onApply, onView, onBuild, readOnly = false, onSaveCopy = null }) {
  const nodes = graph.nodes || [];
  // A component drawn in several places (a repeated block, #102) — the copy
  // or its original — can't be given copies; it stays as drawn.
  const repeated = useMemo(() => {
    const ids = new Set();
    for (const n of nodes) if (n.data?.repeat_of) { ids.add(n.id); ids.add(n.data.repeat_of); }
    return ids;
  }, [nodes]);
  const canDesign = (n) => DESIGNABLE.has(n.type) && n.data?.model && !repeated.has(n.id);
  const designable = useMemo(() => nodes.filter(canDesign), [nodes, repeated]); // eslint-disable-line react-hooks/exhaustive-deps
  const fixed = useMemo(
    () => nodes.filter((n) => n.type !== "input" && n.type !== "output" && !canDesign(n)),
    [nodes, repeated] // eslint-disable-line react-hooks/exhaustive-deps
  );
  const [settings, setSettings] = useState({}); // {nodeId: row settings}
  const [t, setT] = useState(null); // null = not yet touched (use the suggestion)
  const [goal, setGoal] = useState("budget"); // budget | target
  const [budget, setBudget] = useState({ cost: "", weight: "", volume: "" });
  const [target, setTarget] = useState("0.99");
  const [useWeight, setUseWeight] = useState(false);
  const [useVolume, setUseVolume] = useState(false);
  const [mixing, setMixing] = useState(true);
  const [phase, setPhase] = useState("idle"); // idle | working
  const [error, setError] = useState(null);
  const [run, setRun] = useState(null); // { result, blocks, sig }
  const [picked, setPicked] = useState(null); // index into result.front, or null = the answer
  const [applied, setApplied] = useState(null); // { prev, reliability, sig }
  const [modelFor, setModelFor] = useState(null); // { id, index } of a type being edited

  const sig = graphSignature(graph);
  const tValue = t ?? suggestTime(designable);
  const row = (n) => settings[n.id] || defaults(n);
  const update = (id, patch) =>
    setSettings((s) => {
      const node = nodes.find((n) => n.id === id);
      return { ...s, [id]: { ...(s[id] || defaults(node)), ...patch } };
    });
  const updateType = (id, index, patch) => {
    const node = nodes.find((n) => n.id === id);
    const types = [...row(node).types];
    types[index] = { ...types[index], ...patch };
    update(id, { types });
  };

  const included = designable.filter((n) => row(n).include);
  const currentCost = included.reduce(
    (sum, n) => sum + (Number(row(n).cost) || 0) * (n.type === "parallel" ? Math.max(Number(n.data?.n) || 1, 1) : 1),
    0
  );
  const budgetCost = budget.cost === "" ? String(Number((2 * currentCost).toPrecision(4))) : budget.cost;

  // Nothing to design yet (#271) — nor, on a repairable diagram, any
  // intervals to choose: one next step for the whole tab.
  const gap = diagramGap(graph);
  if (gap) {
    return (
      <RbdEmptyState
        gap={gap}
        goal={graph.repairable ? "design it and choose its maintenance intervals" : "design for a target"}
        onBuild={onBuild}
      />
    );
  }

  if (graph.repairable) {
    // Nothing to design with yet — no purchase price, no scheduled
    // maintenance: one line on what the tab does, one on what it needs, and
    // the way there (a sample is read-only: a copy of it can be edited).
    const maintained = maintainedBlocks(graph);
    const priced = (graph.nodes || []).some((n) => n.type === "component" && Number(n.data?.costs?.acquisition) > 0);
    if (!priced && !maintained.replacement.length && !maintained.proof_test.length) {
      return (
        <TabEmptyState
          title="Design: the cheapest copies of each block, and the best maintenance intervals"
          need="It needs a purchase price, age replacement or proof tests on a block (double-click it → Cost & maintenance)."
          action={readOnly
            ? onSaveCopy && { label: "Save a copy to edit", onClick: onSaveCopy }
            : onBuild && { label: "Go to the Builder", onClick: onBuild }}
        />
      );
    }
    // Repairable diagrams: the copies with the lowest total cost of ownership
    // (#99), and the maintenance and proof-test intervals chosen together (#228).
    return (
      <>
        <RbdCheapestDesign graph={graph} onApply={onApply} onView={onView} />
        <RbdIntervals graph={graph} onApply={onApply} onView={onView} />
      </>
    );
  }

  const payloadBlocks = () =>
    included.map((n) => {
      const r = row(n);
      const amounts = (x) => ({
        cost: num(x.cost),
        ...(useWeight && x.weight !== "" ? { weight: num(x.weight) } : {}),
        ...(useVolume && x.volume !== "" ? { volume: num(x.volume) } : {}),
      });
      return {
        id: n.id,
        name: "Current",
        ...amounts(r),
        max_copies: num(r.max),
        required: num(r.required),
        strategy: r.strategy,
        switching: num(r.switching),
        types: r.types.map((ty) => ({ name: ty.name, model: ty.model, ...amounts(ty) })),
      };
    });

  const find = async () => {
    setPhase("working");
    setError(null);
    const blocks = payloadBlocks();
    const limits = {
      ...(goal === "budget" ? { cost: num(budgetCost) } : {}),
      ...(useWeight && budget.weight !== "" ? { weight: num(budget.weight) } : {}),
      ...(useVolume && budget.volume !== "" ? { volume: num(budget.volume) } : {}),
    };
    try {
      const result = await designRbd({
        graph,
        t: num(tValue),
        blocks,
        budget: Object.keys(limits).length ? limits : null,
        target: goal === "target" ? num(target) : null,
        mixing,
      });
      setRun({ result, blocks, sig });
      setPicked(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setPhase("idle");
    }
  };

  const result = run?.result;
  const stale = run != null && run.sig !== sig;
  const shown = result ? (picked == null ? result.design : result.front[picked]) : null;
  const unit = graph.unit ? ` ${graph.unit}` : "";
  const hasTypes = included.some((n) => row(n).types.length > 0);

  const apply = async () => {
    setError(null);
    try {
      const res = await applyRbdDesign({
        graph,
        blocks: run.blocks,
        design: shown.blocks,
        t: result.t,
      });
      // Common-cause groups too: a grouped block's copies join its group.
      const prev = { nodes: graph.nodes, edges: graph.edges, ccf_groups: graph.ccf_groups || [] };
      onApply(res.graph);
      setApplied({
        prev,
        reliability: res.reliability,
        notes: res.notes || [],
        sig: graphSignature({ ...graph, ...res.graph }),
      });
    } catch (e) {
      setError(e.message);
    }
  };
  const undo = () => {
    onApply(applied.prev);
    setApplied(null);
  };
  const appliedCurrent = applied && applied.sig === sig;

  return (
    <div className="rbd-design">
      <p className="muted-line rbd-design-intro">
        Choose how many copies of each block to fit: the most reliable design within a budget, or
        the cheapest one that reaches a target reliability at the mission time. Exact, and free.
      </p>

      <div className="calc-controls rbd-design-goal">
        <label className="calc-t">
          <span>Mission time t{graph.unit ? ` (${graph.unit})` : ""}</span>
          <input type="number" min="0" step="any" value={tValue} onChange={(e) => setT(e.target.value)} />
        </label>
        <div className="calc-t">
          <span>Goal</span>
          <SegmentedControl
            label="Goal"
            value={goal}
            onChange={setGoal}
            options={[
              { value: "budget", label: "Most reliable within a budget" },
              { value: "target", label: "Cheapest to reach a target" },
            ]}
          />
        </div>
        {goal === "budget" ? (
          <label className="calc-t">
            <span>Cost budget</span>
            <input
              type="number" min="0" step="any" value={budgetCost}
              onChange={(e) => setBudget((b) => ({ ...b, cost: e.target.value }))}
            />
          </label>
        ) : (
          <label className="calc-t">
            <span>Target R(t)</span>
            <input type="number" min="0" max="1" step="any" value={target} onChange={(e) => setTarget(e.target.value)} />
          </label>
        )}
        {useWeight && (
          <label className="calc-t">
            <span>Weight limit</span>
            <input
              type="number" min="0" step="any" placeholder="none" value={budget.weight}
              onChange={(e) => setBudget((b) => ({ ...b, weight: e.target.value }))}
            />
          </label>
        )}
        {useVolume && (
          <label className="calc-t">
            <span>Volume limit</span>
            <input
              type="number" min="0" step="any" placeholder="none" value={budget.volume}
              onChange={(e) => setBudget((b) => ({ ...b, volume: e.target.value }))}
            />
          </label>
        )}
      </div>

      <div className="rbd-design-toggles">
        <label><input type="checkbox" checked={useWeight} onChange={(e) => setUseWeight(e.target.checked)} /> Weight</label>
        <label><input type="checkbox" checked={useVolume} onChange={(e) => setUseVolume(e.target.checked)} /> Volume</label>
        <label title="With alternative types, a block's copies may be of different types">
          <input type="checkbox" checked={mixing} onChange={(e) => setMixing(e.target.checked)} /> Mix types within a block
        </label>
      </div>

      {designable.length === 0 ? (
        <p className="hint">
          Add components with life models on the Builder tab — each one can then be given copies.
        </p>
      ) : (
        <div className="rbd-design-scroll">
          <table className="calc-table rbd-design-table">
            <thead>
              <tr>
                <th>Block</th>
                <th title="Copies as drawn">Now</th>
                <th>Unit cost</th>
                {useWeight && <th>Weight</th>}
                {useVolume && <th>Volume</th>}
                <th title="The most copies of this block">Max copies</th>
                <th title="How many copies must work (k-out-of-n)">Must work</th>
                <th>Redundancy</th>
                <th>Types</th>
              </tr>
            </thead>
            <tbody>
              {designable.map((n) => {
                const r = row(n);
                const off = !r.include;
                return [
                  <tr key={n.id} className={off ? "off" : ""}>
                    <td className="rbd-design-block">
                      <label title={off ? "Stays as drawn" : "Designed"}>
                        <input type="checkbox" checked={r.include} onChange={(e) => update(n.id, { include: e.target.checked })} />
                        <span>
                          <b>{n.data.label || n.id}</b>
                          <small>{modelSummary(n.data.model)}</small>
                        </span>
                      </label>
                    </td>
                    <td>{n.type === "parallel" ? Math.max(Number(n.data.n) || 1, 1) : 1}</td>
                    <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} value={r.cost} onChange={(e) => update(n.id, { cost: e.target.value })} /></td>
                    {useWeight && (
                      <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} placeholder="0" value={r.weight} onChange={(e) => update(n.id, { weight: e.target.value })} /></td>
                    )}
                    {useVolume && (
                      <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} placeholder="0" value={r.volume} onChange={(e) => update(n.id, { volume: e.target.value })} /></td>
                    )}
                    <td><input className="rbd-design-num sm" type="number" min="1" max={MAX_COPIES} step="1" disabled={off} value={r.max} onChange={(e) => update(n.id, { max: e.target.value })} /></td>
                    <td>
                      <input
                        className="rbd-design-num sm" type="number" min="1" step="1"
                        disabled={off || r.strategy !== "active"}
                        title={r.strategy !== "active" ? "Standby spares run one unit at a time" : undefined}
                        value={r.strategy !== "active" ? "1" : r.required}
                        onChange={(e) => update(n.id, { required: e.target.value })}
                      />
                    </td>
                    <td>
                      <div className="rbd-design-strategy">
                        <Select
                          value={r.strategy}
                          disabled={off}
                          onChange={(v) => update(n.id, { strategy: v, ...(v !== "active" ? { required: "1" } : {}) })}
                          options={STRATEGIES}
                        />
                        {r.strategy !== "active" && (
                          <label className="rbd-design-switch" title="Probability that switching to a spare works">
                            <span>switch R</span>
                            <input className="rbd-design-num sm" type="number" min="0" max="1" step="any" disabled={off} value={r.switching} onChange={(e) => update(n.id, { switching: e.target.value })} />
                          </label>
                        )}
                      </div>
                    </td>
                    <td>
                      <button
                        type="button"
                        className="link"
                        disabled={off || r.types.length >= MAX_TYPES}
                        onClick={() => {
                          update(n.id, {
                            types: [...r.types, { name: `Type ${r.types.length + 2}`, model: null, cost: r.cost, weight: "", volume: "" }],
                          });
                          setModelFor({ id: n.id, index: r.types.length });
                        }}
                      >
                        + type
                      </button>
                    </td>
                  </tr>,
                  ...r.types.map((ty, i) => (
                    <tr key={`${n.id}-t${i}`} className={"rbd-design-type" + (off ? " off" : "")}>
                      <td className="rbd-design-block">
                        <span className="rbd-design-type-name">
                          <input value={ty.name} disabled={off} onChange={(e) => updateType(n.id, i, { name: e.target.value })} aria-label="Type name" />
                          <button type="button" className="link" disabled={off} onClick={() => setModelFor({ id: n.id, index: i })}>
                            {ty.model ? modelSummary(ty.model) : "Set life model"}
                          </button>
                        </span>
                      </td>
                      <td />
                      <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} value={ty.cost} onChange={(e) => updateType(n.id, i, { cost: e.target.value })} /></td>
                      {useWeight && (
                        <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} placeholder="0" value={ty.weight} onChange={(e) => updateType(n.id, i, { weight: e.target.value })} /></td>
                      )}
                      {useVolume && (
                        <td><input className="rbd-design-num" type="number" min="0" step="any" disabled={off} placeholder="0" value={ty.volume} onChange={(e) => updateType(n.id, i, { volume: e.target.value })} /></td>
                      )}
                      <td colSpan={3} className="rbd-design-type-note">alternative type</td>
                      <td>
                        <button
                          type="button" className="link" disabled={off}
                          onClick={() => update(n.id, { types: r.types.filter((_, j) => j !== i) })}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  )),
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
      {fixed.length > 0 && (
        <p className="hint rbd-design-fixed">
          Stay as drawn —{" "}
          {Object.entries(
            fixed.reduce((groups, n) => {
              const kind = repeated.has(n.id) ? "repeated block"
                : DESIGNABLE.has(n.type) ? "no life model" : KIND_NAMES[n.type] || n.type;
              return { ...groups, [kind]: [...(groups[kind] || []), n.data?.label || n.id] };
            }, {})
          )
            .map(([kind, labels]) => `${kind}: ${[...new Set(labels)].join(", ")}`)
            .join("; ")}
          . Only single components and parallel blocks of identical units can be given copies.
        </p>
      )}

      <div className="rbd-calc-actions">
        <button type="button" onClick={find} disabled={phase === "working" || included.length === 0}>
          {phase === "working" ? "Finding design…" : result && !stale ? "Find again" : "Find design"}
        </button>
        {stale && !appliedCurrent && <span className="hint">The diagram has changed — find the design again.</span>}
      </div>

      {error && <div className="card error">{error}</div>}

      {appliedCurrent && (
        <div className="card note rbd-design-applied" role="status">
          <p>
            <b>Drawn on the diagram — not saved.</b> Its reliability at t = {fmtN(result.t)}
            {unit && ` ${unitInText(unit)}`} is {fmtR(applied.reliability)}. Review it on the Builder tab, then Save RBD to keep it.
          </p>
          {applied.notes.map((note) => <p key={note}>{note}</p>)}
          <div className="rbd-design-applied-actions">
            <button type="button" onClick={onView}>View the diagram</button>
            <button type="button" className="secondary" onClick={undo}>Undo</button>
          </div>
        </div>
      )}

      {result && !stale && (
        <DesignResult
          result={result}
          shown={shown}
          picked={picked}
          onPick={setPicked}
          unit={unit}
          hasTypes={hasTypes}
          designable={designable}
          onApply={apply}
        />
      )}

      {modelFor && (
        <LifeModelModal
          initial={{ model: row(nodes.find((n) => n.id === modelFor.id)).types[modelFor.index]?.model }}
          onClose={() => {
            // A new type with no model yet is dropped when the picker is cancelled.
            const node = nodes.find((n) => n.id === modelFor.id);
            const types = row(node).types;
            if (!types[modelFor.index]?.model) update(modelFor.id, { types: types.filter((_, j) => j !== modelFor.index) });
            setModelFor(null);
          }}
          onSubmit={({ model }) => {
            updateType(modelFor.id, modelFor.index, { model });
            setModelFor(null);
          }}
        />
      )}
    </div>
  );
}

function DesignResult({ result, shown, picked, onPick, unit, hasTypes, designable, onApply }) {
  const extra = result.resources.filter((r) => r !== "cost");
  const nowCopies = Object.fromEntries(
    designable.map((n) => [n.id, n.type === "parallel" ? Math.max(Number(n.data.n) || 1, 1) : 1])
  );
  const front = result.front || [];
  const traces = [
    fitLine({
      x: front.map((d) => d.cost),
      y: front.map((d) => d.reliability),
      mode: "lines+markers",
      line: { shape: "hv" },
      marker: { color: ACCENT, size: 7 },
      name: "Best design for its cost",
      hovertemplate: "Cost %{x:,}<br>R(t) %{y:.6f}<extra>click to inspect</extra>",
    }),
    {
      x: [result.current.cost],
      y: [result.current.reliability],
      type: "scatter",
      mode: "markers",
      marker: { color: DATA_INK, size: 10, symbol: "diamond", line: { color: SURFACE, width: 1.5 } },
      name: "As drawn",
      hovertemplate: "As drawn<br>Cost %{x:,}<br>R(t) %{y:.6f}<extra></extra>",
    },
    optimumMarker({
      x: [shown.cost],
      y: [shown.reliability],
      mode: "markers",
      marker: { size: 12 },
      name: picked == null ? (result.mode === "target" ? "Cheapest reaching the target" : "Best within the budget") : "Selected design",
      showlegend: true,
      hovertemplate: "Cost %{x:,}<br>R(t) %{y:.6f}<extra></extra>",
    }),
  ];
  const shapes = [];
  if (result.mode === "budget" && result.budget.cost != null) shapes.push(referenceShape({ x: result.budget.cost }));
  if (result.mode === "target") shapes.push(referenceShape({ y: result.target }));
  return (
    <div className="rbd-design-result">
      <div className="params">
        <div className="stat">
          <div className="value">{fmtR(result.current.reliability)} → {fmtR(shown.reliability)}</div>
          <div className="name">R(t = {fmtN(result.t)}{unit}), as drawn → design</div>
        </div>
        <div className="stat">
          <div className="value">{fmtN(result.current.cost)} → {fmtN(shown.cost)}</div>
          <div className="name">Cost{result.mode === "budget" && result.budget.cost != null ? ` (budget ${fmtN(result.budget.cost)})` : ""}</div>
        </div>
        {extra.map((r) => (
          <div className="stat" key={r}>
            <div className="value">{fmtN(result.current.resources[r])} → {fmtN(shown.resources[r])}</div>
            <div className="name">
              {r[0].toUpperCase() + r.slice(1)}
              {result.budget[r] != null ? ` (limit ${fmtN(result.budget[r])})` : ""}
            </div>
          </div>
        ))}
      </div>
      {(result.common_cause || []).map((g) => (
        <p className="hint" key={g.id}>
          Common-cause group {g.members.join(" · ")} (β = {g.beta}{g.basis === "probability" ? ", probability basis" : ""}) is included
          {g.designed.length
            ? ": extra copies share the group, so redundancy pays off less than with independent failures."
            : " in every design's reliability."}
        </p>
      ))}
      {result.method === "greedy" && (
        <p className="hint">
          Too many combinations for a proven optimum in reasonable time, so this is the library's
          fast greedy search: usually optimal, not guaranteed. Fewer max copies or blocks gives an
          exact answer.
        </p>
      )}

      <div className="rbd-design-head">
        <div className="rbd-section-head">
          {picked == null
            ? result.mode === "target"
              ? `Cheapest design reaching R(t) ≥ ${result.target}`
              : "Most reliable design within the budget"
            : "Selected from the trade-off curve"}
        </div>
        {picked != null && (
          <button type="button" className="link" onClick={() => onPick(null)}>
            Back to the {result.mode === "target" ? "cheapest" : "best"} design
          </button>
        )}
      </div>
      <table className="calc-table rbd-design-out">
        <thead>
          <tr>
            <th>Block</th>
            <th>Now</th>
            <th>Design</th>
            {hasTypes && <th>Types</th>}
            <th>Cost</th>
            {extra.map((r) => <th key={r}>{r[0].toUpperCase() + r.slice(1)}</th>)}
          </tr>
        </thead>
        <tbody>
          {shown.blocks.map((b) => (
            <tr key={b.id} className={b.copies !== nowCopies[b.id] ? "changed" : ""}>
              <td className="calc-row-label">{b.label}</td>
              <td>{nowCopies[b.id] ?? "—"}</td>
              <td>{arrangement(b)}</td>
              {hasTypes && <td>{b.mix.map((m) => `${m.copies}× ${m.name}`).join(", ")}</td>}
              <td>{fmtN(b.resources.cost)}</td>
              {extra.map((r) => <td key={r}>{fmtN(b.resources[r])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="rbd-calc-actions">
        <button type="button" onClick={onApply} title="Draw this design on the canvas — nothing is saved">
          Apply to diagram
        </button>
        <span className="hint">Draws the design on the canvas for you to review; nothing is saved.</span>
      </div>

      {front.length > 1 && (
        <>
          <div className="rbd-section-head">Cost–reliability trade-off</div>
          <Plot
            data={traces}
            layout={{
              height: 380,
              xaxis: { title: { text: "Cost" } },
              yaxis: { title: { text: `R(t = ${fmtN(result.t)}${unit})` } },
              shapes,
              hovermode: "closest",
            }}
            onClick={(ev) => {
              const p = ev?.points?.[0];
              if (p && p.curveNumber === 0) onPick(p.pointIndex);
            }}
          />
          <p className="muted-line" style={{ margin: 0 }}>
            Each point is the most reliable design for its cost
            {extra.length ? ` within the ${extra.join(" and ")} limits` : ""}. Click one to inspect it
            and apply it instead.
            {result.front_note ? ` ${result.front_note}` : ""}
          </p>
        </>
      )}
      {front.length <= 1 && result.front_note && <p className="muted-line">{result.front_note}</p>}
    </div>
  );
}
