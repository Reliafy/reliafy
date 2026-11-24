// "How often": the one control for when a task or a work package falls due (HowOften.jsx).
// Pick the type, then fill a short sentence:
//
//   Running hours           Every [2,000] [operating hours]            (a unit of use, through the duty)
//   Days, weeks or months   Every [3] [months]
//   Calendar rule           On [the first] [Saturday] of [every month]; [the 1st] of [every 6 months]
//                           from [March]; every [2 weeks] on [Tuesday]; [the last day] of [every 3 months]
//   At shutdowns            At the first planned shutdown [12] [months] after it was last done
//   (a task's first two types: "or every [12] [months], whichever comes first")
//
// Pure: no React, so the tests can hold it. No date maths here: the dates under the control come
// from the server (POST /api/maintenance/schedule/dates, RePyability's recurrence rules), and
// previewFor only builds that request.
//
// What it saves:
// * a task: interval / unit (and also_interval / also_unit), plus `rule` for a rule or shutdowns, in
//   the shape backend/maintenance/how_often.py checks ({kind: "monthly", every: 1, weekday:
//   "Saturday", nth: 1}; {kind: "shutdowns", every: 12, unit: "months"}; null: none);
// * a package: its cadence fields (every, unit, weekday, nth, day, month, anchor, clear_pattern).

export const CALENDAR = ["days", "weeks", "months", "years"];
export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
// Which day in the month: first to fifth, last, a date, or the month's last day. A fifth falls in only
// some months (the rest are skipped).
export const NTH_CHOICES = [[1, "the first"], [2, "the second"], [3, "the third"], [4, "the fourth"], [5, "the fifth"],
  [-1, "the last"]];
const UNIT_WORDS = { hours: ["operating hour", "operating hours"], km: ["km", "km"] };

// The four types, in the order they're offered.
export const TYPES = [
  { value: "hours", label: "Running hours", title: "Every so many operating hours (or km, cycles), dated through the position's duty" },
  { value: "interval", label: "Days, weeks or months", title: "Every so many days, weeks, months or years after it was last done" },
  { value: "rule", label: "Calendar rule", title: "On set dates: the first Saturday of every month, 1 March and 1 September" },
  { value: "shutdowns", label: "At shutdowns", title: "At the position's next planned shutdown once it's due" },
];

// How often a rule repeats: [value, words]. Months every 2, 3, 4 or 6 fall in the same months each year.
export const STEP_CHOICES = [
  ["weeks:1", "every week"], ["weeks:2", "every 2 weeks"], ["weeks:3", "every 3 weeks"], ["weeks:4", "every 4 weeks"],
  ["months:1", "every month"], ["months:2", "every 2 months"], ["months:3", "every 3 months"], ["months:4", "every 4 months"],
  ["months:6", "every 6 months"], ["years:1", "every year"], ["years:2", "every 2 years"],
];
// The steps offered: the usual ones, and the one a rule has if it isn't among them (every 9 weeks).
export function stepChoices(step) {
  if (!step || STEP_CHOICES.some(([v]) => v === step)) return STEP_CHOICES;
  const [unit, n] = String(step).split(":");
  return [...STEP_CHOICES, [step, `every ${n} ${unitWord(unit, Number(n))}`]];
}
// The steps that fall in set months each year (say which month they start in).
export const MONTH_STEPS = ["months:2", "months:3", "months:4", "months:6"];

export const isCalendar = (unit) => CALENDAR.includes(unit);
// A package by operating hours, in words under its "How often" (its dates are the server's).
export const HOURS_PACKAGE_NOTE = "Its visits come each time the hour meter passes another interval, from its reading "
  + "now; they're dated through the operating plan, else the meter's recent rate.";

// "month" / "3 months"; "operating hours" for hours.
export function unitWord(unit, n = 2) {
  const [one, many] = UNIT_WORDS[unit] || [String(unit).replace(/s$/, ""), unit];
  return Number(n) === 1 ? one : many;
}

