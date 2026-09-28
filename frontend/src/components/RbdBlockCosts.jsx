import { useEffect, useState } from "react";
import { getRcmMaintenanceTasks, listRcmStudies } from "../api.js";

// A repairable block's costs and maintenance (#99, #100), edited in the block's
// model dialog, collapsed by default. Stored on the node as
//   data.costs      = {repair, replace, downtime, acquisition}   (numbers, optional)
//   data.preventive = {policy: "age"|"block", interval, duration, cost}
//   data.inspection = {interval, duration, cost}   (hidden failures, proof-tested)
//   data.instant_repair = true                      (no repair-time model needed)
//   data.rcm_source = {study_id, study, mode_id, mode, target, filled, ...}
//                     (the RCM study the schedule was filled from: display only)
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
  return {
    costs: Object.fromEntries(COSTS.map((c) => [c.key, costState(data.costs?.[c.key])])),
    kind: data.preventive ? "preventive" : data.inspection ? "inspection" : "none",
    policy: data.preventive?.policy || "age",
    interval: str(sched.interval),
    duration: isModel ? "" : str(sched.duration),
    durationModel: isModel ? sched.duration : null,
    cost: costState(sched.cost),
    rcm: data.rcm_source || null,
  };
}

// The node-data patch for the section's state: every key present, null to remove.
function toExtras(s) {
  const costs = {};
  for (const c of COSTS) if (!costBlank(s.costs[c.key])) costs[c.key] = costValue(s.costs[c.key]);
  const schedule = {
    interval: numOrNull(s.interval),
    duration: s.durationModel && isBlank(s.duration) ? s.durationModel : numOrNull(s.duration),
    cost: costValue(s.cost),
  };
  return {
    costs: Object.keys(costs).length ? costs : null,
    preventive: s.kind === "preventive" ? { policy: s.policy, ...schedule } : null,
    inspection: s.kind === "inspection" ? schedule : null,
    // The link means nothing once the schedule it filled is gone.
    rcm_source: s.rcm && s.rcm.target === s.kind ? s.rcm : null,
  };
}

