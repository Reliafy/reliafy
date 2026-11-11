// Field reports (Maintenance › Field reports): the words and small sums the
// page shows, kept apart from it so they can be tested.

export const FIELD_REPORTS_PATH = "/maintenance/field-reports";

export const STATUS_LABEL = { new: "New", parsed: "Read", done: "Done" };
export const STATUS_CHIP = { new: "chip-accent", parsed: "chip-warning", done: "chip-success" };

// "0:07", "12:34", "1:02:03".
export function clockLength(seconds) {
  const s = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const rest = String(s % 60).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${rest}` : `${m}:${rest}`;
}

const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// "2 photos, 1 recording (0:12), 1 file"; "" when a report is only notes.
export function contentsText(report) {
  const c = report.counts || {};
  const parts = [];
  if (c.photo) parts.push(plural(c.photo, "photo"));
  if (c.audio) parts.push(`${plural(c.audio, "recording")}${report.audio_seconds ? ` (${clockLength(report.audio_seconds)})` : ""}`);
  if (c.file) parts.push(plural(c.file, "file"));
  return parts.join(", ");
}

// What is still on its way from the phone: "2 of 5 attachments have arrived".
export function arrivingText(report) {
  if (report.complete || report.media_expected == null) return "";
  return `${report.media_arrived} of ${plural(report.media_expected, "attachment")} ${report.media_arrived === 1 ? "has" : "have"} arrived; `
    + "the rest are still on the phone.";
}

// "Deletes in 12 days", "Deletes today", "Kept", "Deleted".
export function keepText(report, today) {
  if (report.expired) return "Deleted";
  if (report.keep) return "Kept";
  if (!report.expires_on || !today) return "";
  const days = Math.round((Date.parse(`${report.expires_on}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86400000);
  if (days <= 0) return "Deletes today";
  return `Deletes in ${plural(days, "day")}`;
}

// The device's time as the person saw it: "12 Nov 2026, 09:30" (the offset dropped: it is their wall clock).
export function takenText(takenAt) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(String(takenAt || ""));
  if (!m) return "";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${Number(m[3])} ${months[Number(m[2]) - 1]} ${m[1]}, ${m[4]}:${m[5]}`;
}

export function matches(report, query) {
  const q = String(query || "").trim().toLowerCase();
  if (!q) return true;
  return [report.notes_preview, report.title, report.by_name, ...(report.about || []).map((a) => a.name)]
    .some((text) => String(text || "").toLowerCase().includes(q));
}