// The types a control offers: running hours only where a unit of use is offered; a rule only where
// patterns are allowed (a package counted from its last visit has none); shutdowns on a position's task.
export function typesFor(units, { patterns = true, shutdowns = false } = {}) {
  return TYPES.filter((t) => (t.value === "hours" ? units.some((u) => !isCalendar(u))
    : t.value === "interval" ? units.some(isCalendar)
      : t.value === "rule" ? patterns : shutdowns));
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s);
const monthOf = (iso) => (iso ? String(Number(String(iso).slice(5, 7))) : "1");
const BLANK = { type: "interval", every: "", unit: "months", step: "months:1", pattern: "nth", weekday: "Saturday", nth: "1",
  day: "1", month: "1", startMonth: "1", also: "", alsoUnit: "months" };

// The rule-type fields from a saved rule (or a package's cadence in the same shape).
function ruleFields(r) {
  const unit = { weekly: "weeks", monthly: "months", yearly: "years" }[r.kind];
  const out = { type: "rule", step: `${unit}:${r.every ?? 1}`, startMonth: monthOf(r.anchor) };
  if (r.kind === "weekly") return { ...out, pattern: "weekday", weekday: cap(r.weekdays?.[0] || r.weekday || "Monday") };
  if (r.month) out.month = String(r.month);
  if (r.weekday) return { ...out, pattern: "nth", weekday: cap(r.weekday), nth: String(r.nth) };
  if (Number(r.day) >= 31 || (r.kind === "yearly" && Number(r.month) === 2 && Number(r.day) >= 29)) return { ...out, pattern: "lastday" };
  return { ...out, pattern: "day", day: String(r.day ?? 1) };
}

// The form from a task as read (interval, unit, also_*, rule).
export function formFromTask(task) {
  const r = task?.rule;
  const unit = task?.unit || "months";
  const base = {
    ...BLANK, every: task?.interval != null ? String(task.interval) : "", unit,
    type: isCalendar(unit) ? "interval" : "hours",
    also: task?.also_interval ? String(task.also_interval) : "", alsoUnit: task?.also_unit || "months",
  };
  if (!r || r.kind === "every") return base;
  if (r.kind === "shutdowns") return { ...base, type: "shutdowns", every: String(r.every), unit: r.unit, also: "" };
  return { ...base, ...ruleFields(r) };
}

// The form from a package's cadence as read ({every, unit, weekday, nth, day, month, anchor}).
export function formFromPackage(pkg) {
  const c = pkg?.cadence || {};
  const unit = c.unit || "weeks";
  const base = { ...BLANK, every: String(c.every ?? 1), unit, type: unit === "hours" ? "hours" : "interval",
    step: `${unit}:${c.every ?? 1}`, startMonth: monthOf(c.anchor) };
  if (!c.day && !c.weekday) return base;
  const kind = unit === "weeks" ? "weekly" : unit === "years" ? "yearly" : "monthly";
  return { ...base, ...ruleFields({ kind, every: c.every ?? 1, weekday: c.weekday, nth: c.nth, day: c.day, month: c.month, anchor: c.anchor }) };
}

const whole = (v, lo, hi) => {
  const n = Number(v);
  return v !== "" && v != null && Number.isInteger(n) && n >= lo && n <= hi;
};
const stepOf = (form) => {
  const [unit, n] = String(form.step || "months:1").split(":");
  return { unit, every: Number(n) || 1 };
};
// Whether a type takes the second limit (whichever comes first).
export const takesAlso = (form) => form.type === "hours" || form.type === "interval";

// What's wrong, in words, or null.
export function howOftenProblem(form, { wholeOnly = false } = {}) {
  if (form.type === "rule") {
    if (form.pattern === "day" && !whole(form.day, 1, 31)) return "The day of the month is 1 to 31.";
    return null;
  }
  const n = Number(form.every);
  if (!(n > 0)) return "Say how often: a number more than 0.";
  if ((wholeOnly || form.type === "shutdowns") && !Number.isInteger(n)) return "Give a whole number here.";
  if (takesAlso(form)) {
    if (form.also !== "" && form.also != null && !(Number(form.also) > 0)) return "The second limit is a number more than 0, or leave it empty.";
    if (form.also && form.alsoUnit === form.unit) return "The second limit needs another unit (hours or months, whichever comes first).";
  }
  return null;
}

// The anchor a rule every 2, 3, 4 or 6 months counts from: the 1st of its start month this year.
function monthAnchor(form, anchor) {
  const year = String(anchor || new Date().toISOString()).slice(0, 4);
  return `${year}-${String(form.startMonth || 1).padStart(2, "0")}-01`;
}

