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

// {blockers, intervalError, notice}: `blockers` are what stops Apply, in
// plain words (shown next to the button while it's disabled); `intervalError`
// is the message under the interval field; `notice` is a quiet note that
// doesn't stop Apply.
export function checkDecision({ outcome, rtfBasis, task = "", interval = "", intervalUnit = "hours", notes = "", fields = [] }, { limits = false } = {}) {
  const blockers = [];
  let intervalError = null;
  let notice = null;
  if (!outcome) {
    return { blockers: ["Choose a maintenance decision."], intervalError, notice };
  }
  if (outcome === "rtf" && !rtfBasis) blockers.push("Choose why it can run to failure.");
  const asksInterval = fields.includes("interval");
  const raw = String(interval ?? "").trim();
  if (asksInterval && raw !== "") {
    const n = Number(raw);
    if (!Number.isFinite(n)) intervalError = "The interval must be a number.";
    else if (n <= 0) intervalError = "The interval must be more than 0.";
    else if (limits && DAYS_PER[intervalUnit] && n * DAYS_PER[intervalUnit] > MAX_DAYS) intervalError = "The interval is at most 100 years.";
    else if (limits && !DAYS_PER[intervalUnit] && n > MAX_USE) intervalError = `The interval is at most ${MAX_USE.toLocaleString("en-AU")} ${intervalUnit}.`;
  } else if (asksInterval && NEEDS_INTERVAL.has(outcome)) {
    intervalError = INTERVAL_NEEDED[outcome];
  }
  if (intervalError) blockers.push(raw === "" ? "Give the task's interval." : "Fix the interval.");
  if (limits && String(notes || "").trim().length > MAX_NOTES) {
    blockers.push(`Shorten the notes to ${MAX_NOTES.toLocaleString("en-AU")} characters or fewer.`);
  }
  if (outcome === "on_condition" && asksInterval && raw === "") {
    notice = String(task || "").trim()
      ? "No task will be created without an interval: give one to schedule it, or say in the notes what covers it."
      : "No task will be created: this decision will show as having no task. Say in the notes what covers it.";
  }
  return { blockers, intervalError, notice };
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
