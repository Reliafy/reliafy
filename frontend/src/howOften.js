// "How often": the one control for when a task or a work package falls due
// (HowOften.jsx). It reads as a sentence: "Every [1] [month] on [the first]
// [Saturday]", "Every [1] [year] on [the first] [Tuesday] of [November]",
// "Every [2,000] [operating hours]", "or every [12] [months], whichever comes
// first". Pure: no React, so the tests can hold it.
//
// What it saves:
// * a task: interval / unit (and also_interval / also_unit), plus `rule` for a
//   pattern an interval can't say, in the shape backend/maintenance/how_often.py
//   checks ({kind: "monthly", every: 1, weekday: "Saturday", nth: 1}; null: none);
// * a package: its cadence fields (every, unit, weekday, nth, day, month,
//   clear_pattern), which the server reads into the same shape.
//
// The next dates shown under it are worked out here, the same way the server's
// schedule (Cadence) does, so a wrong rule is caught before saving. This is a
// thin seam: the scheduling library will own the arithmetic later.

export const CALENDAR = ["days", "weeks", "months", "years"];
export const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
// Which one in the month: first to fifth, last. A fifth falls in only some months (the rest are skipped).
export const NTH_CHOICES = [[1, "the first"], [2, "the second"], [3, "the third"], [4, "the fourth"], [5, "the fifth"],
  [-1, "the last"]];
const UNIT_WORDS = { hours: ["operating hour", "operating hours"], km: ["km", "km"] };

export const isCalendar = (unit) => CALENDAR.includes(unit);

// "month" / "3 months"; "operating hours" for hours.
export function unitWord(unit, n = 2) {
  const [one, many] = UNIT_WORDS[unit] || [String(unit).replace(/s$/, ""), unit];
  return Number(n) === 1 ? one : many;
}

// Which patterns a unit can have: a weekday for weeks; a weekday or a date for months and years.
export function patternsFor(unit) {
  if (unit === "weeks") return ["none", "weekday"];
  if (unit === "months" || unit === "years") return ["none", "nth", "day"];
  return ["none"];
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1).toLowerCase() : s);

// The form from a task as read (interval, unit, also_*, rule).
export function formFromTask(task) {
  const r = task?.rule;
  const base = {
    every: task?.interval != null ? String(task.interval) : "", unit: task?.unit || "months",
    pattern: "none", weekday: "Saturday", nth: "1", day: "1", month: "1",
    also: task?.also_interval ? String(task.also_interval) : "", alsoUnit: task?.also_unit || "months",
  };
  if (!r) return base;
  const out = { ...base, every: String(r.every ?? 1), unit: { weekly: "weeks", monthly: "months", yearly: "years" }[r.kind] || base.unit };
  if (r.kind === "weekly") return { ...out, pattern: "weekday", weekday: cap(r.weekdays?.[0] || "Saturday") };
  if (r.month) out.month = String(r.month);
  if (r.weekday) return { ...out, pattern: "nth", weekday: cap(r.weekday), nth: String(r.nth) };
  if (r.day) return { ...out, pattern: "day", day: String(r.day) };
  return out;
}

// The form from a package's cadence as read ({every, unit, weekday, nth, day, month, anchor}).
export function formFromPackage(pkg) {
  const c = pkg?.cadence || {};
  const unit = c.unit || "weeks";
  let pattern = "none";
  if (c.day) pattern = "day";
  else if (c.weekday) pattern = unit === "weeks" ? "weekday" : "nth";
  return {
    every: String(c.every ?? 1), unit, pattern, weekday: cap(c.weekday || "Monday"), nth: String(c.nth ?? 1),
    day: String(c.day ?? 1), month: String(c.month ?? 1), also: "", alsoUnit: "months",
  };
}

const whole = (v, lo, hi) => {
  const n = Number(v);
  return v !== "" && v != null && Number.isInteger(n) && n >= lo && n <= hi;
};

// What's wrong, in words, or null.
export function howOftenProblem(form, { wholeOnly = false } = {}) {
  const n = Number(form.every);
  if (!(n > 0)) return "Say how often: a number more than 0.";
  const pattern = patternOf(form);
  if ((wholeOnly || pattern !== "none") && !Number.isInteger(n)) return "Every is a whole number here.";
  if (pattern === "day" && !whole(form.day, 1, 31)) return "The day of the month is 1 to 31.";
  if (form.also !== "" && form.also != null && !(Number(form.also) > 0)) return "The second limit is a number more than 0, or leave it empty.";
  if (form.also && form.alsoUnit === form.unit) return "The second limit needs another unit (hours or months, whichever comes first).";
  return null;
}

// The pattern the form has, given its unit (a pattern the unit can't take falls back to none).
export function patternOf(form) {
  return patternsFor(form.unit).includes(form.pattern) ? form.pattern : "none";
}

