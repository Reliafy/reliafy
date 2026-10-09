import { useEffect, useState } from "react";
import { getRcmMaintenanceTasks, listRcmStudies } from "../api.js";
import { unitInText } from "./unitText.js";
import { unitAbbr } from "./rbdModelText.js";
import SegmentedControl from "./ui/SegmentedControl.jsx";

// A repairable block's costs and maintenance (#99, #100, #156, #157), edited in
// the block dialog's Maintenance (or Proof test) and Costs sections (#314).
// Stored on the node as
//   data.costs      = {repair, replace, downtime, acquisition}   (numbers, optional)
//   data.preventive = {policy: "age"|"block", interval, duration, cost,
//                      opportunity}               (age: renewed early at a group stop)
//                   | {policy: "condition", interval, threshold, inspection_cost,
//                      duration, cost}             (replaced on condition at inspections)
//   data.inspection = {interval, duration, cost,   (hidden failures, proof-tested)
//                      offset, coverage, full_test} (staggered / imperfect tests)
//   data.maintenance_group = "name"                 (shares the group's set-up cost)
//   data.crew_priority = 2                          (place in the repair-crew queue)
//   data.instant_repair = true                      (no repair-time model needed)
//   data.rcm_source = {study_id, study, mode_id, mode, target, filled, ...}
//                     (the RCM study the schedule was filled from: display only)
// A standby group (mode "standby") takes only costs and a crew priority.
// A duration of 0/blank is instant. A block has scheduled replacement or proof
// tests, not both (as in RePyability). A cost charged per action (repair,
// parts, each replacement or test) may be a range {min, max}: RePyability
// draws it uniformly at every action, so the simulated cost spreads while the
// exact cost rate takes its mean.

const COSTS = [
  { key: "repair", label: "Repair cost", per: "per failure", ranged: true, help: "Labour, call-out: charged at every failure." },
  { key: "replace", label: "Parts cost", per: "per failure", ranged: true, help: "The spare part or replacement unit, charged at every failure." },
  { key: "downtime", label: "Block downtime", per: "per {u}", help: "Charged while this block is down, even if the system is up (a degraded-mode penalty). System-wide lost production is set on the diagram." },
  { key: "acquisition", label: "Purchase price", per: "once", help: "Buying the unit: counted in the total cost of ownership and the cheapest design, not the running cost." },
];

const KINDS = [
  { id: "none", label: "None" },
  { id: "preventive", label: "Scheduled replacement" },
  { id: "inspection", label: "Hidden failures, proof-tested" },
];

const str = (v) => (v == null ? "" : String(v));
const isBlank = (v) => v == null || String(v).trim() === "";
const nonNeg = (v) => isBlank(v) || (Number.isFinite(Number(v)) && Number(v) >= 0);
const positive = (v) => !isBlank(v) && Number.isFinite(Number(v)) && Number(v) > 0;
const numOrNull = (v) => (isBlank(v) ? null : Number(v));
const fmt = (v) => (Number.isFinite(Number(v)) ? Number(Number(v).toPrecision(4)).toLocaleString() : "?");

// A cost's editing state: a single value, or a min–max range.
const isRange = (v) => v != null && typeof v === "object";
const costState = (v) =>
  isRange(v) ? { range: true, value: "", min: str(v.min), max: str(v.max) } : { range: false, value: str(v), min: "", max: "" };
const costBlank = (c) => (c.range ? isBlank(c.min) && isBlank(c.max) : isBlank(c.value));
function costValue(c) {
  if (!c.range) return numOrNull(c.value);
  if (costBlank(c)) return null;
  const lo = numOrNull(c.min);
  const hi = numOrNull(c.max);
  return lo != null && lo === hi ? lo : { min: lo, max: hi };
}
function costProblem(c, name) {
  if (!c.range) return nonNeg(c.value) ? null : `${name} must be a non-negative number.`;
  if (costBlank(c)) return null;
  if (isBlank(c.min) || isBlank(c.max)) return `${name}: give both ends of the range.`;
  if (!nonNeg(c.min) || !nonNeg(c.max)) return `${name}: the range must be non-negative numbers.`;
  if (Number(c.min) > Number(c.max)) return `${name}: the range's min is above its max.`;
  return null;
}
// Switch between a single value and a range, keeping what was typed.
function toggleRange(c) {
  if (c.range) {
    const both = !isBlank(c.min) && !isBlank(c.max) && nonNeg(c.min) && nonNeg(c.max);
    const value = both ? String((Number(c.min) + Number(c.max)) / 2) : isBlank(c.min) ? c.max : c.min;
    return { range: false, value, min: "", max: "" };
  }
  return { range: true, value: "", min: c.value, max: c.value };
}