function problems(s) {
  const out = [];
  for (const c of COSTS) {
    const p = costProblem(s.costs[c.key], c.label);
    if (p) out.push(p);
  }
  if (s.kind !== "none") {
    const what = s.kind === "preventive" ? "replacement" : "test";
    if (!positive(s.interval)) out.push(`Set the ${what} interval (a positive number).`);
    if (!nonNeg(s.duration)) out.push(`The ${what} duration must be a non-negative number.`);
    const p = costProblem(s.cost, `The ${what} cost`);
    if (p) out.push(p);
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

function Field({ label, hint, value, onChange, title, filled }) {
  return (
    <label className={"param-field rbd-cost-field" + (filled ? " rbd-filled" : "")} title={title}>
      <span>{label}</span>
      <input type="number" step="any" min="0" value={value} placeholder="—" onChange={(e) => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

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
  const u = unit ? ` ${unit}` : "";
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
        <button type="button" className="link-btn" onClick={onClose}>Cancel</button>
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

// The "Cost & maintenance" section. Reports {extras, valid} through onChange.
export function BlockCostSection({ initial, onChange, unit = "" }) {
  const u = unit ? unit.replace(/s$/, "") : "time unit";
  const [s, setS] = useState(() => initialState(initial));
  const [picking, setPicking] = useState(false);
  const [open, setOpen] = useState(
    () => !!(initial?.preventive || initial?.inspection || Object.keys(initial?.costs || {}).length)
  );
  const update = (patch) => {
    const next = { ...s, ...patch };
    setS(next);
    onChange?.({ extras: toExtras(next), valid: problems(next).length === 0 });
  };
  const setCost = (key, v) => update({ costs: { ...s.costs, [key]: v } });
  const errs = problems(s);
  const set = [
    ...COSTS.filter((c) => !costBlank(s.costs[c.key])).map((c) => c.label.toLowerCase()),
    ...(s.kind === "preventive" ? ["scheduled replacement"] : s.kind === "inspection" ? ["proof tests"] : []),
  ];
  const what = s.kind === "preventive" ? "replacement" : "test";

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
    <details className="rbd-costs-section" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        Cost &amp; maintenance
        <span className="muted"> · {set.length ? set.join(", ") : "optional"}</span>
      </summary>
      <div className="rbd-costs-body">
        <div className="rbd-costs-h">
          Costs <span className="muted">in your currency, all optional · per-failure costs can be a range</span>
        </div>
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

        <div className="rbd-costs-h rbd-costs-h-row">
          Maintenance
          {!picking && (
            <button type="button" className="link-btn" onClick={() => setPicking(true)}>
              Fill from RCM study…
            </button>
          )}
        </div>
        {picking && <RcmPicker unit={unit} onPick={pick} onClose={() => setPicking(false)} />}
        <div className="seg" role="radiogroup" aria-label="Maintenance">
          {KINDS.map((k) => (
            <button key={k.id} type="button" role="radio" aria-checked={s.kind === k.id}
                    className={"seg-btn" + (s.kind === k.id ? " active" : "")}
                    onClick={() => update({ kind: k.id })}>
              {k.label}
            </button>
          ))}
        </div>
        {link && (
          <div className="rbd-rcm-source">
            <div>
              From RCM study <b>{link.study}</b> — {link.mode}: {filledText(filled, unit, link.sources, link.analysis)}.
              {edited && <span className="rbd-rcm-edited"> Edited since.</span>}
            </div>
            <div className="muted">
              Not kept in sync: later changes to the study don't update this block.{" "}
              <button type="button" className="link-btn" onClick={() => update({ rcm: null })}>Unlink</button>
            </div>
          </div>
        )}
        {s.kind === "preventive" && (
          <>
            <div className="seg rbd-costs-policy" role="radiogroup" aria-label="Replacement policy">
              {[["age", "Age replacement"], ["block", "Block replacement"]].map(([id, label]) => (
                <button key={id} type="button" role="radio" aria-checked={s.policy === id}
                        className={"seg-btn" + (s.policy === id ? " active" : "")}
                        onClick={() => update({ policy: id })}>
                  {label}
                </button>
              ))}
            </div>
            <p className="hint">
              {s.policy === "age"
                ? "Replaced as new once it reaches the interval's age; a failure restarts the clock."
                : "Replaced at every multiple of the interval, whatever its age (skipped while it's down). Priced by simulation."}
            </p>
          </>
        )}
        {s.kind === "inspection" && (
          <p className="hint">
            A failure stays hidden — the block is down but nobody knows — until the next proof test
            finds it; its repair starts then. Exact figures need an exponential life and instant tests
            and repairs; otherwise they're simulated.
          </p>
        )}
        {s.kind !== "none" && (
          <div className="param-fields">
            <Field label={`${what === "test" ? "Test" : "Replace"} every`} hint={unit || "time"}
                   value={s.interval} onChange={(v) => update({ interval: v })} filled={intervalFilled} />
            <Field label="Takes" hint={s.durationModel && isBlank(s.duration) ? "a distribution (set elsewhere)" : `${unit || "time"} · blank = instant`}
                   title={`How long the block is off-line for each ${what} (a planned outage).`}
                   value={s.duration} onChange={(v) => update({ duration: v })} />
            <CostField label={`Cost per ${what}`} hint="optional" cost={s.cost}
                       onChange={(v) => update({ cost: v })} filled={costFilled} />
          </div>
        )}
        {errs.length > 0 && (
          <ul className="rbd-costs-errors">
            {errs.map((e) => <li key={e}>{e}</li>)}
          </ul>
        )}
      </div>
    </details>
  );
}

// Small chips on a repairable block: its maintenance at a glance.
const UNIT_ABBR = { hours: "h", hour: "h", days: "d", day: "d", years: "y", year: "y", minutes: "min", weeks: "wk" };

export function MaintenanceChips({ data, unit }) {
  const key = (unit || "").trim().toLowerCase();
  const u = key ? ` ${UNIT_ABBR[key] || key}` : "";
  if (!data.preventive && !data.inspection) return null;
  const from = data.rcm_source?.study ? ` · from RCM study “${data.rcm_source.study}”` : "";
  return (
    <div className="rbd-maint-chips">
      {data.preventive && (
        <span className="rbd-maint-chip pm"
              title={`Scheduled ${data.preventive.policy === "block" ? "block" : "age"} replacement every ${fmt(data.preventive.interval)}${u}${from}`}>
          PM {fmt(data.preventive.interval)}{u}
        </span>
      )}
      {data.inspection && (
        <span className="rbd-maint-chip test"
              title={`Hidden failures, proof-tested every ${fmt(data.inspection.interval)}${u}${from}`}>
          Proof test {fmt(data.inspection.interval)}{u}
        </span>
      )}
    </div>
  );
}