// The task's rule ({kind, every, ...}), or null for a plain interval. anchor: the date its weeks,
// months and years count from (left out, the server takes the day the task was made).
export function ruleOf(form, anchor = null) {
  const every = Number(form.every);
  const pattern = patternOf(form);
  if (pattern === "none") return null;
  if (form.unit === "weeks") return { kind: "weekly", every, weekdays: [form.weekday], ...(anchor ? { anchor } : {}) };
  const kind = form.unit === "years" ? "yearly" : "monthly";
  const which = pattern === "nth" ? { weekday: form.weekday, nth: Number(form.nth) } : { day: Number(form.day) };
  return { kind, every, ...(kind === "yearly" ? { month: Number(form.month) } : {}), ...which, ...(anchor ? { anchor } : {}) };
}

// A task's update or create body: interval, unit, the second limit and the rule (null clears it).
export function taskBody(form, anchor = null) {
  return {
    interval: Number(form.every), unit: form.unit,
    also_interval: form.also ? Number(form.also) : 0, also_unit: form.also ? form.alsoUnit : null,
    rule: ruleOf(form, anchor),
  };
}

// What a task's pattern counts from: its rule's own anchor, else today (a new or newly patterned task).
export const taskAnchor = (task, today) => task?.rule?.anchor || today;

// A package's cadence fields, for create or update (its pattern replaced, or cleared).
export function packageBody(form) {
  const body = { every: Number(form.every), unit: form.unit };
  const pattern = patternOf(form);
  if (pattern === "weekday") body.weekday = form.weekday.toLowerCase();
  else if (pattern === "nth") { body.weekday = form.weekday.toLowerCase(); body.nth = Number(form.nth); }
  else if (pattern === "day") body.day = Number(form.day);
  else body.clear_pattern = true;
  if (form.unit === "years" && pattern !== "none") body.month = Number(form.month);
  return body;
}

const nthWord = (nth) => (NTH_CHOICES.find(([v]) => v === Number(nth)) || [0, `the ${nth}th`])[1];
const ordinalDay = (d) => {
  const n = Number(d);
  const suffix = n % 100 >= 10 && n % 100 <= 20 ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th");
  return `${n}${suffix}`;
};

// The whole thing in words: "Every month on the first Saturday", "Every 2,000 operating hours,
// or every 12 months, whichever comes first".
export function howOftenWords(form) {
  const n = Number(form.every);
  const pattern = patternOf(form);
  const num = Number.isFinite(n) ? n.toLocaleString("en-GB") : form.every;
  let text = n === 1 ? `Every ${unitWord(form.unit, 1)}` : `Every ${num} ${unitWord(form.unit, n)}`;
  if (pattern === "weekday") text += ` on ${form.weekday}`;
  if (pattern === "nth") text += ` on ${nthWord(form.nth)} ${form.weekday}`;
  if (pattern === "day") text += ` on the ${ordinalDay(form.day)}`;
  if (form.unit === "years" && pattern !== "none") text += ` of ${MONTH_NAMES[Number(form.month) - 1]}`;
  if (form.also && Number(form.also) > 0) {
    text += `, or every ${Number(form.also).toLocaleString("en-GB")} ${unitWord(form.alsoUnit, Number(form.also))}, whichever comes first`;
  }
  return text;
}

// ---- dates --------------------------------------------------------------------------------

const toDate = (iso) => {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
};
const iso = (dt) => dt.toISOString().slice(0, 10);
const addDays = (dt, n) => new Date(dt.getTime() + n * 86400000);
const daysIn = (y, m) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();
// Monday 0 … Sunday 6.
const weekdayOf = (dt) => (dt.getUTCDay() + 6) % 7;

// anchor + months, keeping the anchor's day (a shorter month's last day instead).
export function addMonths(isoDay, months) {
  const a = toDate(isoDay);
  const total = a.getUTCFullYear() * 12 + a.getUTCMonth() + months;
  const y = Math.floor(total / 12);
  const m = total - y * 12;
  return iso(new Date(Date.UTC(y, m, Math.min(a.getUTCDate(), daysIn(y, m)))));
}

// The server's add_interval: whole months by the calendar, part months as 30.4375 days.
export function addInterval(isoDay, interval, unit) {
  const n = Number(interval);
  if (unit === "days") return iso(addDays(toDate(isoDay), Math.round(n)));
  if (unit === "weeks") return iso(addDays(toDate(isoDay), Math.round(n * 7)));
  if (unit === "months" || unit === "years") {
    const months = n * (unit === "years" ? 12 : 1);
    return Number.isInteger(months) ? addMonths(isoDay, months) : iso(addDays(toDate(isoDay), Math.round(months * 30.4375)));
  }
  return null;
}

// The nth `weekday` (0 Monday) of a month, or null (a fifth that month hasn't).
function nthWeekday(y, m, weekday, nth) {
  const len = daysIn(y, m);
  if (nth > 0) {
    const first = weekdayOf(new Date(Date.UTC(y, m, 1)));
    const day = 1 + ((weekday - first + 7) % 7) + (nth - 1) * 7;
    return day <= len ? new Date(Date.UTC(y, m, day)) : null;
  }
  const last = weekdayOf(new Date(Date.UTC(y, m, len)));
  const day = len - ((last - weekday + 7) % 7) + (nth + 1) * 7;
  return day >= 1 ? new Date(Date.UTC(y, m, day)) : null;
}