function initialState(data = {}) {
  const sched = data.preventive || data.inspection || {};
  // A duration given as a distribution (e.g. by the assistant) is kept as is.
  const isModel = sched.duration != null && typeof sched.duration === "object";
  const test = data.inspection || {};
  return {
    costs: Object.fromEntries(COSTS.map((c) => [c.key, costState(data.costs?.[c.key])])),
    kind: data.preventive ? "preventive" : data.inspection ? "inspection" : "none",
    policy: data.preventive?.policy || "age",
    interval: str(sched.interval),
    duration: isModel ? "" : str(sched.duration),
    durationModel: isModel ? sched.duration : null,
    cost: costState(sched.cost),
    // Condition-based replacement (#157).
    threshold: str(data.preventive?.threshold),
    inspectionCost: costState(data.preventive?.inspection_cost),
    // Opportunistic renewal in a maintenance group (#157).
    group: data.maintenance_group || "",
    opportunity: str(data.preventive?.opportunity),
    // Staggered and imperfect proof tests (#136).
    offset: str(test.offset),
    coverage: str(test.coverage),
    fullTest: str(test.full_test),
    priority: str(data.crew_priority),
    rcm: data.rcm_source || null,
  };
}

const prob = (v) => !isBlank(v) && Number.isFinite(Number(v)) && Number(v) >= 0 && Number(v) <= 1;
const partialCoverage = (s) => !isBlank(s.coverage) && prob(s.coverage) && Number(s.coverage) < 1;

// The node-data patch for the section's state: every key present, null to remove.
function toExtras(s, mode = "component") {
  const costs = {};
  for (const c of COSTS) if (!costBlank(s.costs[c.key])) costs[c.key] = costValue(s.costs[c.key]);
  const priority = numOrNull(s.priority);
  if (mode === "standby") {
    return { costs: Object.keys(costs).length ? costs : null, crew_priority: priority };
  }
  const schedule = {
    interval: numOrNull(s.interval),
    duration: s.durationModel && isBlank(s.duration) ? s.durationModel : numOrNull(s.duration),
    cost: costValue(s.cost),
  };
  const group = s.kind !== "inspection" && s.group.trim() ? s.group.trim() : null;
  const preventive = { policy: s.policy, ...schedule };
  if (s.policy === "condition") {
    preventive.threshold = numOrNull(s.threshold);
    const ic = costValue(s.inspectionCost);
    if (ic != null) preventive.inspection_cost = ic;
  } else if (s.policy === "age" && group && !isBlank(s.opportunity)) {
    preventive.opportunity = numOrNull(s.opportunity);
  }
  const inspection = { ...schedule };
  if (!isBlank(s.offset) && Number(s.offset) > 0) inspection.offset = numOrNull(s.offset);
  if (partialCoverage(s)) {
    inspection.coverage = numOrNull(s.coverage);
    inspection.full_test = numOrNull(s.fullTest);
  }
  return {
    costs: Object.keys(costs).length ? costs : null,
    preventive: s.kind === "preventive" ? preventive : null,
    inspection: s.kind === "inspection" ? inspection : null,
    maintenance_group: group,
    crew_priority: priority,
    // The link means nothing once the schedule it filled is gone.
    rcm_source: s.rcm && s.rcm.target === s.kind ? s.rcm : null,
  };
}

