// A work order's "Readings and settings": the points it asks to be read or set
// (GET /api/maintenance/work-orders/:id's reading_points: its tasks' LSA tools'
// points, a trigger's point, a task by use's counter, the settings where it is),
// then the other hand-read points there. Values are recorded when the work
// order closes or when Record is pressed (POST …/readings), each linked to the
// work order. Pure functions, tested in workOrderReadings.test.js.

import { numberText } from "./measuringPoint.js";
import { withUnit } from "./measurementsTab.js";

const WHY = {
  tool: "a tool the task uses reads it",
  trigger: "the task's trigger watches it",
  counter: "the task goes by its use",
  setting: "a setting here",
};

// Why the work order asks for a point, in words ("a tool the task uses reads it · a setting here").
export const whyText = (why) => (why || []).map((w) => WHY[w] || w).join(" · ");

// The rows the section lists: the points asked for first (group "asked"), then
// the other hand-read points on what it's on (group "other"), each once.
export function readingRows(wo) {
  const asked = (wo?.reading_points || []).map((p) => ({
    id: p.id, name: p.name, unit: p.unit || "", kind: p.kind, last: p.reading, taskId: p.task_id || null,
    task: p.task?.name || "", why: whyText(p.why), recorded: p.recorded || null, group: "asked",
    range: [p.range_min, p.range_max],
  }));
  const seen = new Set(asked.map((r) => r.id));
  // A point here whose name the task's own words name (a "Vibration check" and the pump's
  // "Vibration" point) is what the check reads: asked for, next to the task's own points,
  // not folded under "Other measurements here".
  const words = taskWords([wo?.task?.name, ...(wo?.lines || []).map((l) => l.name || l.task?.name)]);
  const other = [];
  for (const m of (wo?.measurements || []).filter((x) => !seen.has(x.id))) {
    const named = words.size > 0 && [...nameWords(m.name)].some((w) => words.has(w));
    const row = {
      id: m.id, name: m.name, unit: m.unit || "", kind: m.kind, last: m.reading, taskId: null, task: named ? wo?.task?.name || "" : "",
      why: named ? "the task names it" : "", recorded: null, group: named ? "asked" : "other", range: [null, null],
    };
    if (named) asked.push(row);
    else other.push(row);
  }
  return [...asked, ...other];
}

// Words that say what a task does, not what it reads: never enough to tie a point to it.
const COMMON = new Set([
  "check", "checks", "inspect", "inspection", "replace", "replacement", "test", "service", "clean", "weekly",
  "monthly", "yearly", "annual", "daily", "quarterly", "routine", "record", "reading", "readings", "take",
  "measure", "level", "the", "and", "with", "from", "pump", "motor", "drive",
]);
function nameWords(text) {
  return new Set(String(text || "").toLowerCase().split(/[^a-z0-9]+/).filter((w) => w.length >= 4 && !COMMON.has(w)));
}
function taskWords(names) {
  const out = new Set();
  for (const n of names) for (const w of nameWords(n)) out.add(w);
  return out;
}

// A row's value box to start with: a setting's current value (it's what's
// changed from), else empty. Prefilled values aren't sent until edited.
export function startValues(rows) {
  const out = {};
  for (const r of rows) out[r.id] = { value: r.kind === "setting" && r.last != null ? String(r.last) : "", dirty: false };
  return out;
}

// The boxes after the work order is (re)loaded: fresh start values, except
// a box someone has typed in and not yet recorded, which keeps what they typed.
// (A checklist tick or a status change reloads the work order too; it must
// never wipe a value being entered.)
export function mergeValues(rows, prev) {
  const start = startValues(rows);
  for (const id of Object.keys(start)) if (prev?.[id]?.dirty) start[id] = prev[id];
  return start;
}

// The boxes once `sent` ([{point_id}]) are recorded: those go back to clean
// (the reload then gives them their new start value); the rest are untouched.
export function clearSent(values, sent) {
  const out = { ...values };
  for (const r of sent || []) if (out[r.point_id]) out[r.point_id] = { ...out[r.point_id], dirty: false };
  return out;
}

// What to send: every box edited and not empty, [{point_id, value, task_id?}].
// An empty box (or one left as prefilled) records nothing.
export function readingsToSend(rows, values) {
  const out = [];
  for (const r of rows) {
    const v = values?.[r.id];
    if (!v || !v.dirty || String(v.value).trim() === "") continue;
    const n = Number(v.value);
    if (!Number.isFinite(n)) continue;
    out.push({ point_id: r.id, value: n, ...(r.taskId ? { task_id: r.taskId } : {}) });
  }
  return out;
}

// A box's label: "Chlorinator output (%)", a setting's "now 45%" hint as placeholder.
export function boxLabel(r) {
  return `${r.name}${r.unit ? ` (${r.unit})` : ""}${r.kind === "setting" ? ", set to" : ""}`;
}

// A row's muted line: why it's asked, the task, its last value, and whether a
// value has been taken at this work order.
export function rowDetail(r) {
  const last = r.last != null ? `${r.kind === "setting" ? "now" : "last"} ${withUnit(numberText(r.last), r.unit)}` : r.kind === "setting" ? "not set yet" : "never read";
  return [r.recorded ? `recorded ${withUnit(numberText(r.recorded.value), r.unit)} here` : "", r.why, r.task && `for ${r.task}`, last]
    .filter(Boolean).join(" · ");
}

// "Readings: 2 of 3 recorded" for a task's line ({asked, recorded}), or "".
export function progressText(counts) {
  if (!counts || !counts.asked) return "";
  return `Readings: ${counts.recorded} of ${counts.asked} recorded`;
}

// One taken reading in words: "Chlorinator output set to 60% (from 45%)", "Salt 3200 ppm".
export function takenText(r) {
  const u = r.point?.unit || "";
  if (r.point?.kind === "setting") {
    return `${r.point.name} set to ${withUnit(numberText(r.value), u)}${r.from != null ? ` (from ${withUnit(numberText(r.from), u)})` : ""}`;
  }
  return `${r.point?.name || "Reading"} ${withUnit(numberText(r.value), u)}`;
}

// What's wrong with a value as typed, before anything is sent ("" when nothing): a
// counter only goes up, so a value below its last reading is refused (the server would
// refuse it at Close); one outside the point's range says so.
export function boxProblem(r, raw) {
  if (raw == null || String(raw).trim() === "") return "";
  const v = Number(raw);
  if (!Number.isFinite(v)) return "Enter a number.";
  if (r?.kind === "counter" && r.last != null && v < Number(r.last)) {
    return `A counter only goes up: the last reading was ${r.last}${r.unit ? ` ${r.unit}` : ""}. If the counter was replaced, add a new one.`;
  }
  const [lo, hi] = r?.range || [];
  if (lo != null && v < lo) return `Below its range (at least ${lo}).`;
  if (hi != null && v > hi) return `Above its range (at most ${hi}).`;
  return "";
}
