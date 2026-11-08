// When a task falls due (Nov 2026): a task's start is the date it first falls due, then
// every interval after. Without one, it's one interval from when it was made (or last
// done). The server sends next_due, and first_due while a date set for it stands.
import { dayText } from "./measuringPoint.js";

// "first due 1 Oct 2027" (a date set for it), "next due 9 Nov 2027", or "" (by use, raised
// only by an event, or no date yet).
export function dueText(task) {
  if (!task) return "";
  if (task.first_due) return `first due ${dayText(task.first_due)}`;
  return task.next_due ? `next due ${dayText(task.next_due)}` : "";
}

// Whether a task takes a start date: one by the calendar (a task by use falls due on its counter).
const CALENDAR = new Set(["days", "weeks", "months", "years"]);
export function takesStart(task) {
  if (!task) return false;
  return CALENDAR.has(task.unit) || CALENDAR.has(task.also_unit);
}

// Why a typed start date can't be kept ("" when it can; empty is fine: no date).
export function startWhy(value) {
  const v = String(value || "").trim();
  if (!v) return "";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(v) || Number.isNaN(new Date(`${v}T00:00:00`).getTime())) {
    return "Enter a date, like 2027-10-01.";
  }
  return "";
}

// The body that sets it ({start: "2027-10-01"}), or clears it ({start: null}: back to one
// interval from when it was last done, or made).
export function startBody(value) {
  const v = String(value || "").trim();
  return { start: v || null };
}

// The task a save just made: in the read after it (its tasks), not among the ids before,
// by name when several are new. null when none is.
export function madeTask(beforeIds, after, name = "") {
  const before = new Set(beforeIds || []);
  const fresh = [...(after?.tasks || []), ...(after?.decision?.tasks || [])].filter((t) => t?.id && !before.has(t.id));
  if (!fresh.length) return null;
  const wanted = String(name || "").trim().toLowerCase();
  return fresh.find((t) => String(t.name || "").trim().toLowerCase() === wanted) || fresh[0];
}
