// The Maintenance plan of a repairable RBD: one row per block, saying what planned work is done to
// it, how often, how long it takes it off-line, what it costs, how much it restores, and its duty.
// The pane (components/RbdMaintenancePlan.jsx) is the one place this is edited; the block dialog
// shows a summary. Pure functions here, so the pane's rules are tested on their own.
//
// It edits the node data RePyability already takes (backend/services/rbd_maintenance.py):
//   data.preventive = {policy: "age"|"block"|"condition", interval, duration, cost,
//                      threshold, inspection_cost, opportunity, operating_interval}
//   data.inspection = {interval, duration, cost, offset, coverage, full_test}   (proof tests)
//   data.maintenance_group, data.crew_priority
//   data.duty       = the share of the time it runs, in (0, 1]: its life is in operating time
// A replacement may be given in operating time (operating_interval, "every 500 running hours"):
// its interval on the diagram's clock is that over the duty, and with no duty it's refused with a
// plain note (the backend does the same, and is the judge).
import { hoursPerUnit, unitAbbr } from "./components/rbdModelText.js";

// What the installed library takes, when the server doesn't say (a tree plan carries its own
// `supports`, found by capability). Restoration and shutdowns saved in the tree before the library
// takes them are shown with PENDING_WORDS and calculated with what it can (as new, no shutdowns).
export const PLAN_SUPPORTS = Object.freeze({ restoration: ["as_new"], shutdowns: false });
export const PENDING_WORDS = "Saved — used in results once the next library update is in.";
export const RESTORATIONS = { as_new: "As new", kijima1: "Kijima I", kijima2: "Kijima II" };

export const TASKS = [
  { id: "none", label: "Run to failure", help: "No planned work: it's repaired when it fails." },
  { id: "age", label: "Replace at age", help: "Replaced as new when it reaches this age (the time since it was last replaced); a failure restarts the clock. The work orders count the same way." },
  { id: "block", label: "Replace at fixed times", help: "Replaced at every multiple of the interval, whatever its age (skipped while it's down): a package on fixed dates." },
  { id: "condition", label: "Inspect on condition", help: "Inspected every interval while running (in no time); replaced when its chance of failing before the next inspection is above the threshold." },
  { id: "test", label: "Proof test", help: "Its failures are hidden until a proof test finds them; the repair starts then." },
];
const TASK_IDS = new Set(TASKS.map((t) => t.id));

const isBlank = (v) => v == null || String(v).trim() === "";
const num = (v) => (isBlank(v) ? null : Number(v));
const finite = (v) => v != null && Number.isFinite(Number(v));
export const fmt = (v) => (finite(v) ? Number(Number(v).toPrecision(4)).toLocaleString("en-GB") : "?");

// The block's task, from its data.
export function taskOf(data = {}) {
  if (data.inspection) return "test";
  if (data.preventive) return TASK_IDS.has(data.preventive.policy) ? data.preventive.policy : "age";
  return "none";
}
export const taskLabel = (id) => TASKS.find((t) => t.id === id)?.label || id;

// The task's schedule object (preventive or inspection), or null.
export const schedule = (data = {}) => data.inspection || data.preventive || null;

// The blocks the plan lists: component blocks with their own model (a repeated block is the same
// physical unit drawn again, so its plan is its original's). Standby groups take no planned work.
export function planRows(nodes = []) {
  return nodes
    .filter((n) => n.type === "component" && !n.data?.repeat_of)
    .map((n) => ({ id: n.id, label: n.data?.label || n.id, data: n.data || {}, task: taskOf(n.data) }));
}

// The table's columns: the crew priority only when crews are limited, restoration always (it
// says "As new", which is what every task does today).
export function planColumns({ crews = false } = {}) {
  return ["block", "duty", "task", "every", "takes", "cost", "restores", "group", ...(crews ? ["crew"] : [])];
}