// The task's rule ({kind, every, ...}), or null for a plain interval or running hours. anchor: the date
// its weeks, months and years count from (left out, the server takes the day the task was made).
export function ruleOf(form, anchor = null) {
  if (form.type === "shutdowns") return { kind: "shutdowns", every: Number(form.every), unit: form.unit };
  if (form.type !== "rule") return null;
  const { unit, every } = stepOf(form);
  const at = MONTH_STEPS.includes(form.step) ? monthAnchor(form, anchor) : anchor;
  const anchored = at ? { anchor: at } : {};
  if (unit === "weeks") return { kind: "weekly", every, weekdays: [form.weekday], ...anchored };
  const kind = unit === "years" ? "yearly" : "monthly";
  const month = kind === "yearly" ? { month: Number(form.month) } : {};
  let which;
  if (form.pattern === "lastday") which = { day: kind === "yearly" ? new Date(Date.UTC(2028, Number(form.month), 0)).getUTCDate() : 31 };
  else if (form.pattern === "day") which = { day: Number(form.day) };
  else which = { weekday: form.weekday, nth: Number(form.nth) };
  return { kind, every, ...month, ...which, ...anchored };
}

// A task's update or create body: interval, unit, the second limit and the rule (null clears it).
export function taskBody(form, anchor = null) {
  const rule = ruleOf(form, anchor);
  if (form.type === "rule") {
    const { unit, every } = stepOf(form);
    return { interval: every, unit, also_interval: 0, also_unit: null, rule };
  }
  const also = takesAlso(form) && form.also;
  return {
    interval: Number(form.every), unit: form.unit,
    also_interval: also ? Number(form.also) : 0, also_unit: also ? form.alsoUnit : null, rule,
  };
}

// What a task's pattern counts from: its rule's own anchor, else today (a new or newly patterned task).
export const taskAnchor = (task, today) => task?.rule?.anchor || today;

// The every / unit a form steps by (a rule's step; else its interval): what a package's visit plan reads.
export function cadenceOf(form) {
  if (form.type !== "rule") return { every: Number(form.every), unit: form.unit };
  return stepOf(form);
}

// Another type for a form, keeping what carries over: each type keeps a unit it can take (use for
// running hours, the calendar for the rest), and a rule's step and an interval stay in step.
export function changeType(value, t, units) {
  if (!t || t === value.type) return value;
  const next = { ...value, type: t };
  if (t === "hours" && isCalendar(value.unit)) next.unit = units.find((u) => !isCalendar(u)) || value.unit;
  if (t !== "hours" && !isCalendar(value.unit)) next.unit = "months";
  if (t === "rule" && value.type !== "rule" && isCalendar(next.unit) && Number.isInteger(Number(value.every)) && Number(value.every) > 0
      && next.unit !== "days") {
    next.step = `${next.unit}:${Number(value.every)}`;
    if (next.unit === "weeks") next.pattern = "weekday";
    else if (next.pattern === "weekday") next.pattern = "nth";
  }
  if (value.type === "rule" && t !== "rule" && t !== "hours") {
    const [unit, every] = String(value.step).split(":");
    Object.assign(next, { unit, every });
  }
  return next;
}

// A task's "Every [N] [unit]" with a new unit: a unit of use makes it running hours (or km, cycles),
// a calendar unit an interval after it was last done. A rule or shutdowns keep their own unit line.
export function withUnit(value, unit) {
  if (value.type === "rule" || value.type === "shutdowns") return { ...value, unit };
  return { ...value, unit, type: isCalendar(unit) ? "interval" : "hours" };
}

// The units a task's "Every [N] [unit]" offers (Derryn, 23 Nov 2026): operating hours and the
// calendar always (a place's tasks: the calendar only); cycles, starts or km only where one of the
// position's counters counts them, or the task already does.
const USE_OF = { h: "hours", hr: "hours", hrs: "hours", hours: "hours", hour: "hours", km: "km", cycle: "cycles", cycles: "cycles",
  start: "starts", starts: "starts" };
export function taskUnitChoices({ place = false, counters = [], form = null } = {}) {
  if (place) return [...CALENDAR];
  const have = new Set(["hours"]);
  for (const u of counters) if (USE_OF[String(u || "").toLowerCase()]) have.add(USE_OF[String(u).toLowerCase()]);
  for (const u of [form?.unit, form?.alsoUnit]) if (u && !isCalendar(u)) have.add(u);
  return ["hours", "cycles", "starts", "km"].filter((u) => have.has(u)).concat(CALENDAR);
}

