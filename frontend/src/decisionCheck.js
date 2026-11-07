// What the decision dialog (components/DecisionModal.jsx) needs before Apply,
// checked as the server checks a decision (backend/services/rcm.py
// _clean_decision; with `limits`, the Explorer's own checks too:
// backend/maintenance/service.py decide_failure_mode), plus one rule of its
// own: a fixed-interval or failure-finding decision means nothing without an
// interval, so it needs one. On-condition doesn't: some on-condition
// decisions are covered by another task and carry only a note, so with no
// interval the dialog only says that no task will be made. Pure, tested in
// decisionCheck.test.js.

// The decisions that can't do without an interval.
export const NEEDS_INTERVAL = new Set(["fixed_interval", "failure_finding"]);

// The longest interval the Explorer schedules: 100 years on the calendar, or
// ten million units of use (hours, cycles, km).
const DAYS_PER = { days: 1, weeks: 7, months: 30.4375, years: 365.25 };
const MAX_DAYS = 100 * 365.25;
const MAX_USE = 1e7;
const MAX_NOTES = 4000;

const INTERVAL_NEEDED = {
  fixed_interval: "Give the interval: how often it's replaced or restored.",
  failure_finding: "Give the interval: how often the hidden function is checked.",
};

// ---- a combination of tasks -----------------------------------------------------
// RCM II's "combination of tasks": where no one task is good enough on its own
// (usually safety or environmental consequences), a decision holds two or more
// outcomes, a regular inspection plus a fixed-time replacement, each with a
// task of its own. The rules, as the server checks them
// (backend/maintenance/rcm_decisions.py): two or more of the scheduled
// outcomes, no outcome twice, or a redesign beside one scheduled task as the
// interim measure; run-to-failure and accept stand alone.

export const SCHEDULED = ["on_condition", "fixed_interval", "failure_finding"];
const COMBINES = [...SCHEDULED, "redesign"];

// Whether a list of outcomes may be one decision (one outcome always may).
export function combinationOk(outcomes) {
  if (outcomes.length < 2) return true;
  if (new Set(outcomes).size !== outcomes.length || outcomes.some((o) => !COMBINES.includes(o))) return false;
  const scheduled = outcomes.filter((o) => SCHEDULED.includes(o)).length;
  return outcomes.includes("redesign") ? scheduled === 1 : scheduled >= 2;
}

// The outcomes the dialog offers to join `primary` ([{id, allowed}]), given
// the ones `chosen` already: none for an outcome that stands alone.
// `answers` ({hidden, consequence}): the mode's, so the diagram's refusals
// grey a choice out too (`why` says why).
export function combineChoices(primary, chosen = [], answers = null) {
  if (!COMBINES.includes(primary)) return [];
  return COMBINES.filter((o) => o !== primary).map((o) => {
    const why = answers && !chosen.includes(o) ? doctrineRefusal(answers.hidden, answers.consequence, [primary, ...chosen, o]) : null;
    const allowed = chosen.includes(o) || (combinationOk([primary, ...chosen, o]) && !why);
    return answers ? { id: o, allowed, why } : { id: o, allowed };
  });
}

// The extra members still allowed once the primary outcome changes (in order,
// each kept while the whole stays a combination the rules allow).
export function pruneExtras(primary, extras) {
  const kept = [];
  for (const x of extras) {
    if (COMBINES.includes(primary) && combinationOk([primary, ...kept.map((k) => k.outcome), x.outcome])) kept.push(x);
  }
  return kept;
}

// The strategy analysis an outcome expects (EvidencePicker's analysisKind).
export const analysisKindOf = (outcome) => ({ fixed_interval: "optimal_replacement", failure_finding: "failure_finding" }[outcome] || null);

// A combination's further task as the server takes it ({outcome, task,
// interval, interval_unit, evidence}). `x`: the dialog's row ({outcome, task,
// interval, intervalUnit, evidence, had: the evidence it had}); `expected`: the
// evidence type its outcome expects. Its own evidence goes with it when it's a
// report or notes (fit for any task), the kind it expects, or what it had.
export function extraBody(x, expected) {
  if (!SCHEDULED.includes(x.outcome)) return { outcome: x.outcome };
  const out = { outcome: x.outcome, ...(String(x.task || "").trim() ? { task: x.task.trim() } : {}),
    interval: Number(x.interval), interval_unit: x.intervalUnit };
  const e = x.evidence;
  if (e?.type && e?.id && (e.type === "report" || e.type === "working" || e.type === expected || e === x.had)) {
    out.evidence = { type: e.type, id: e.id };
  }
  return out;
}