// ---------------------------------------------------------------------------------------------
// Runs: the share of the time a block runs ("Runs 25% of the time"; data.duty, the API's name.
// "Duty" is kept for duty / standby pairs.)
// ---------------------------------------------------------------------------------------------
// Typed as a percentage ("25", "25%"); blank = it runs all the time.
export function parseDuty(text) {
  const t = String(text ?? "").trim().replace(/%$/, "").trim();
  if (!t) return { value: null, error: null };
  const x = Number(t);
  if (!Number.isFinite(x) || x <= 0 || x > 100) {
    return { value: null, error: "Runs is the share of the time it runs: more than 0% and at most 100%." };
  }
  return { value: Number((x / 100).toPrecision(12)), error: null };
}
export const dutyText = (duty) => (finite(duty) ? String(Number((Number(duty) * 100).toPrecision(6))) : "");
export const hasDuty = (data = {}) => finite(data.duty) && Number(data.duty) > 0 && Number(data.duty) <= 1;

// "Runs 25% of the time · about 6 h a day" (a day only makes sense on a calendar clock).
export function dutyWords(duty, unit = "") {
  if (!finite(duty) || Number(duty) >= 1) return "Runs all the time";
  const pct = `${fmt(Number(duty) * 100)}%`;
  const perUnit = hoursPerUnit(unit);
  return perUnit != null ? `Runs ${pct} of the time · about ${fmt(Number(duty) * 24)} h a day` : `Runs ${pct} of the time`;
}

// Operating time only makes sense when the diagram's clock is a time (not cycles or km).
export const operatingAllowed = (unit) => hoursPerUnit(unit) != null;
export const toCalendar = (operating, duty) => (finite(operating) && finite(duty) && duty > 0 ? operating / duty : null);
export const toOperating = (calendar, duty) => (finite(calendar) && finite(duty) ? calendar * duty : null);
export const intervalBasis = (data = {}) => (data.preventive && !isBlank(data.preventive.operating_interval) ? "operating" : "calendar");

// ---------------------------------------------------------------------------------------------
// Costs: a number or a min–max range ("300–700"), drawn uniformly at each action
// ---------------------------------------------------------------------------------------------
export function parseCost(text) {
  const t = String(text ?? "").trim().replace(/,/g, "");
  if (!t) return { value: null, error: null };
  const m = t.match(/^(\d*\.?\d+(?:e[+-]?\d+)?)\s*(?:-|–|—|to)\s*(\d*\.?\d+(?:e[+-]?\d+)?)$/i);
  if (m) {
    const lo = Number(m[1]);
    const hi = Number(m[2]);
    if (lo > hi) return { value: null, error: "The range's low end is above its high end." };
    return { value: lo === hi ? lo : { min: lo, max: hi }, error: null };
  }
  const x = Number(t);
  if (!Number.isFinite(x) || x < 0) return { value: null, error: "A cost is a number, or a range like 300–700." };
  return { value: x, error: null };
}
export function costText(v) {
  if (v == null || v === "") return "";
  if (typeof v === "object") return `${v.min ?? ""}–${v.max ?? ""}`;
  return String(v);
}

// A plain number field: blank, or a non-negative (or positive) number.
// A chance or a share typed as a percentage ("5", "5%") and kept as a fraction (0.05), as the
// diagram stores it; and back for the box. Blank is none.
export const THRESHOLD_NEEDED = "Set the replacement threshold: the chance of failing before the next inspection, as a % (e.g. 5%).";
export function parsePercent(text) {
  const t = String(text ?? "").trim().replace(/%$/, "").trim();
  if (!t) return { value: null, error: null };
  const x = Number(t);
  if (!Number.isFinite(x) || x < 0 || x > 100) return { value: null, error: "Enter a percentage from 0 to 100." };
  return { value: Number((x / 100).toPrecision(12)), error: null };
}
export const percentText = (v) => (finite(v) ? String(Number((Number(v) * 100).toPrecision(6))) : "");

