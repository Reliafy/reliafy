// A work package's own page (Maintenance › Packages › one): the sentence at its
// top, and its Edit pane's form, checked, and turned into the update's body
// (only what changed). Pure: no React, so the tests can hold it.
import { cadenceWords, daysLate } from "./lsaTab.js";
import { doneText } from "./maintenanceOrders.js";
import { formatDate } from "./dates.js";

const UNITS = ["days", "weeks", "months", "years"];
export const PACKAGE_UNITS = UNITS;
export const NTHS = [[1, "first"], [2, "second"], [3, "third"], [4, "fourth"], [-1, "last"]];

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// "Sat 14 Nov" (with the year when it isn't `today`'s).
export function visitDay(iso, today = null) {
  if (!iso) return "";
  const sameYear = !!today && String(today).slice(0, 4) === String(iso).slice(0, 4);
  return formatDate(String(iso).slice(0, 10), { weekday: true, year: !sameYear }) || String(iso);
}

// The page's first line, the answer first: "Every Saturday, next visit Sat 14 Nov; 1 visit late".
export function packageSentence(pkg, today = null) {
  if (!pkg) return "";
  const cadence = cadenceWords(pkg) || "No timing set";
  if (pkg.status === "retired") {
    return `Retired${pkg.retired_reason ? `: ${pkg.retired_reason}` : ""}.${pkg.cadence?.text ? ` It visited ${pkg.cadence.text}.` : ""}`;
  }
  const parts = [cadence + (pkg.parent ? `, on ${pkg.parent.name}'s visits` : "")];
  if (pkg.status === "paused") {
    parts[0] += `; ${pkg.pause?.text || "paused"}`;
    return parts[0] + ".";
  }
  const wo = pkg.open_work_order;
  if (wo) parts[0] += `, visit of ${visitDay(wo.visit_on, today)} open (#${wo.number})`;
  else if (pkg.next_visit) parts[0] += `, next visit ${visitDay(pkg.next_visit, today)}`;
  else parts[0] += ", no visit due";
  const late = daysLate(pkg, today);
  if (late > 0) {
    const missed = Math.max(1, wo?.visits_missed || 0);
    parts.push(`${plural(missed, "visit")} late, by ${plural(late, "day")}`);
  }
  if (pkg.season && pkg.in_season === false) parts.push(`out of season (${pkg.season.text})`);
  return parts.join("; ") + ".";
}

// A visit rule in words, for a task's row: "every visit", "every 4th visit (the first, then every 4th)".
export function ruleOf(task) {
  return task?.visit_rule === "nth" && task.every_nth ? { rule: "nth", nth: String(task.every_nth) } : { rule: "every", nth: "" };
}

// The Edit pane's starting values, from the package as read.
export function initialForm(pkg) {
  const c = pkg?.cadence || {};
  const pattern = c.day ? "day" : c.weekday ? "weekday" : "none";
  return {
    name: pkg?.name || "",
    timing: pkg?.timing || "fixed",
    every: String(c.every ?? 1),
    unit: c.unit || "weeks",
    pattern,
    weekday: String(c.weekday || "monday").toLowerCase(),
    nth: String(c.nth ?? 1),
    day: String(c.day ?? 1),
    tolerance: pkg?.tolerance?.amount != null ? String(pkg.tolerance.amount) : "0",
    toleranceUnit: pkg?.tolerance?.unit || "days",
    trade: pkg?.trade || "",
    notes: pkg?.notes || "",
    rules: Object.fromEntries((pkg?.tasks || []).map((t) => [t.task_id, ruleOf(t)])),
  };
}

const TIMING_KEYS = ["timing", "every", "unit", "pattern", "weekday", "nth", "day"];
const whole = (v, lo, hi) => {
  const n = Number(v);
  return v !== "" && Number.isInteger(n) && n >= lo && n <= hi;
};

