import { useMemo, useState } from "react";
import { allocateRbd } from "../api.js";
import { diagramGap } from "../rbdReadiness.js";
import { pctNear1 } from "../rbdCapacity.js";
import { formatNumber } from "../format.js";
import RbdEmptyState from "./RbdEmptyState.jsx";
import Select from "./Select.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import ResultSummary, { ResultDetails } from "./ui/ResultSummary.jsx";
import { graphSignature } from "./RbdValidation.jsx";
import { unitAbbr } from "./rbdModelText.js";
import "./RbdTargets.css";
import "./RbdDesignPanel.css";

// The Targets tab (#53): design to a system target. Enter a target — a
// reliability at a mission time, or a repairable diagram's long-run
// availability — pick a method, and see what each block needs against what it
// has now. The allocation comes from RePyability; nothing is saved.

// The methods, in plain words: what each does, when to use it, and its limits
// (after RePyability's comparison of them).
export const NONREPAIRABLE_METHODS = [
  {
    value: "cost_based",
    label: "Cost-based",
    what: "The cheapest way to the target: improving a block costs more the closer it gets to its best, and rises faster for a block that is hard to improve.",
    use: "Any diagram, when you know roughly how far and how easily each block can be improved (under Advanced).",
    limits: "The cost is a model, not your prices: it ranks the effort, it doesn't price it.",
  },
  {
    value: "improvement",
    label: "Improvement",
    what: "Cuts every block's chance of failing by the same factor, keeping their ratios. Fixed blocks stay as they are.",
    use: "Improving an existing design evenly, holding blocks you can't change.",
    limits: "A block that is already very good is asked to improve by the same factor as a weak one.",
  },
  {
    value: "minimum_effort",
    label: "Minimum effort",
    what: "Raises only the weakest blocks, to one common level, and leaves the rest as they are: the least total improvement.",
    use: "A series system whose weak blocks can be improved.",
    limits: "Series systems only (every block on the one path).",
  },
  {
    value: "simple",
    label: "Simple (weighted)",
    what: "Starts every block at 50% and makes the smallest change that meets the target; the blocks that matter most to the system move furthest. A weight makes a block take more or less of the change.",
    use: "Early design, from the diagram alone, before you have block data.",
    limits: "Ignores how reliable the blocks are today.",
  },
  {
    value: "equal",
    label: "Equal",
    what: "Every block gets the same reliability.",
    use: "A quick first budget when nothing is known about the blocks.",
    limits: "Asks as much of a simple, reliable block as of a complex, weak one.",
  },
];

export const REPAIRABLE_METHODS = [
  {
    value: "availability",
    label: "Availability",
    what: "The availability each block needs, and the longer mean life (at today's repair time) or the shorter repair time (at today's mean life) that gives it.",
    use: "Setting availability targets for suppliers or maintenance, block by block.",
    limits: "Blocks with scheduled maintenance, proof tests, standby, instant repair or a common-cause group keep theirs, and every repair must have a crew.",
  },
  {
    value: "mttf_mttr",
    label: "Mean life and repair time",
    what: "The cheapest pair of mean life and repair time for each block: a longer life or a quicker repair, whichever costs less at the margin.",
    use: "Choosing between reliability and maintainability improvements; or repair times only (maintainability allocation).",
    limits: "As for availability; the cost is a model that ranks the effort, not your prices.",
  },
];

const APPORTION = [
  { value: "cost_based", label: "Cost-based" },
  { value: "improvement", label: "Improvement" },
  { value: "minimum_effort", label: "Minimum effort (series)" },
  { value: "equal", label: "Equal" },
];

// The per-block options each method reads (Advanced).
const COLUMNS = {
  equal: [],
  simple: ["weight"],
  minimum_effort: [],
  improvement: ["fixed", "weight"],
  cost_based: ["fixed", "max", "feasibility"],
  availability: ["fixed"],
  "availability:improvement": ["fixed", "weight"],
  "availability:cost_based": ["fixed", "max", "feasibility"],
  mttf_mttr: ["fixed", "max_mttf", "min_mttr", "mttf_feasibility", "mttr_feasibility"],
};

const num = (v) => (v === "" || v == null ? null : Number(v));

// A starting mission time: a quarter of the shortest characteristic life.
function suggestTime(nodes) {
  const lives = [];
  for (const n of nodes) {
    const m = n.data?.model;
    const p = Object.fromEntries((m?.params || []).map((x) => [x.name, Number(x.value)]));
    if (m?.distribution_id === "weibull" && p.alpha > 0) lives.push(p.alpha);
    else if (m?.distribution_id === "exponential" && p.failure_rate > 0) lives.push(1 / p.failure_rate);
  }
  if (!lives.length) return "";
  return String(Number((Math.min(...lives) / 4).toPrecision(2)));
}

