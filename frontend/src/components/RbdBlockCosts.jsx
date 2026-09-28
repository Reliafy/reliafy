import { useState } from "react";

// A repairable block's costs and maintenance (#99, #100), edited in the block's
// model dialog, collapsed by default. Stored on the node as
//   data.costs      = {repair, replace, downtime, acquisition}   (numbers, optional)
//   data.preventive = {policy: "age"|"block", interval, duration, cost}
//   data.inspection = {interval, duration, cost}   (hidden failures, proof-tested)
//   data.instant_repair = true                      (no repair-time model needed)
// A duration of 0/blank is instant. A block has scheduled replacement or proof
// tests, not both (as in RePyability).

const COSTS = [
  { key: "repair", label: "Repair cost", per: "per failure", help: "Labour, call-out: charged at every failure." },
  { key: "replace", label: "Parts cost", per: "per failure", help: "The spare part or replacement unit, charged at every failure." },
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

function initialState(data = {}) {
  const sched = data.preventive || data.inspection || {};
  // A duration given as a distribution (e.g. by the assistant) is kept as is.
  const isModel = sched.duration != null && typeof sched.duration === "object";
  return {
    costs: Object.fromEntries(COSTS.map((c) => [c.key, str(data.costs?.[c.key])])),
    kind: data.preventive ? "preventive" : data.inspection ? "inspection" : "none",
    policy: data.preventive?.policy || "age",
    interval: str(sched.interval),
    duration: isModel ? "" : str(sched.duration),
    durationModel: isModel ? sched.duration : null,
    cost: str(sched.cost),
  };
}

// The node-data patch for the section's state: every key present, null to remove.
function toExtras(s) {
  const costs = {};
  for (const c of COSTS) if (!isBlank(s.costs[c.key])) costs[c.key] = Number(s.costs[c.key]);
  const schedule = {
    interval: numOrNull(s.interval),
    duration: s.durationModel && isBlank(s.duration) ? s.durationModel : numOrNull(s.duration),
    cost: numOrNull(s.cost),
  };
  return {
    costs: Object.keys(costs).length ? costs : null,
    preventive: s.kind === "preventive" ? { policy: s.policy, ...schedule } : null,
    inspection: s.kind === "inspection" ? schedule : null,
  };
}

function problems(s) {
  const out = [];
  for (const c of COSTS) if (!nonNeg(s.costs[c.key])) out.push(`${c.label} must be a non-negative number.`);
  if (s.kind !== "none") {
    const what = s.kind === "preventive" ? "replacement" : "test";
    if (!positive(s.interval)) out.push(`Set the ${what} interval (a positive number).`);
    if (!nonNeg(s.duration)) out.push(`The ${what} duration must be a non-negative number.`);
    if (!nonNeg(s.cost)) out.push(`The ${what} cost must be a non-negative number.`);
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

function Field({ label, hint, value, onChange, title }) {
  return (
    <label className="param-field rbd-cost-field" title={title}>
      <span>{label}</span>
      <input type="number" step="any" min="0" value={value} placeholder="—" onChange={(e) => onChange(e.target.value)} />
      {hint && <small>{hint}</small>}
    </label>
  );
}

// The "Cost & maintenance" section. Reports {extras, valid} through onChange.
export function BlockCostSection({ initial, onChange, unit = "" }) {
  const u = unit ? unit.replace(/s$/, "") : "time unit";
  const [s, setS] = useState(() => initialState(initial));
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
    ...COSTS.filter((c) => !isBlank(s.costs[c.key])).map((c) => c.label.toLowerCase()),
    ...(s.kind === "preventive" ? ["scheduled replacement"] : s.kind === "inspection" ? ["proof tests"] : []),
  ];
  const what = s.kind === "preventive" ? "replacement" : "test";

  return (
    <details className="rbd-costs-section" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        Cost &amp; maintenance
        <span className="muted"> · {set.length ? set.join(", ") : "optional"}</span>
      </summary>
      <div className="rbd-costs-body">
        <div className="rbd-costs-h">Costs <span className="muted">in your currency, all optional</span></div>
        <div className="param-fields">
          {COSTS.map((c) => (
            <Field key={c.key} label={c.label} hint={c.per.replace("{u}", u)} title={c.help}
                   value={s.costs[c.key]} onChange={(v) => setCost(c.key, v)} />
          ))}
        </div>

        <div className="rbd-costs-h">Maintenance</div>
        <div className="seg" role="radiogroup" aria-label="Maintenance">
          {KINDS.map((k) => (
            <button key={k.id} type="button" role="radio" aria-checked={s.kind === k.id}
                    className={"seg-btn" + (s.kind === k.id ? " active" : "")}
                    onClick={() => update({ kind: k.id })}>
              {k.label}
            </button>
          ))}
        </div>
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
                   value={s.interval} onChange={(v) => update({ interval: v })} />
            <Field label="Takes" hint={s.durationModel && isBlank(s.duration) ? "a distribution (set elsewhere)" : `${unit || "time"} · blank = instant`}
                   title={`How long the block is off-line for each ${what} (a planned outage).`}
                   value={s.duration} onChange={(v) => update({ duration: v })} />
            <Field label={`Cost per ${what}`} hint="optional" value={s.cost} onChange={(v) => update({ cost: v })} />
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
  const fmt = (v) => (Number.isFinite(Number(v)) ? Number(Number(v).toPrecision(4)).toLocaleString() : "?");
  if (!data.preventive && !data.inspection) return null;
  return (
    <div className="rbd-maint-chips">
      {data.preventive && (
        <span className="rbd-maint-chip pm"
              title={`Scheduled ${data.preventive.policy === "block" ? "block" : "age"} replacement every ${fmt(data.preventive.interval)}${u}`}>
          PM {fmt(data.preventive.interval)}{u}
        </span>
      )}
      {data.inspection && (
        <span className="rbd-maint-chip test"
              title={`Hidden failures, proof-tested every ${fmt(data.inspection.interval)}${u}`}>
          Proof test {fmt(data.inspection.interval)}{u}
        </span>
      )}
    </div>
  );
}