// What's wrong with the form, in words, or null.
export function formProblem(form, pkg) {
  if (!form.name.trim()) return "Give it a name.";
  if (!whole(form.every, 1, 1000)) return "Every is a whole number, 1 or more.";
  if (form.pattern === "day" && !whole(form.day, 1, 31)) return "The day of the month is 1 to 31.";
  if (!pkg?.parent && form.toleranceUnit === "days" && !whole(form.tolerance, 0, 366)) return "On time within is a whole number of days, 0 to 366.";
  if (!pkg?.parent && form.toleranceUnit === "hours" && !(Number(form.tolerance) >= 0)) return "On time within is a number of hours, 0 or more.";
  for (const [id, r] of Object.entries(form.rules)) {
    if (r.rule === "nth" && !whole(r.nth, 2, 100)) {
      const t = (pkg?.tasks || []).find((x) => x.task_id === id);
      return `${t?.name || "A task"}: every Nth visit is a whole number, 2 to 100.`;
    }
  }
  return null;
}

// Which pattern the timing can have: a weekday for weeks, a weekday or a date for months, none otherwise.
export function patternsFor(form) {
  if (form.timing !== "fixed") return ["none"];
  if (form.unit === "weeks") return ["weekday"];
  if (form.unit === "months") return ["weekday", "day"];
  return ["none"];
}

// The update's body: only what changed ({} when nothing did). Timing goes as a
// whole when any part of it changed, its pattern replaced (or cleared).
export function editBody(pkg, form) {
  const start = initialForm(pkg);
  const body = {};
  if (form.name.trim() !== start.name) body.name = form.name.trim();
  if (form.trade.trim() !== start.trade) body.trade = form.trade.trim();
  if (form.notes !== start.notes) body.notes = form.notes;
  if (TIMING_KEYS.some((k) => form[k] !== start[k])) {
    body.timing = pkg?.parent ? "fixed" : form.timing;
    body.every = Number(form.every);
    body.unit = form.unit;
    const allowed = patternsFor({ ...form, timing: body.timing });
    const pattern = allowed.includes(form.pattern) ? form.pattern : allowed[0];
    if (pattern === "weekday") {
      body.weekday = form.weekday;
      if (form.unit === "months") body.nth = Number(form.nth);
    } else if (pattern === "day") {
      body.day = Number(form.day);
    } else {
      body.clear_pattern = true;
    }
  }
  if (!pkg?.parent && (form.tolerance !== start.tolerance || form.toleranceUnit !== start.toleranceUnit)) {
    body.tolerance = Number(form.tolerance);
    body.tolerance_unit = form.toleranceUnit;
  }
  const tasks = [];
  for (const t of pkg?.tasks || []) {
    const was = start.rules[t.task_id];
    const now = form.rules[t.task_id] || was;
    if (now.rule === was.rule && (now.rule !== "nth" || Number(now.nth) === Number(was.nth))) continue;
    tasks.push({
      task_id: t.task_id, visit_rule: now.rule, ...(now.rule === "nth" ? { every_nth: Number(now.nth) } : {}),
      suppresses: (t.suppresses || []).map((s) => s.id),
    });
  }
  if (tasks.length) body.tasks = tasks;
  return body;
}

// What a recent work order's visit came to: open (late or not), or what was done.
export function outcomeText(wo) {
  if (!wo) return "";
  if (wo.status !== "closed" && wo.status !== "cancelled") return wo.overdue ? "Open, late" : "Open";
  return doneText(wo);
}

// A task's name in the Edit pane: with what it's on when another task in the
// package has the same name (a check on each of three pumps).
export function taskLabel(task, tasks = []) {
  const twins = tasks.filter((t) => t.name === task.name).length > 1;
  return twins && task.subject?.name ? `${task.name} · ${task.subject.name}` : task.name;
}

// What a visit does, in words: each task name once, with how many ("Check seal ×3, Grease").
export function visitTasksText(taskIds = [], tasks = []) {
  const byId = Object.fromEntries(tasks.map((t) => [t.task_id, t.name]));
  const counts = new Map();
  for (const id of taskIds) {
    const name = byId[id];
    if (name) counts.set(name, (counts.get(name) || 0) + 1);
  }
  return [...counts].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name)).join(", ");
}