// The dates a rule gives on or after `from`, counted from `anchor` (at most `count`).
export function ruleDates(rule, anchor, from, count = 3) {
  const out = [];
  const start = toDate(anchor);
  const lo = toDate(from) > start ? toDate(from) : start;
  const every = Number(rule.every) || 1;
  if (rule.kind === "weekly") {
    const wd = WEEKDAY_NAMES.indexOf(cap(rule.weekdays[0]));
    const week0 = addDays(start, -weekdayOf(start));
    let d = addDays(lo, (wd - weekdayOf(lo) + 7) % 7);
    for (let guard = 0; out.length < count && guard < 5000; guard += 1, d = addDays(d, 7)) {
      const weeks = Math.round((addDays(d, -weekdayOf(d)) - week0) / (7 * 86400000));
      if (weeks % every === 0) out.push(iso(d));
    }
    return out;
  }
  const months = rule.kind === "yearly" ? 12 * every : every;
  const m0 = start.getUTCFullYear() * 12 + start.getUTCMonth();
  let k = Math.max(0, Math.floor((lo.getUTCFullYear() * 12 + lo.getUTCMonth() - m0) / months) - 1);
  for (let guard = 0; out.length < count && guard < 1000; guard += 1, k += 1) {
    const total = m0 + k * months + (rule.kind === "yearly" ? (Number(rule.month) - 1) - start.getUTCMonth() : 0);
    const y = Math.floor(total / 12);
    const m = total - y * 12;
    if (rule.kind === "yearly" && y < start.getUTCFullYear()) continue;
    let d;
    if (rule.weekday) d = nthWeekday(y, m, WEEKDAY_NAMES.indexOf(cap(rule.weekday)), Number(rule.nth));
    else d = new Date(Date.UTC(y, m, Math.min(Number(rule.day), daysIn(y, m))));
    if (d && d >= lo) out.push(iso(d));
  }
  return out;
}

// The next `count` dates the form gives, or null when they come from a meter (a unit of use).
//   from:   the day counting starts (a task: when it was last done, else today)
//   anchor: what a pattern counts its weeks, months and years from (a package's anchor)
//   after:  true when `from` itself is done (a task last done that day): only later dates count
export function nextDates(form, { from, anchor = null, after = false, count = 3 } = {}) {
  if (!isCalendar(form.unit) || howOftenProblem(form)) return null;
  const rule = ruleOf(form, anchor);
  if (rule) {
    const start = after ? addInterval(from, 1, "days") : from;
    return ruleDates(rule, anchor || from, start, count);
  }
  const out = [];
  let base = from;
  const also = form.also && isCalendar(form.alsoUnit) ? [Number(form.also), form.alsoUnit] : null;
  for (let i = 0; i < count; i += 1) {
    let next = addInterval(base, form.every, form.unit);
    if (also) {
      const other = addInterval(base, also[0], also[1]);
      if (other && other < next) next = other;
    }
    if (!next) break;
    out.push(next);
    base = next;
  }
  return out;
}

// Where package dates start: a fixed cadence from its anchor; counted from the last visit, from today.
export function packageDates(form, { anchor, today, timing = "fixed", count = 3 }) {
  if (timing !== "fixed") return nextDates({ ...form, pattern: "none" }, { from: today, count });
  const rule = ruleOf(form) || { kind: "every" };
  if (rule.kind !== "every") return ruleDates(rule, anchor || today, today, count);
  // Every N units from the anchor: the first on or after today, then on.
  const out = [];
  const months = form.unit === "years" ? 12 * Number(form.every) : form.unit === "months" ? Number(form.every) : null;
  const step = months ? null : (form.unit === "weeks" ? 7 : 1) * Number(form.every);
  const behind = step ? Math.floor((toDate(today) - toDate(anchor || today)) / 86400000 / step) : 0;
  for (let k = Math.max(0, behind - 1), guard = 0; out.length < count && guard < 5000; k += 1, guard += 1) {
    const d = months ? addMonths(anchor || today, k * months) : addInterval(anchor || today, k * Number(form.every), form.unit);
    if (d >= today) out.push(d);
  }
  return out;
}

// What to show under the control: {dates, lead, note}. A unit of use goes by its meter, so
// only a calendar second limit has dates of its own ("By the 12-month limit: …").
export function howOftenPreview(form, opts) {
  if (isCalendar(form.unit)) return { dates: nextDates(form, opts), lead: "Next", note: "" };
  const also = Number(form.also);
  if (also > 0 && isCalendar(form.alsoUnit)) {
    const dates = nextDates({ ...form, every: form.also, unit: form.alsoUnit, pattern: "none", also: "" }, opts);
    return { dates, lead: `By the ${also.toLocaleString("en-GB")}-${unitWord(form.alsoUnit, 1)} limit`, note: "", after: "or sooner, when the meter gets there first." };
  }
  return { dates: null, lead: "Next", note: `By ${unitWord(form.unit, 2)}: its dates come from its meter readings.` };
}
