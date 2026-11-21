// Recording work with no work order (work orders turned off, workOrdersFlag.js):
// the same actions a work order's close records, sent to POST /api/maintenance/work-done.
// Pure, so the tests can hold it.
import { doneText } from "./maintenanceOrders.js";

// A position as the shared "what was done" form (WorkDoneForm.jsx) reads a work
// order: what's fitted, its failure modes (its own, and those seen at like
// positions), its parts list. It starts like a breakdown: nothing picked, and a
// replacement asks whether it failed, so nothing is recorded by default.
export function positionWorkSubject(p) {
  if (!p?.id) return null;
  const ref = { id: p.id, name: p.name };
  return {
    type: "corrective", subject: { kind: "position", ...ref }, position: ref, fitted: p.fitted || null,
    failure_modes: p.failure_modes || [], class_failure_modes: p.class_failure_modes || [],
    suggested_parts: p.parts_list || [], can_replace: true, inside_positions: [],
  };
}

// The body for what was done at a position: the form's payload (a close's: actions,
// on, notes, readings) with where it was done. A work package's not_done has no place here.
export function workDoneBody(positionId, payload = {}) {
  const { not_done: _skip, ...rest } = payload;
  return { position_id: positionId, ...rest };
}

// The body for a task recorded as done on a day (renewing it, as closing its work order would).
export function taskDoneBody(task, on) {
  return on ? { task_id: task.id, on } : { task_id: task.id };
}

// What recording a task done says afterwards.
export function taskDoneText(view, fmt = (d) => d) {
  const next = view?.task?.next_due;
  const on = view?.on;
  return `Recorded as done${on ? ` on ${fmt(on)}` : ""}.${next ? ` Next due ${fmt(next)}.` : ""}`;
}

const KIND_WORDS = { corrective: "Repair or replacement", preventive: "Planned task", inspection: "Inspection", other: "Other work" };

// The "Work done" history (work orders turned off): the closed ones, newest first,
// each { id, on, title, what (what was done, when the server says), kind }.
// Anything not closed (cancelled, or open from before) is left out.
export function workDoneRows(workOrders = []) {
  return (workOrders || [])
    .filter((w) => w.status === "closed")
    .map((w) => ({
      id: w.id, on: w.closed || w.opened, title: w.title,
      what: (w.done || []).length ? doneText(w) : "", kind: KIND_WORDS[w.type] || w.type || "",
    }))
    .sort((a, b) => (a.on < b.on ? 1 : a.on > b.on ? -1 : 0));
}