export function parseNumber(text, { positive = false, max = null } = {}) {
  const t = String(text ?? "").trim();
  if (!t) return { value: null, error: null };
  const x = Number(t);
  if (!Number.isFinite(x) || x < 0 || (positive && x === 0) || (max != null && x > max)) {
    return { value: null, error: positive ? "Enter a positive number." : max != null ? `Enter a number from 0 to ${max}.` : "Enter a number, 0 or more." };
  }
  return { value: x, error: null };
}

// ---------------------------------------------------------------------------------------------
// Edits: each returns new node data (nothing is changed in place)
// ---------------------------------------------------------------------------------------------
const drop = (obj, ...keys) => {
  const out = { ...obj };
  for (const k of keys) delete out[k];
  return out;
};
const clean = (obj) => Object.fromEntries(Object.entries(obj).filter(([, v]) => v != null && v !== ""));

// Change the task, keeping the interval, duration and cost already typed. A proof-tested block
// can't be in a maintenance group (nobody knows it has failed when the group stops), so its group
// goes; a test's extras (first test, coverage) and a replacement's (threshold, early renewal) stay
// with their kind.
export function setTask(data, task) {
  const base = drop(data, "preventive", "inspection");
  if (task === "none") return base;
  const was = schedule(data) || {};
  const common = clean({ interval: was.interval, duration: was.duration, cost: was.cost });
  if (task === "test") {
    const kept = data.inspection ? data.inspection : common;
    return drop({ ...base, inspection: kept }, "maintenance_group");
  }
  const prev = data.preventive || {};
  const pm = clean({
    ...common,
    policy: task,
    operating_interval: prev.operating_interval,
    threshold: task === "condition" ? prev.threshold : null,
    inspection_cost: task === "condition" ? prev.inspection_cost : null,
    opportunity: task === "age" ? prev.opportunity : null,
  });
  return { ...base, preventive: pm };
}

// Set a field of the block's schedule (duration, cost, threshold, ...); null removes it.
export function setScheduleField(data, key, value) {
  const which = data.inspection ? "inspection" : data.preventive ? "preventive" : null;
  if (!which) return data;
  const next = { ...data[which], [key]: value };
  if (value == null) delete next[key];
  return { ...data, [which]: next };
}

// Set the interval, on the calendar or in operating time. In operating time the calendar interval
// follows from the duty; with Runs blank the block runs all the time, so it's the same number.
export function setInterval(data, value, basis = "calendar") {
  const which = data.inspection ? "inspection" : data.preventive ? "preventive" : null;
  if (!which) return data;
  if (which === "inspection" || basis === "calendar") {
    const next = drop({ ...data[which], interval: value }, "operating_interval");
    if (value == null) delete next.interval;
    return { ...data, [which]: next };
  }
  const calendar = hasDuty(data) ? toCalendar(value, Number(data.duty)) : value;
  const next = { ...data.preventive, operating_interval: value, interval: calendar };
  if (value == null) delete next.operating_interval;
  if (calendar == null) delete next.interval;
  return { ...data, preventive: next };
}

// Switch the interval's basis, keeping the same schedule where the duty allows.
export function setIntervalBasis(data, basis) {
  const pm = data.preventive;
  if (!pm || basis === intervalBasis(data)) return data;
  if (basis === "operating") {
    const operating = hasDuty(data) ? toOperating(pm.interval, Number(data.duty)) : pm.interval;
    return setInterval(data, operating != null ? Number(operating.toPrecision(12)) : null, "operating");
  }
  return setInterval(data, pm.interval ?? null, "calendar");
}

// Set the duty (a fraction, or null to run all the time); a replacement given in operating time
// moves with it.
export function setDuty(data, duty) {
  let out = duty == null || Number(duty) >= 1 ? drop(data, "duty") : { ...data, duty: Number(duty) };
  if (out.preventive && !isBlank(out.preventive.operating_interval)) {
    out = setInterval(out, Number(out.preventive.operating_interval), "operating");
  }
  return out;
}

export function setGroup(data, name) {
  const g = String(name ?? "").trim();
  return g ? { ...data, maintenance_group: g } : drop(data, "maintenance_group");
}
export function setCrewPriority(data, value) {
  return value == null ? drop(data, "crew_priority") : { ...data, crew_priority: value };
}

