// Reliafy Maintenance: what a task or work order is on. A position (the job: it
// stays with the slot), an item (it follows the serial number, into a store and to
// another position) or a location (a round, an area inspection).

export const SUBJECT_KINDS = ["position", "item", "location"];
const PATHS = { position: "positions", item: "items", location: "locations" };

// Units a task can count: a location's go by the calendar only.
export const CALENDAR_UNITS = ["days", "weeks", "months", "years"];
export const ALL_UNITS = [...CALENDAR_UNITS, "hours", "cycles", "km", "starts"];
export function taskUnits(kind) {
  return kind === "location" ? CALENDAR_UNITS : ALL_UNITS;
}

// The page a subject is on: /asset-register/items/<id>.
export function subjectPath(subject) {
  if (!subject?.id || !PATHS[subject.kind]) return null;
  return `/asset-register/${PATHS[subject.kind]}/${subject.id}`;
}

// The API path for a subject's tasks or points: /api/maintenance/items/<id>/tasks.
export function subjectApiPath(subject, what) {
  return `/api/maintenance/${PATHS[subject.kind] || "positions"}/${subject.id}/${what}`;
}

// A word for what isn't a position, shown beside its name ("item", "location").
export function subjectBadge(subject) {
  return subject && subject.kind !== "position" ? subject.kind : "";
}

// Where an item's work is now, in words: "fitted to Truck B", "in Store", "last at Area 1".
export function itemAtText(at) {
  if (!at) return "";
  if (at.how === "fitted" && at.position) {
    return `fitted to ${at.position.name}${at.location ? ` (${at.location.display || at.location.name})` : ""}`;
  }
  const where = at.location ? at.location.display || at.location.name : "";
  if (at.how === "placed") return where ? `in ${where}` : "placed";
  if (at.how === "last_at") return where ? `last at ${where}` : "not placed";
  return where;
}

// An item's task's setting for a spell in a store, in words (only for a calendar
// limit: use doesn't accrue in a store anyway).
export function whileStoredText(task) {
  if (task?.subject?.kind !== "item") return "";
  if (![task.unit, task.also_interval ? task.also_unit : null].some((u) => CALENDAR_UNITS.includes(u))) return "";
  return task.while_stored === "pause" ? "pauses while in store" : "keeps running in store";
}

// The kinds of work a work order can record: a replacement only at a position.
export function actionKinds(kinds, wo) {
  return wo?.can_replace === false ? kinds.filter((k) => k.id !== "replace") : kinds;
}

// Task kinds whose work is a check: it finds a problem, it doesn't replace anything.
const CHECK_OUTCOMES = ["on_condition", "failure_finding"];

// What a work order's close form starts at, from what the work is for. A round or an
// inspection: "inspect". A check (an on-condition or failure-finding task, or a task
// that asks for a reading): "checked" (sent as an inspection that found it OK). A
// fixed-interval task: a replacement where one can be recorded. Otherwise as before:
// a replacement at a position, a repair elsewhere. Only the form's starting point:
// the user picks what was really done.
export function defaultCloseKind(wo) {
  const atPosition = wo?.can_replace !== false;
  if (wo?.type === "inspection" || wo?.subject?.kind === "location") return "inspect";
  const tasks = wo?.tasks?.length ? wo.tasks : wo?.task ? [wo.task] : [];
  const read = new Set((wo?.reading_points || [])
    .filter((p) => p.task_id && (p.why || []).some((w) => w === "tool" || w === "trigger")).map((p) => p.task_id));
  const isCheck = (t) => CHECK_OUTCOMES.includes(t.outcome) || (!t.outcome && read.has(t.id));
  if (tasks.length && tasks.every(isCheck)) return "checked";
  return atPosition ? "replace" : "repair";
}

// A close form's action as the API takes it: "checked" is an inspection that found it OK.
export function closeActionKind(kind) {
  return kind === "checked" ? { kind: "inspect", finding: "ok" } : { kind };
}