function MethodHelp({ methods }) {
  return (
    <details className="rbd-targets-help">
      <summary>How the methods compare</summary>
      <div className="rbd-targets-help-scroll">
        <table className="calc-table rbd-targets-help-table">
          <thead>
            <tr><th>Method</th><th>What it does</th><th>Use it for</th><th>Limits</th></tr>
          </thead>
          <tbody>
            {methods.map((m) => (
              <tr key={m.value}>
                <td><b>{m.label}</b></td>
                <td>{m.what}</td>
                <td>{m.use}</td>
                <td>{m.limits}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export default function RbdTargets({ graph, onBuild }) {
  const repairable = !!graph.repairable;
  const nodes = graph.nodes || [];
  const blocks = useMemo(
    () => nodes.filter((n) => !["input", "output", "knode"].includes(n.type) && !n.data?.repeat_of),
    [nodes]
  );
  const methods = repairable ? REPAIRABLE_METHODS : NONREPAIRABLE_METHODS;
  const [method, setMethod] = useState(null); // null: the first of the diagram's kind
  const [apportion, setApportion] = useState("cost_based");
  const [levers, setLevers] = useState("both");
  const [target, setTarget] = useState(null);
  const [t, setT] = useState(null);
  const [opts, setOpts] = useState({}); // {nodeId: {fixed, weight, max, …}}
  const [phase, setPhase] = useState("idle");
  const [error, setError] = useState(null); // {message, reachable?}
  const [run, setRun] = useState(null); // {result, sig}

  const chosen = methods.some((m) => m.value === method) ? method : methods[0].value;
  const about = methods.find((m) => m.value === chosen);
  const targetValue = target ?? (repairable ? "99.9" : "99");
  const tValue = t ?? suggestTime(blocks);
  const sig = graphSignature(graph);
  const unit = graph.unit || "";
  const u = unitAbbr(unit) ? ` ${unitAbbr(unit)}` : unit ? ` ${unit.toLowerCase()}` : "";
  const columnKey = chosen === "availability" && COLUMNS[`availability:${apportion}`] ? `availability:${apportion}` : chosen;
  const columns = COLUMNS[columnKey] || [];

  const gap = diagramGap(graph);
  if (gap) return <RbdEmptyState gap={gap} goal="set a target for it" onBuild={onBuild} />;

  const setOpt = (id, key, value) => setOpts((o) => ({ ...o, [id]: { ...(o[id] || {}), [key]: value } }));
  const options = () => {
    const out = {};
    const pick = (key, scale = 1) => {
      const m = {};
      for (const n of blocks) {
        const v = opts[n.id]?.[key];
        if (v !== undefined && v !== "") m[n.id] = Number(v) / scale;
      }
      return Object.keys(m).length ? m : null;
    };
    if (columns.includes("fixed")) {
      const fixed = blocks.filter((n) => opts[n.id]?.fixed).map((n) => n.id);
      if (fixed.length) out.fixed = fixed;
    }
    if (columns.includes("weight")) out.weights = pick("weight");
    if (columns.includes("max")) out.max = pick("max", 100);
    if (columns.includes("feasibility")) out.feasibility = pick("feasibility");
    if (columns.includes("max_mttf")) out.max_mttf = pick("max_mttf");
    if (columns.includes("min_mttr")) out.min_mttr = pick("min_mttr");
    if (columns.includes("mttf_feasibility")) out.mttf_feasibility = pick("mttf_feasibility");
    if (columns.includes("mttr_feasibility")) out.mttr_feasibility = pick("mttr_feasibility");
    if (chosen === "availability") out.availability_method = apportion;
    if (chosen === "mttf_mttr") out.levers = levers;
    for (const k of Object.keys(out)) if (out[k] == null) delete out[k];
    return out;
  };

  const allocate = async (goal = targetValue) => {
    setPhase("working");
    setError(null);
    try {
      const result = await allocateRbd({
        graph,
        target: num(goal) / 100,
        method: chosen,
        t: repairable ? null : num(tValue),
        options: options(),
      });
      setRun({ result, sig });
    } catch (e) {
      setRun(null);
      setError({ message: e.message, reachable: e.data?.reachable || null });
    } finally {
      setPhase("idle");
    }
  };

  const result = run?.result;
  const stale = run != null && run.sig !== sig;
  const measure = repairable ? "availability" : "reliability";

  // An unreachable target: the range, and one step to the most it can reach.
  const reach = error?.reachable;
  const reachable = reach && reach.high > 0
    ? Number((Math.floor(reach.high * (reach.high_reached ? 1e5 : 1e5 - 1e-3)) / 1e3).toFixed(3))
    : null;

  return (
    <div className="rbd-targets">
      <p className="muted-line rbd-targets-intro">
        Set a target for the whole system and see what each block needs to meet it. Exact, and free.
      </p>

      <div className="calc-controls rbd-targets-controls">
        <label className="calc-t">
          <span>Target {repairable ? "availability" : "reliability"} (%)</span>
          <input type="number" min="0" max="100" step="any" value={targetValue} onChange={(e) => setTarget(e.target.value)} />
        </label>
        {!repairable && (
          <label className="calc-t">
            <span>Mission time{unit ? ` (${unit.toLowerCase()})` : ""}</span>
            <input type="number" min="0" step="any" value={tValue} onChange={(e) => setT(e.target.value)} />
          </label>
        )}
        <div className="calc-t rbd-targets-method">
          <span>Method</span>
          <Select value={chosen} onChange={setMethod} options={methods.map((m) => ({ value: m.value, label: m.label }))} />
        </div>
        {chosen === "availability" && (
          <div className="calc-t rbd-targets-method">
            <span>Apportion by</span>
            <Select value={apportion} onChange={setApportion} options={APPORTION} />
          </div>
        )}
        {chosen === "mttf_mttr" && (
          <div className="calc-t">
            <span>Change</span>
            <SegmentedControl
              label="Change"
              value={levers}
              onChange={setLevers}
              options={[
                { value: "both", label: "Both" },
                { value: "mttf", label: "Mean life" },
                { value: "mttr", label: "Repair time" },
              ]}
            />
          </div>
        )}
        <button type="button" onClick={() => allocate()} disabled={phase === "working" || !blocks.length}>
          {phase === "working" ? "Allocating…" : "Allocate"}
        </button>
      </div>
      <p className="rbd-targets-about">{about.what} <span className="muted">{about.limits}</span></p>
      <MethodHelp methods={methods} />

      {columns.length > 0 && (
        <details className="rbd-targets-advanced">
          <summary>Advanced: per-block settings</summary>
          <div className="rbd-design-scroll">
            <table className="calc-table rbd-targets-table">
              <thead>
                <tr>
                  <th>Block</th>
                  {columns.includes("fixed") && <th title="Keeps what it has now">Fixed</th>}
                  {columns.includes("weight") && <th title="A larger weight takes more of the change; 0 none (default 1)">Weight</th>}
                  {columns.includes("max") && <th title={`The most this block's ${measure} can reach (default: towards 100%)`}>Best (%)</th>}
                  {columns.includes("feasibility") && <th title="How easily it improves, 0 to 0.99 (default 0.5): higher is easier">Feasibility</th>}
                  {columns.includes("max_mttf") && <th title="The longest mean life it can reach">Longest life{u}</th>}
                  {columns.includes("min_mttr") && <th title="The shortest repair time it can reach">Shortest repair{u}</th>}
                  {columns.includes("mttf_feasibility") && <th title="How easily its mean life rises, 0 to 0.99 (default 0.5)">Life feasibility</th>}
                  {columns.includes("mttr_feasibility") && <th title="How easily its repair time falls, 0 to 0.99 (default 0.5)">Repair feasibility</th>}
                </tr>
              </thead>
              <tbody>
                {blocks.map((n) => {
                  const o = opts[n.id] || {};
                  const field = (key, props = {}) => (
                    <td>
                      <input
                        className="rbd-design-num" type="number" step="any" min="0" placeholder="—"
                        aria-label={`${n.data?.label || n.id}: ${key}`} disabled={o.fixed}
                        value={o[key] ?? ""} onChange={(e) => setOpt(n.id, key, e.target.value)} {...props}
                      />
                    </td>
                  );
                  return (
                    <tr key={n.id}>
                      <td className="rbd-design-block">{n.data?.label || n.id}</td>
                      {columns.includes("fixed") && (
                        <td>
                          <input
                            type="checkbox" aria-label={`Fix ${n.data?.label || n.id}`} checked={!!o.fixed}
                            onChange={(e) => setOpt(n.id, "fixed", e.target.checked)}
                          />
                        </td>
                      )}
                      {columns.includes("weight") && field("weight")}
                      {columns.includes("max") && field("max", { max: "100" })}
                      {columns.includes("feasibility") && field("feasibility", { max: "0.99" })}
                      {columns.includes("max_mttf") && field("max_mttf")}
                      {columns.includes("min_mttr") && field("min_mttr")}
                      {columns.includes("mttf_feasibility") && field("mttf_feasibility", { max: "0.99" })}
                      {columns.includes("mttr_feasibility") && field("mttr_feasibility", { max: "0.99" })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {error && reach && (
        <ResultSummary
          tone="caveat"
          sentence={
            <>
              A system {measure} of <b>{String(targetValue).trim()}%</b> can't be reached this way: it can go{" "}
              {reach.low != null && <>from <b>{pctNear1(reach.low)}</b> </>}
              {reach.high_reached ? "up to" : "towards, but not to,"} <b>{pctNear1(reach.high)}</b>.
            </>
          }
        >
          Lower the target, free fixed blocks or raise their limits.{" "}
          {reachable != null && reachable > 0 && (
            <button type="button" className="link" onClick={() => { setTarget(String(reachable)); allocate(String(reachable)); }}>
              Try {reachable}%
            </button>
          )}
        </ResultSummary>
      )}
      {error && !reach && <p className="error" role="alert">{error.message}</p>}

      {result && <TargetResult result={result} stale={stale} unit={u} />}
    </div>
  );
}

function TargetResult({ result, stale, unit }) {
  const repairable = result.kind === "availability";
  const measure = repairable ? "availability" : "reliability";
  const rows = result.blocks;
  const raise = rows.filter((b) => b.required > b.current * (1 + 1e-9) + 1e-12);
  const met = result.system.current >= result.target - 1e-12;
  const at = repairable ? "" : ` at ${formatNumber(result.t)}${unit}`;
  const showLevers = repairable && rows.some((b) => b.mttf != null);
  const life = (v) => (v == null ? "—" : `${formatNumber(v)}${unit}`);

  return (
    <div className={"rbd-targets-result" + (stale ? " stale" : "")}>
      {stale && <p className="muted-line warn">The diagram has changed since: allocate again to update.</p>}
      <ResultSummary
        tone={met ? "good" : "neutral"}
        sentence={
          met ? (
            <>
              The system already meets <b>{pctNear1(result.target)}</b>{at}: it is at <b>{pctNear1(result.system.current)}</b>.
            </>
          ) : (
            <>
              To reach <b>{pctNear1(result.target)}</b> {measure}{at}, <b>{raise.length}</b> of {rows.length} blocks
              need{raise.length === 1 ? "s" : ""} to improve.
            </>
          )
        }
        stats={[
          { label: "System now", value: pctNear1(result.system.current) },
          { label: "With these targets", value: pctNear1(result.system.allocated) },
          { label: "Blocks to improve", value: `${raise.length} of ${rows.length}` },
        ]}
      />
      <div className="rbd-design-scroll">
        <table className="calc-table rbd-targets-table rbd-targets-out">
          <thead>
            <tr>
              <th>Block</th>
              <th>Now</th>
              <th>Needs</th>
              {showLevers && <th title="The mean life that gives it, at today's repair time">Mean life</th>}
              {showLevers && <th title="The repair time that gives it, at today's mean life">Repair time</th>}
            </tr>
          </thead>
          <tbody>
            {rows.map((b) => {
              const up = b.required > b.current * (1 + 1e-9) + 1e-12;
              const down = b.required < b.current * (1 - 1e-9) - 1e-12;
              return (
                <tr key={b.id}>
                  <td className="rbd-design-block">
                    {b.label}
                    {b.fixed && <span className="muted"> · fixed</span>}
                    {b.kept && !b.fixed && <span className="muted"> · keeps its own</span>}
                  </td>
                  <td>{pctNear1(b.current)}</td>
                  <td className={up ? "rbd-targets-up" : ""}>
                    {pctNear1(b.required)}
                    {down && <span className="muted"> (can fall)</span>}
                  </td>
                  {showLevers && (
                    <td>{b.mttf == null ? "—" : result.method === "mttf_mttr" || Math.abs(b.mttf - b.current_mttf) > 1e-9 * b.current_mttf
                      ? <>{life(b.current_mttf)} → <b>{life(b.mttf)}</b></> : life(b.current_mttf)}</td>
                  )}
                  {showLevers && (
                    <td>{b.mttr == null ? "—" : result.method === "mttf_mttr" || Math.abs(b.mttr - b.current_mttr) > 1e-9 * b.current_mttr
                      ? <>{life(b.current_mttr)} → <b>{life(b.mttr)}</b></> : life(b.current_mttr)}</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {repairable && result.method === "availability" && (
        <p className="hint">Either the mean life or the repair time shown gives a block its availability (or any pair in the same ratio).</p>
      )}
      {result.notes?.length > 0 && (
        <ResultDetails summary="Notes">
          <ul className="rbd-targets-notes">
            {result.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </ResultDetails>
      )}
    </div>
  );
}