// ---------------------------------------------------------------------------------------------
// What's wrong with a row, in plain words (the backend checks the same before it calculates)
// ---------------------------------------------------------------------------------------------
export function rowProblems(data = {}, unit = "") {
  const out = [];
  const task = taskOf(data);
  if (!isBlank(data.duty) && !hasDuty(data)) out.push("Runs is the share of the time it runs: more than 0% and at most 100%.");
  if (task === "none") return out;
  const s = schedule(data) || {};
  const operating = intervalBasis(data) === "operating";
  if (operating) {
    // Runs blank is "all the time": running time is calendar time, nothing more to set.
    if (!finite(s.operating_interval) || Number(s.operating_interval) <= 0) out.push("Set how often, in running time.");
    else if (!operatingAllowed(unit)) out.push("Running time needs the diagram in a time unit (hours, days, …).");
  } else if (!finite(s.interval) || Number(s.interval) <= 0) {
    out.push(task === "condition" ? "Set how often it's inspected." : task === "test" ? "Set how often it's tested." : "Set how often it's replaced.");
  }
  const every = Number(s.interval);
  if (task === "condition") {
    const th = Number(s.threshold);
    if (!finite(s.threshold) || th < 0 || th > 1) out.push(THRESHOLD_NEEDED);
  }
  if (task === "age" && !isBlank(s.opportunity)) {
    if (isBlank(data.maintenance_group)) out.push("Early renewal at a group stop needs a maintenance group.");
    else if (finite(every) && Number(s.opportunity) > every) out.push("The early-renewal age must be from 0 to the replacement interval.");
  }
  if (task === "test") {
    if (!isBlank(s.offset) && finite(every) && (Number(s.offset) < 0 || Number(s.offset) >= every)) {
      out.push("The first test must fall within the first interval (0 to less than the interval).");
    }
    if (finite(s.coverage) && Number(s.coverage) < 1) {
      const ratio = Number(s.full_test) / every;
      if (!finite(s.full_test) || Number(s.full_test) <= 0) out.push("A test that misses failures needs a full-test interval.");
      else if (finite(every) && (Math.round(ratio) < 1 || Math.abs(ratio - Math.round(ratio)) > 1e-9 * ratio)) {
        out.push("The full-test interval must be a whole multiple of the test interval.");
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------------------------
const unitSuffix = (unit) => (unitAbbr(unit) ? ` ${unitAbbr(unit)}` : "");

function durationWords(d, unit) {
  if (d == null || d === "" || d === "instant" || Number(d) === 0) return "no downtime";
  if (typeof d === "object") return "takes a modelled time";
  return `takes ${fmt(d)}${unitSuffix(unit)}`;
}

// "Replace at age every 4,380 h (2,190 running h), takes 8 h, as new". The block dialog's summary,
// and the canvas chip's title.
export function taskSummary(data = {}, unit = "") {
  const task = taskOf(data);
  if (task === "none") return "Run to failure";
  const s = schedule(data) || {};
  const u = unitSuffix(unit);
  const every = finite(s.interval) ? `every ${fmt(s.interval)}${u}` : "interval not set";
  const running = intervalBasis(data) === "operating" && finite(s.operating_interval)
    ? ` (${fmt(s.operating_interval)} running${u})` : "";
  const parts = [`${taskLabel(task)} ${every}${running}`, durationWords(s.duration, unit)];
  if (task !== "test") parts.push("as new");
  return parts.join(", ");
}

// The pane's one-line totals: how many blocks have planned work, and how many have a duty.
export function planCounts(rows) {
  return {
    blocks: rows.length,
    planned: rows.filter((r) => r.task !== "none").length,
    withDuty: rows.filter((r) => hasDuty(r.data) && Number(r.data.duty) < 1).length,
    problems: rows.filter((r) => rowProblems(r.data).length > 0).length,
  };
}
