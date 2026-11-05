// A measurement point's readings list (Reliafy Maintenance) keeps readings that
// were struck out or corrected, each with a status: "ok", "correction" (it
// replaces another), "voided" or "replaced" (by a correction).

const STRUCK = new Set(["voided", "replaced"]);

// The readings that count (for charts): struck-out ones left out.
export function liveReadings(readings) {
  return (readings || []).filter((r) => !STRUCK.has(r.status));
}

export function isStruck(reading) {
  return STRUCK.has(reading.status);
}

// What happened to a reading, in a few words; "" for one as entered.
export function readingStatusText(r, fmt = (d) => d) {
  const why = (text) => (text ? `: ${text}` : "");
  if (r.status === "voided") return `voided ${fmt(r.voided_on)}${why(r.void_reason)}`;
  if (r.status === "replaced") {
    const by = r.replaced_by || {};
    return `corrected ${fmt(r.voided_on)} to ${by.value} on ${by.when && by.when.length > 10 ? by.when : fmt(by.at)}${why(r.void_reason)}`;
  }
  if (r.status === "correction") {
    const was = r.replaces || {};
    return `correction of ${was.value} on ${was.when && was.when.length > 10 ? was.when : fmt(was.at)}${why(r.reason)}`;
  }
  return "";
}

// When a reading was taken, as the server shows it to its precision ("2026-10-19
// 10:14", "2026-10"), falling back to the formatted day for a date-only reading.
export function readingWhen(r, fmt = (d) => d) {
  if (r.when && r.when.length > 10) return r.when;
  if (r.precision === "year" || r.precision === "month") return r.when;
  return fmt(r.on || (r.at || "").slice(0, 10));
}

// "10:14" from a reading known to the minute or finer, for a time input.
export function readingClock(r) {
  return r.when && r.when.length >= 16 ? r.when.slice(11, 16) : "";
}