function problems(s, mode = "component") {
  const out = [];
  for (const c of COSTS) {
    const p = costProblem(s.costs[c.key], c.label);
    if (p) out.push(p);
  }
  if (!isBlank(s.priority) && !Number.isFinite(Number(s.priority))) out.push("The crew priority must be a number.");
  if (mode === "standby") return out;
  if (s.kind !== "none") {
    const condition = s.kind === "preventive" && s.policy === "condition";
    const what = s.kind === "inspection" ? "test" : condition ? "inspection" : "replacement";
    if (!positive(s.interval)) out.push(`Set the ${what} interval (a positive number).`);
    if (!nonNeg(s.duration)) out.push(`The ${condition ? "replacement" : what} duration must be a non-negative number.`);
    const p = costProblem(s.cost, `The ${condition ? "replacement" : what} cost`);
    if (p) out.push(p);
  }
  if (s.kind === "preventive" && s.policy === "condition") {
    if (!prob(s.threshold)) out.push("Set the replacement threshold: a probability from 0 to 1 (e.g. 0.05).");
    const p = costProblem(s.inspectionCost, "The inspection cost");
    if (p) out.push(p);
  }
  if (s.kind === "preventive" && s.policy === "age" && s.group.trim() && !isBlank(s.opportunity)) {
    if (!nonNeg(s.opportunity) || (positive(s.interval) && Number(s.opportunity) > Number(s.interval))) {
      out.push("The early-renewal age must be from 0 to the replacement interval.");
    }
  }
  if (s.kind === "inspection") {
    if (!nonNeg(s.offset) || (positive(s.interval) && Number(s.offset) >= Number(s.interval))) {
      out.push("The first test must fall within the first interval (0 to less than the interval).");
    }
    if (!isBlank(s.coverage) && !prob(s.coverage)) out.push("The coverage must be a fraction from 0 to 1.");
    if (partialCoverage(s)) {
      const ratio = Number(s.fullTest) / Number(s.interval);
      if (!positive(s.fullTest)) out.push("A test that misses failures needs a full-test interval.");
      else if (positive(s.interval) && (Math.round(ratio) < 1 || Math.abs(ratio - Math.round(ratio)) > 1e-9 * ratio)) {
        out.push("The full-test interval must be a whole multiple of the test interval.");
      }
    }
  }
  return out;
}

// Apply a patch from the dialog to a node's data (null removes a key).
export function applyBlockExtras(data, extras) {
  if (!extras) return data;
  const out = { ...data };
  for (const [k, v] of Object.entries(extras)) {
    if (v == null || v === false) delete out[k];
    else out[k] = v;
  }
  return out;
}

