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
    return `corrected ${fmt(r.voided_on)} to ${by.value} on ${fmt(by.at)}${why(r.void_reason)}`;
  }
  if (r.status === "correction") {
    const was = r.replaces || {};
    return `correction of ${was.value} on ${fmt(was.at)}${why(r.reason)}`;
  }
  return "";
}