// ---- the RCM decision diagram (SAE JA1011, RCM II) ------------------------------
// Two questions, in order: is the failure evident or hidden (`hidden`: true,
// false, or null not answered), then the consequence category (for a hidden
// failure, what the multiple failure would do). The tasks are weighed in
// order (on condition, fixed interval, then for a hidden failure failure
// finding); when none is worth doing the default action follows from the two
// answers. The same rules and words as the server's
// (backend/maintenance/rcm_decisions.py refusal and default_action).

export const SERIOUS = ["safety", "environmental"];
export const CATEGORIES = ["safety", "environmental", "operational", "non_operational"];
export const TASK_ORDER = ["on_condition", "fixed_interval", "failure_finding"];
// What's done when no task is worth doing, in the dialog's order.
export const DEFAULT_OUTCOMES = ["rtf", "accept", "redesign"];

// A mode's two answers however it was saved: the old fifth consequence
// "hidden" reads as hidden with its category not yet set, and a category with
// no answer as evident (the old five values were one or the other).
export function modeAnswers(mode) {
  const raw = mode?.consequence || null;
  if (raw === "hidden") return { hidden: true, consequence: null };
  if (typeof mode?.hidden === "boolean") return { hidden: mode.hidden, consequence: raw };
  return { hidden: raw ? false : null, consequence: raw };
}

const CATEGORY_WORD = { safety: "A safety", environmental: "An environmental", operational: "An operational", non_operational: "A non-operational" };

// Why the diagram doesn't allow these outcomes for these answers, or null.
export function doctrineRefusal(hidden, consequence, outcomes) {
  const members = (outcomes || []).filter(Boolean);
  if (SERIOUS.includes(consequence) && members.some((o) => o === "rtf" || o === "accept")) {
    return `${CATEGORY_WORD[consequence]} consequence can't be run to failure or accepted: find a task that makes the risk of ${hidden ? "the multiple failure" : "the failure"} tolerable, or redesign.`;
  }
  if (members.includes("failure_finding") && hidden === false) {
    return "Failure finding is for hidden failures only, and this one is evident (the crew would notice it). Mark it hidden if the loss of function can't be seen in normal operation.";
  }
  if (members.filter((o) => SCHEDULED.includes(o)).length > 1 && (consequence === "operational" || consequence === "non_operational")) {
    return `A combination of tasks is only for safety or environmental consequences, where no single task makes the risk tolerable. ${CATEGORY_WORD[consequence]} consequence takes the one task that costs least over time.`;
  }
  return null;
}

// The test a task must pass for these answers, in a few words.
export function worthTest(hidden, consequence) {
  if (SERIOUS.includes(consequence)) return `it makes the risk${hidden ? " of the multiple failure" : ""} tolerable (cost isn't the test)`;
  if (consequence === "operational") return `it costs less over time than the ${hidden ? "multiple failures" : "lost output and repairs"} it prevents`;
  if (consequence === "non_operational") return `it costs less over time than the ${hidden ? "multiple failures" : "repairs"} it prevents`;
  return null;
}

const TASK_WORTH = {
  on_condition: "First choice: worth doing if a sign of the failure shows in time to act",
  fixed_interval: "Next: worth doing if the failures come at an age most of them reach",
  failure_finding: "For a hidden failure, after those: worth doing if a check finds the failure",
};

// One line for each task kind on what makes it worth doing here.
export function worthLine(outcome, hidden, consequence) {
  const start = TASK_WORTH[outcome];
  if (!start) return null;
  const test = worthTest(hidden, consequence);
  return test ? `${start}, and ${test}.` : `${start}.`;
}

// What the diagram prescribes when no task is worth doing ({outcome, then,
// redesign, text}), or null until the category is known.
export function defaultAction(hidden, consequence) {
  if (!CATEGORIES.includes(consequence)) {
    return hidden ? { outcome: null, then: null, redesign: null, text: "Say what the multiple failure would do (the hidden failure plus the one it protects against): the default action follows from it." } : null;
  }
  const serious = SERIOUS.includes(consequence);
  if (!hidden && serious) return { outcome: "redesign", then: null, redesign: "compulsory", text: "If no task makes the risk tolerable, redesign is compulsory. It can't be run to failure." };
  if (!hidden) return { outcome: "rtf", then: null, redesign: "desirable", text: "If no task pays for itself, no scheduled maintenance (run to failure). A redesign may be worth it." };
  if (serious) return { outcome: "failure_finding", then: "redesign", redesign: "compulsory", text: "If no on condition or fixed interval task makes the risk tolerable, a failure finding task that makes the multiple-failure risk tolerable; if none does, redesign is compulsory." };
  return { outcome: "failure_finding", then: "rtf", redesign: "desirable", text: "If no on condition or fixed interval task pays, a failure finding task if it costs less than the multiple failures it prevents; otherwise no scheduled maintenance. A redesign may be worth it." };
}

