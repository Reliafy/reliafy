// What a task by use counts: its measurement (a counter on its position, above
// or below it, or on the item fitted there), shown and changed in the task's
// dialogs, and the choice a move asks for when the measurement doesn't fit the
// new position (GET /api/maintenance/tasks/:id/measurement, and a move's 409
// needs_choice, carry the same view: {task_id, name, unit, last_done,
// last_done_reading, last_done_reading_estimated, measurement, fits, choices,
// suggested_point_id}).

// How a measurement stands to the place the task is on (or would move to).
export const RELATION_WORDS = {
  here: "on this position",
  above: "on a position above",
  below: "on a position below",
  "fitted item": "on the fitted item",
};

// A number as the readings show it: grouped, at most one decimal place.
export function readingNumber(value) {
  if (value == null || !Number.isFinite(Number(value))) return "";
  return Number(value).toLocaleString("en-AU", { maximumFractionDigits: 1 });
}

export function readingText(value, unit) {
  const n = readingNumber(value);
  return n ? `${n}${unit ? ` ${unit}` : ""}` : "";
}

// "Engine hours on Truck 12" (or "hours while fitted" for an item's use where it's been fitted).
export function pointLabel(p) {
  if (!p) return "";
  if (p.derived) return `${p.name} (the use it has had where it was fitted)`;
  return p.on?.name ? `${p.name} on ${p.on.name}` : p.name;
}

// One choice as a list shows it: "Engine hours on Truck 14 · reads 5,600 hours".
export function choiceLabel(c) {
  const reads = c.reading != null ? ` · reads ${readingText(c.reading, c.unit)}` : " · no readings yet";
  return `${pointLabel(c)}${reads}`;
}

// The reading a choice had when the task was last done, in words.
export function atLastDoneText(c, unit) {
  const v = c?.at_last_done;
  if (!v || v.value == null) return "";
  return `${v.estimated ? "about " : ""}${readingText(v.value, unit || c.unit)}`;
}

// What the move dialog starts on for a task: switch to the suggested
// measurement there (its reading worked out from the date), else keep.
export function startChoice(view) {
  const point = view?.suggested_point_id || view?.choices?.[0]?.id || "";
  return {
    mode: point ? "switch" : "keep",
    pointId: point,
    readingMode: "estimate",
    reading: "",
    interval: "",
    calendarUnit: "months",
  };
}

// A dialog's choice checked: the words saying what's missing, or null.
export function checkChoice(state, view) {
  if (state.mode === "switch") {
    if (!state.pointId) return "Pick the measurement it should count.";
    if (view?.last_done && state.readingMode === "enter") {
      const n = Number(String(state.reading).trim());
      if (String(state.reading).trim() === "" || !Number.isFinite(n)) {
        return "Enter the reading when it was last done, or work it out from the date.";
      }
    }
    return null;
  }
  if (state.mode === "calendar") {
    const n = Number(String(state.interval).trim());
    if (String(state.interval).trim() === "" || !Number.isFinite(n) || n <= 0) return "Say how often it falls due on the calendar.";
    return null;
  }
  return state.mode === "keep" ? null : "Pick what it should count.";
}

// The choice as a move takes it ({choice: keep | switch | calendar, ...}).
export function choiceBody(state, view) {
  if (state.mode === "switch") {
    const body = { choice: "switch", point_id: state.pointId };
    if (view?.last_done && state.readingMode === "enter") body.last_done_reading = Number(String(state.reading).trim());
    return body;
  }
  if (state.mode === "calendar") return { choice: "calendar", interval: Number(String(state.interval).trim()), unit: state.calendarUnit || "months" };
  return { choice: "keep" };
}

// The batch again with one operation's measurement filled in (merged with any
// choices it carries already, from an earlier question in the same drop).
export function withMeasurement(operations, index, measurement) {
  return operations.map((op, i) => (i !== index ? op : {
    ...op,
    args: { ...op.args, measurement: { ...(op.args?.measurement && typeof op.args.measurement === "object" ? op.args.measurement : {}), ...measurement } },
  }));
}

// What the measurement field in a task's dialog says now:
// {counts, reads, lastDone} lines (empty strings where there's nothing to say).
export function measurementLines(view, fmtDate = (d) => d) {
  if (!view?.by_use) return { counts: "", reads: "", lastDone: "" };
  const m = view.measurement;
  const counts = m ? pointLabel(m) : `Nothing yet: no ${view.unit} counter here`;
  const reads = m && !m.derived && m.reading != null
    ? `Reads ${readingText(m.reading, m.unit || view.unit)} (${fmtDate(m.read_on)})`
    : m && !m.derived ? "No readings yet" : "";
  let lastDone = "";
  if (view.last_done) {
    lastDone = view.last_done_reading != null
      ? `Last done ${fmtDate(view.last_done)} at ${readingText(view.last_done_reading, view.unit)}${view.last_done_reading_estimated ? " (an estimate, worked out from the date)" : ""}`
      : `Last done ${fmtDate(view.last_done)} (no reading then)`;
  }
  return { counts, reads, lastDone };
}

// The measurement field's change as the task update takes it: {point_id,
// last_done_reading?}, or null when nothing changed. `pick` is the point id
// chosen ("" : automatic, the position's own counter in the unit).
export function fieldBody(view, pick, readingMode, reading) {
  const was = view?.chosen ? view?.measurement?.id || "" : "";
  if (pick === was && readingMode !== "enter") return null;
  const body = { point_id: pick };
  if (view?.last_done && readingMode === "enter") body.last_done_reading = Number(String(reading).trim());
  return body;
}