// "More scheduling options", folded: one line saying what's set in it, so nothing is hidden
// silently ("" when nothing is). `replace`: the task's own When the item is replaced ("" = default).
export function moreScheduleSummary(form, { replace = "" } = {}) {
  const bits = [];
  if (form.type === "rule") bits.push("on set calendar dates");
  if (form.type === "shutdowns") bits.push("at planned shutdowns");
  if (takesAlso(form) && Number(form.also) > 0) {
    bits.push(`also every ${Number(form.also).toLocaleString("en-GB")} ${unitWord(form.alsoUnit, Number(form.also))}, whichever first`);
  }
  if (replace === "restart") bits.push("restarts when the item is replaced");
  if (replace === "keep") bits.push("keeps its schedule when the item is replaced");
  const text = bits.join(" · ");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

// A package's cadence fields, for create or update (its pattern replaced, or cleared).
export function packageBody(form) {
  if (form.type !== "rule") return { every: Number(form.every), unit: form.unit, clear_pattern: true };
  const { unit, every } = stepOf(form);
  const body = { every, unit };
  if (unit === "weeks") body.weekday = form.weekday.toLowerCase();
  else {
    const rule = ruleOf(form);
    if (rule.weekday) { body.weekday = rule.weekday.toLowerCase(); body.nth = rule.nth; } else body.day = rule.day;
    if (unit === "years") body.month = Number(form.month);
    if (MONTH_STEPS.includes(form.step)) body.anchor = monthAnchor(form, null);
  }
  return body;
}

// ---- the preview under the control ---------------------------------------------------------

const DAYS_PER = { days: 1, weeks: 7, months: 30.4375, years: 365.25 };
// A plain interval as the server takes it (whole units; a part month as days).
function plain(every, unit) {
  const n = Number(every);
  return Number.isInteger(n) ? { kind: "every", every: n, unit } : { kind: "every", every: Math.max(1, Math.round(n * DAYS_PER[unit])), unit: "days" };
}

// What to ask the server for, to show the next dates under the control: {request, lead, note, after}.
// request is the body of POST /api/maintenance/schedule/dates, or null (nothing to date: say `note`).
//   from:       the day counting starts (a task: when it was last done, else today)
//   after:      true when `from` itself is done (a task last done that day): only later dates count
//   anchor:     what a rule counts its weeks, months and years from (a task's rule, a package's anchor)
//   positionId: a task at shutdowns: the position whose shutdowns it's done at
//   fixed:      a package on set dates (its plain interval counts from its anchor, not from `from`)
export function previewFor(form, { from, after = false, anchor = null, positionId = null, fixed = false, count = 5 } = {}) {
  const none = (note) => ({ request: null, lead: "Next", note, after: "" });
  if (howOftenProblem(form)) return none("");
  const base = { start: from, after, count };
  if (form.type === "hours") {
    const also = Number(form.also);
    if (also > 0 && isCalendar(form.alsoUnit)) {
      return { request: { ...base, rule: plain(also, form.alsoUnit) }, lead: `By the ${also.toLocaleString("en-GB")}-${unitWord(form.alsoUnit, 1)} limit`,
        note: "", after: "or sooner, when the meter gets there first." };
    }
    return none(`By ${unitWord(form.unit, 2)}: its dates come from the operating plan where there is one, else its meter readings.`);
  }
  if (form.type === "shutdowns") {
    if (!positionId) return none("Its dates are the position's planned shutdowns.");
    return { request: { ...base, rule: ruleOf(form), position_id: positionId }, lead: "Next", note: "", after: "" };
  }
  if (form.type === "rule") return { request: { ...base, rule: ruleOf(form, anchor) }, lead: "Next", note: "", after: "" };
  const rule = { ...plain(form.every, form.unit), ...(fixed && anchor ? { anchor } : {}) };
  const also = Number(form.also) > 0 && isCalendar(form.alsoUnit) ? plain(form.also, form.alsoUnit) : null;
  return { request: { ...base, rule, ...(also ? { also: { every: also.every, unit: also.unit } } : {}) }, lead: "Next", note: "", after: "" };
}