function Field({ label, hint, value, onChange, title, filled, min = "0", max }) {
  return (
    <label className={"param-field rbd-cost-field" + (filled ? " rbd-filled" : "")} title={title}>
      <span>{label}</span>
      <input type="number" step="any" min={min} max={max} value={value} placeholder="—" aria-label={label}
             onChange={(e) => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

function TextField({ label, hint, value, onChange, title, list }) {
  return (
    <label className="param-field rbd-cost-field" title={title}>
      <span>{label}</span>
      <input type="text" value={value} placeholder="—" list={list} aria-label={label}
             onChange={(e) => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

const POLICIES = [
  ["age", "Age replacement"],
  ["block", "Block replacement"],
  ["condition", "Condition-based"],
];
const POLICY_HINTS = {
  age: "Replaced as new once it reaches the interval's age; a failure restarts the clock.",
  block: "Replaced at every multiple of the interval, whatever its age (skipped while it's down).",
  condition:
    "Inspected every interval while running (in no time), and replaced when its chance of failing before " +
    "the next inspection is above the threshold. Figures are numerical, not simulated.",
};

// A cost that may be a single value or a min–max range (drawn uniformly).
function CostField({ label, hint, cost, onChange, title, filled }) {
  const mean = cost.range && !costProblem(cost, label) && !costBlank(cost)
    ? (Number(cost.min) + Number(cost.max)) / 2 : null;
  return (
    <div className={"param-field rbd-cost-field" + (filled ? " rbd-filled" : "")} title={title}>
      <span className="rbd-cost-label">
        {label}
        <button type="button" className="rbd-range-toggle" onClick={() => onChange(toggleRange(cost))}
                title={cost.range ? "Enter a single amount" : "Enter a range (min–max): drawn uniformly at each action"}>
          {cost.range ? "single" : "range"}
        </button>
      </span>
      {cost.range ? (
        <span className="rbd-range-inputs">
          <input type="number" step="any" min="0" value={cost.min} placeholder="min" aria-label={`${label} minimum`}
                 onChange={(e) => onChange({ ...cost, min: e.target.value })} />
          <span aria-hidden="true">–</span>
          <input type="number" step="any" min="0" value={cost.max} placeholder="max" aria-label={`${label} maximum`}
                 onChange={(e) => onChange({ ...cost, max: e.target.value })} />
        </span>
      ) : (
        <input type="number" step="any" min="0" value={cost.value} placeholder="—" aria-label={label}
               onChange={(e) => onChange({ ...cost, value: e.target.value })} />
      )}
      {(hint || mean != null) && (
        <small>{[hint, mean != null ? `uniform, mean ${fmt(mean)}` : null].filter(Boolean).join(" · ")}</small>
      )}
    </div>
  );
}

const TARGET_LABEL = { preventive: "Scheduled replacement", inspection: "Proof test" };

// What an RCM task fills, in words: "every 580 h · age replacement · cost 200".
function filledText(fill, unit, sources = {}, analysis) {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const parts = [`every ${fmt(fill.interval)}${u}${sources.interval === "analysis" ? " (from its analysis)" : ""}`];
  if (fill.policy) parts.push(`${fill.policy} replacement`);
  if (fill.cost != null) parts.push(`cost ${fmt(fill.cost)}${analysis ? ` (from “${analysis}”)` : ""}`);
  return parts.join(" · ");
}

// Pick an RCM study, then one of its tasks, to fill the block's schedule.
function RcmPicker({ unit, onPick, onClose }) {
  const [studies, setStudies] = useState(null);
  const [studyId, setStudyId] = useState("");
  const [tasks, setTasks] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let live = true;
    listRcmStudies()
      .then((r) => live && setStudies(r.studies || []))
      .catch((e) => live && setError(e.message || "Couldn't load your RCM studies."));
    return () => { live = false; };
  }, []);

  const choose = (id) => {
    setStudyId(id);
    setTasks(null);
    setError(null);
    if (!id) return;
    setLoading(true);
    getRcmMaintenanceTasks(id, unit)
      .then(setTasks)
      .catch((e) => setError(e.message || "Couldn't load the study's tasks."))
      .finally(() => setLoading(false));
  };

  return (
    <div className="rbd-rcm-picker">
      <div className="rbd-rcm-picker-head">
        <strong>Fill from an RCM study</strong>
        <button type="button" className="link" onClick={onClose}>Cancel</button>
      </div>
      {studies && studies.length === 0 ? (
        <p className="hint">No RCM studies yet — record failure modes and their tasks under RCM, then fill blocks from them.</p>
      ) : (
        <select value={studyId} onChange={(e) => choose(e.target.value)} disabled={!studies} aria-label="RCM study">
          <option value="">{studies ? "Choose a study…" : "Loading studies…"}</option>
          {(studies || []).map((st) => (
            <option key={st.id} value={st.id}>
              {st.name}{st.shared_by ? ` — shared by ${st.shared_by}` : ""}
            </option>
          ))}
        </select>
      )}
      {loading && <p className="hint">Loading tasks…</p>}
      {error && <p className="rbd-costs-errors">{error}</p>}
      {tasks && (
        tasks.tasks.length === 0 ? (
          <p className="hint">This study has no failure modes yet.</p>
        ) : (
          <ul className="rbd-rcm-tasks">
            {tasks.tasks.map((t) => (
              <li key={t.mode_id} className={t.target ? "ok" : "no"}>
                <div className="rbd-rcm-task-text">
                  <div className="rbd-rcm-mode">{t.mode}</div>
                  <div className="muted">
                    {[t.outcome_label || "No task decided", t.task].filter(Boolean).join(" · ")}
                  </div>
                  {t.target ? (
                    <div className="rbd-rcm-fills">
                      <b>{TARGET_LABEL[t.target]}</b> {filledText(t.fill, unit, t.sources, t.analysis_name)}
                    </div>
                  ) : (
                    <div className="rbd-rcm-reason">{t.reason}</div>
                  )}
                </div>
                {t.target && (
                  <button type="button" className="secondary rbd-rcm-use"
                          onClick={() => onPick(tasks, t)}>
                    Use
                  </button>
                )}
              </li>
            ))}
          </ul>
        )
      )}
      <p className="hint">
        A task carries its interval (and a replacement task's linked analysis its cost); durations and the other
        costs stay as you set them.
      </p>
    </div>
  );
}

// The block dialog's costs and maintenance (#314): one shared state, drawn as
// separate sections (Proof test / Maintenance, Costs, the crew priority) so
// the dialog can order and fold them. ``useBlockExtras`` reports
// {extras, valid} through onChange; ``mode="standby"``: a standby group,
// which takes only costs and a priority.
export function useBlockExtras(initial, onChange, mode = "component") {
  const [s, setS] = useState(() => initialState(initial));
  const update = (patch) => {
    const next = { ...s, ...patch };
    setS(next);
    onChange?.({ extras: toExtras(next, mode), valid: problems(next, mode).length === 0 });
  };
  return { s, update, errs: problems(s, mode), mode };
}

// What's set, in words, for a folded section's summary.
export function costsSummary({ s }) {
  const set = COSTS.filter((c) => !costBlank(s.costs[c.key])).map((c) => c.label.toLowerCase());
  return set.length ? set.join(", ") : "optional";
}
export function maintenanceSummary({ s }, unit = "") {
  const u = unit ? ` ${unitInText(unit)}` : "";
  const condition = s.kind === "preventive" && s.policy === "condition";
  const what = s.kind === "inspection" ? "proof test" : condition ? "condition-based" : s.kind === "preventive" ? "scheduled replacement" : null;
  const parts = [what && positive(s.interval) ? `${what} every ${fmt(s.interval)}${u}` : what];
  if (s.kind !== "inspection" && s.group.trim()) parts.push(`group “${s.group.trim()}”`);
  return parts.filter(Boolean).join(", ") || "none";
}

// The block's costs (all optional; per-failure costs can be a range).
export function CostFields({ ctl, unit = "" }) {
  const { s, update } = ctl;
  const u = unit ? unitInText(unit).replace(/s$/, "") : "time unit";
  const setCost = (key, v) => update({ costs: { ...s.costs, [key]: v } });
  return (
    <>
      <p className="hint">In your currency, all optional. A per-failure cost can be a range.</p>
      <div className="param-fields">
        {COSTS.map((c) =>
          c.ranged ? (
            <CostField key={c.key} label={c.label} hint={c.per} title={c.help}
                       cost={s.costs[c.key]} onChange={(v) => setCost(c.key, v)} />
          ) : (
            <Field key={c.key} label={c.label} hint={c.per.replace("{u}", u)} title={c.help}
                   value={s.costs[c.key].value} onChange={(v) => setCost(c.key, { ...s.costs[c.key], value: v })} />
          )
        )}
      </div>
    </>
  );
}

// The block's place in the repair-crew queue (a diagram with limited crews).
export function PriorityField({ ctl }) {
  const { s, update } = ctl;
  return (
    <div className="param-fields">
      <Field label="Repair-crew priority" hint="higher is repaired first · blank = 0" min={undefined}
             title="When every repair crew is busy, waiting jobs are taken highest priority first, then in the order they fell due."
             value={s.priority} onChange={(v) => update({ priority: v })} />
    </div>
  );
}

// Scheduled replacement or proof tests, and the maintenance group.
export function MaintenanceFields({ ctl, unit = "", groups = [] }) {
  const { s, update } = ctl;
  const [picking, setPicking] = useState(false);
  const condition = s.kind === "preventive" && s.policy === "condition";
  const what = s.kind === "preventive" ? (condition ? "inspection" : "replacement") : "test";

  const pick = (study, task) => {
    const fill = task.fill || {};
    update({
      kind: task.target,
      ...(fill.policy ? { policy: fill.policy } : {}),
      interval: str(fill.interval),
      ...(fill.cost != null ? { cost: costState(fill.cost) } : {}),
      rcm: {
        study_id: study.study_id,
        study: study.study,
        mode_id: task.mode_id,
        mode: task.mode,
        target: task.target,
        filled: fill,
        sources: task.sources || {},
        ...(task.analysis_name ? { analysis: task.analysis_name } : {}),
        filled_at: new Date().toISOString().slice(0, 10),
      },
    });
    setPicking(false);
  };
  const link = s.rcm && s.rcm.target === s.kind ? s.rcm : null;
  const filled = link?.filled || {};
  const same = (a, b) => !isBlank(a) && b != null && Number(a) === Number(b);
  const intervalFilled = link && same(s.interval, filled.interval);
  const costFilled = link && filled.cost != null && !s.cost.range && same(s.cost.value, filled.cost);
  const edited = link && (!intervalFilled || (filled.cost != null && !costFilled)
                          || (filled.policy && filled.policy !== s.policy));

  return (
    <>
      <div className="rbd-maint-head">
        <SegmentedControl
          label="Maintenance"
          value={s.kind}
          onChange={(kind) => update({ kind })}
          options={KINDS.map((k) => ({ value: k.id, label: k.label }))}
        />
        {!picking && (
          <button type="button" className="link" onClick={() => setPicking(true)}>
            Fill from RCM study…
          </button>
        )}
      </div>
      {picking && <RcmPicker unit={unit} onPick={pick} onClose={() => setPicking(false)} />}
      {link && (
        <div className="rbd-rcm-source">
          <div>
            From RCM study <b>{link.study}</b> — {link.mode}: {filledText(filled, unit, link.sources, link.analysis)}.
            {edited && <span className="rbd-rcm-edited"> Edited since.</span>}
          </div>
          <div className="muted">
            Not kept in sync: later changes to the study don't update this block.{" "}
            <button type="button" className="link" onClick={() => update({ rcm: null })}>Unlink</button>
          </div>
        </div>
      )}
      {s.kind === "preventive" && (
        <>
          <SegmentedControl
            label="Replacement policy"
            className="rbd-costs-policy"
            value={s.policy}
            onChange={(policy) => update({ policy })}
            options={POLICIES.map(([id, label]) => ({ value: id, label }))}
          />
          <p className="hint">{POLICY_HINTS[s.policy] || POLICY_HINTS.age}</p>
        </>
      )}
      {s.kind === "inspection" && (
        <p className="hint">
          A failure stays hidden — the block is down but nobody knows — until the next proof test
          finds it; its repair starts then. Any life distribution; exact figures need instant tests
          and repairs, otherwise they're simulated.
        </p>
      )}
      {s.kind !== "none" && (
        <div className="param-fields">
          <Field label={`${what === "test" ? "Test" : what === "inspection" ? "Inspect" : "Replace"} every`}
                 hint={unit || "time"}
                 value={s.interval} onChange={(v) => update({ interval: v })} filled={intervalFilled} />
          {condition && (
            <Field label="Replace above" hint="P(fails before next inspection), e.g. 0.05" max="1"
                   title="Replaced at an inspection when its chance of failing before the next one, given its age, is above this."
                   value={s.threshold} onChange={(v) => update({ threshold: v })} />
          )}
          <Field label="Takes" hint={s.durationModel && isBlank(s.duration) ? "a distribution (set elsewhere)" : `${unit || "time"} · blank = instant`}
                 title={`How long the block is off-line for each ${condition ? "replacement" : what} (a planned outage).`}
                 value={s.duration} onChange={(v) => update({ duration: v })} />
          <CostField label={`Cost per ${condition ? "replacement" : what}`} hint="optional" cost={s.cost}
                     onChange={(v) => update({ cost: v })} filled={costFilled} />
          {condition && (
            <CostField label="Cost per inspection" hint="optional" cost={s.inspectionCost}
                       onChange={(v) => update({ inspectionCost: v })} />
          )}
        </div>
      )}
      {s.kind === "inspection" && (
        <div className="param-fields">
          <Field label="First test at" hint={`${unit || "time"} · stagger redundant channels`}
                 title="When the first proof test falls (0 to less than the interval). Testing redundant channels at different times lowers the PFDavg."
                 value={s.offset} onChange={(v) => update({ offset: v })} />
          <Field label="Coverage" hint="share of failures a test finds · blank = all" max="1"
                 title="An imperfect proof test finds only this fraction of failures; the rest stay hidden until a full test."
                 value={s.coverage} onChange={(v) => update({ coverage: v })} />
          {partialCoverage(s) && (
            <Field label="Full test every" hint={`${unit || "time"} · a multiple of the test interval`}
                   title="A full proof test (e.g. at a turnaround) finds every failure."
                   value={s.fullTest} onChange={(v) => update({ fullTest: v })} />
          )}
        </div>
      )}
      {s.kind !== "inspection" && (
        <div className="param-fields">
          <TextField label="Maintenance group" hint="blocks in a group share a set-up cost" list="rbd-maint-groups"
                     title="Blocks maintained together: each stop of the group (a failure or replacement of a member) is charged the group's set-up cost once. Set the cost under Crews and groups."
                     value={s.group} onChange={(v) => update({ group: v })} />
          {s.kind === "preventive" && s.policy === "age" && s.group.trim() && (
            <Field label="Renew early from age" hint={`${unit || "time"} · at a stop of its group`}
                   title="Opportunistic maintenance: when its group stops, it is renewed too if at least this old (0 to the interval)."
                   value={s.opportunity} onChange={(v) => update({ opportunity: v })} />
          )}
          <datalist id="rbd-maint-groups">
            {groups.map((g) => <option value={g} key={g} />)}
          </datalist>
        </div>
      )}
    </>
  );
}

export function ExtrasErrors({ ctl }) {
  if (!ctl.errs.length) return null;
  return (
    <ul className="rbd-costs-errors">
      {ctl.errs.map((e) => <li key={e}>{e}</li>)}
    </ul>
  );
}

// A standby group's "Costs" section: costs and (limited crews) its priority,
// folded unless something is set.
export function BlockCostSection({ initial, onChange, unit = "", crews = false, mode = "standby" }) {
  const ctl = useBlockExtras(initial, onChange, mode);
  const [open, setOpen] = useState(
    () => !!(Object.keys(initial?.costs || {}).length || initial?.crew_priority != null)
  );
  return (
    <details className="rbd-dlg-fold" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        Costs <span className="muted"> · {costsSummary(ctl)}</span>
      </summary>
      <div className="rbd-dlg-fold-body">
        <CostFields ctl={ctl} unit={unit} />
        {crews && <PriorityField ctl={ctl} />}
        <ExtrasErrors ctl={ctl} />
      </div>
    </details>
  );
}

// A repairable block's maintenance as chips (#314): one neutral style, an icon
// each — proof test ⏱, scheduled replacement ↻, condition-based ◎, group ⧉.
export function maintenanceChips(data, unit) {
  const u = unitAbbr(unit) ? ` ${unitAbbr(unit)}` : "";
  const out = [];
  const from = data.rcm_source?.study ? ` · from RCM study “${data.rcm_source.study}”` : "";
  const pm = data.preventive;
  const test = data.inspection;
  const cbm = pm?.policy === "condition";
  if (pm) {
    out.push({
      key: "pm",
      text: `${cbm ? "◎" : "↻"} ${fmt(pm.interval)}${u}`,
      title: cbm
        ? `Inspected every ${fmt(pm.interval)}${u}, replaced when P(failing before the next inspection) > ${pm.threshold}${from}`
        : `Scheduled ${pm.policy === "block" ? "block" : "age"} replacement every ${fmt(pm.interval)}${u}`
          + (pm.opportunity != null ? `, renewed early from age ${fmt(pm.opportunity)}${u} at a group stop` : "") + from,
    });
  }
  if (test) {
    const notes = [
      test.offset ? `first test at ${fmt(test.offset)}${u}` : null,
      test.coverage != null && Number(test.coverage) < 1
        ? `${Math.round(Number(test.coverage) * 100)}% coverage, full test every ${fmt(test.full_test)}${u}` : null,
    ].filter(Boolean);
    out.push({
      key: "test",
      text: `⏱ ${fmt(test.interval)}${u}${notes.length ? " *" : ""}`,
      title: `Hidden failures, proof-tested every ${fmt(test.interval)}${u}${notes.length ? ` (${notes.join("; ")})` : ""}${from}`,
    });
  }
  if (data.maintenance_group) {
    out.push({
      key: "group",
      text: `⧉ ${data.maintenance_group}`,
      title: `Maintenance group “${data.maintenance_group}”: shares its set-up cost`,
    });
  }
  return out;
}
