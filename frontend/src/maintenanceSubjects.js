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

// The page a subject is on: /maintenance/items/<id>.
export function subjectPath(subject) {
  if (!subject?.id || !PATHS[subject.kind]) return null;
  return `/maintenance/${PATHS[subject.kind]}/${subject.id}`;
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