// What's wrong with an interval as typed (null when nothing is).
function intervalProblem(raw, unit, limits) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return "The interval must be a number.";
  if (n <= 0) return "The interval must be more than 0.";
  if (limits && DAYS_PER[unit] && n * DAYS_PER[unit] > MAX_DAYS) return "The interval is at most 100 years.";
  if (limits && !DAYS_PER[unit] && n > MAX_USE) return `The interval is at most ${MAX_USE.toLocaleString("en-AU")} ${unit}.`;
  return null;
}

// {blockers, intervalError, notice, extraErrors}: `blockers` are what stops
// Apply, in plain words (shown next to the button while it's disabled);
// `intervalError` is the message under the interval field; `notice` is a
// quiet note that doesn't stop Apply; `extraErrors[i]` the message under the
// interval of a combination's i-th further task (`extras`: [{outcome,
// interval, intervalUnit}]). In a combination every scheduled task needs its
// interval, the first one too.
// `hidden` and `consequence`: the mode's answers; a decision the RCM decision
// diagram forbids for them is a blocker, in its words.
export function checkDecision({ outcome, rtfBasis, task = "", interval = "", intervalUnit = "hours", notes = "", fields = [], extras = [], hidden = null, consequence = null }, { limits = false } = {}) {
  const blockers = [];
  let intervalError = null;
  let notice = null;
  if (!outcome) {
    return { blockers: ["Choose a maintenance decision."], intervalError, notice };
  }
  const refused = doctrineRefusal(hidden, consequence, [outcome, ...extras.map((x) => x.outcome)]);
  if (refused) blockers.push(refused);
  if (outcome === "rtf" && !rtfBasis) blockers.push("Choose why it can run to failure.");
  const asksInterval = fields.includes("interval");
  const raw = String(interval ?? "").trim();
  const combined = extras.length > 0;
  if (asksInterval && raw !== "") {
    intervalError = intervalProblem(raw, intervalUnit, limits);
  } else if (asksInterval && (NEEDS_INTERVAL.has(outcome) || combined)) {
    intervalError = INTERVAL_NEEDED[outcome] || "Give the interval: in a combination every task needs one.";
  }
  if (intervalError) blockers.push(raw === "" ? "Give the task's interval." : "Fix the interval.");
  const extraErrors = extras.map((x) => {
    if (!SCHEDULED.includes(x.outcome)) return null;
    const r = String(x.interval ?? "").trim();
    return r === "" ? "Give this task's interval." : intervalProblem(r, x.intervalUnit || "hours", limits);
  });
  if (combined && !combinationOk([outcome, ...extras.map((x) => x.outcome)])) {
    blockers.push("These outcomes can't be combined.");
  }
  if (extraErrors.some(Boolean)) blockers.push("Give each task of the combination a valid interval.");
  if (limits && String(notes || "").trim().length > MAX_NOTES) {
    blockers.push(`Shorten the notes to ${MAX_NOTES.toLocaleString("en-AU")} characters or fewer.`);
  }
  if (outcome === "on_condition" && asksInterval && raw === "" && !combined) {
    notice = String(task || "").trim()
      ? "No task will be created without an interval: give one to schedule it, or say in the notes what covers it."
      : "No task will be created: this decision will show as having no task. Say in the notes what covers it.";
  }
  return { blockers, intervalError, notice, extraErrors };
}

// ---- the interval's unit, remembered on this device ---------------------------
// The decision dialog's unit starts at the one chosen last (most RCMs have
// their tasks in weeks or months, not hours), else hours as before. A decision
// that already has a unit keeps its own. Storage can throw (private mode,
// blocked site data), so every read and write is guarded.

export const INTERVAL_UNITS = ["hours", "days", "weeks", "months", "years", "cycles", "km"];
const UNIT_KEY = "reliafy.rcmIntervalUnit";

// The unit chosen last on this device, or null.
export function rememberedUnit(storage = globalThis.localStorage) {
  try {
    const u = storage?.getItem(UNIT_KEY);
    return INTERVAL_UNITS.includes(u) ? u : null;
  } catch {
    return null;
  }
}

export function rememberUnit(unit, storage = globalThis.localStorage) {
  if (!INTERVAL_UNITS.includes(unit)) return;
  try {
    storage?.setItem(UNIT_KEY, unit);
  } catch {
    // Not remembered on this device; the dialog still works.
  }
}

// The unit the dialog starts at: the decision's own, else the one chosen
// last, else hours.
export function startUnit(existing, storage = globalThis.localStorage) {
  return existing?.interval_unit || rememberedUnit(storage) || "hours";
}
