// Shared Instrument-design helpers: distribution accent colours, a reliability
// sparkline path, a stable per-model seed, and relative-time formatting.

// Accent colour per distribution family (keyed by the first word of the
// backend's distribution name, so "Weibull PH" -> Weibull blue).
export const DIST_COLORS = {
  Weibull: "#2f6df6",
  Lognormal: "#7c4dff",
  Exponential: "#0ea5e9",
  Gamma: "#e0883b",
  Normal: "#16a34a",
  Logistic: "#7c4dff",
  Gumbel: "#0ea5e9",
  Cox: "#6c727c",
};

export function distColor(distribution = "") {
  const family = String(distribution).split(/[\s(]/)[0];
  return DIST_COLORS[family] || "#2f6df6";
}

// API timestamps are UTC. If the ISO string carries no timezone (naive, e.g.
// after a MongoDB round-trip) treat it as UTC, not the browser's local zone —
// otherwise every time reads off by the viewer's UTC offset.
export function parseTimestamp(iso) {
  if (iso == null) return new Date(NaN);
  if (typeof iso === "string" && !/([zZ]|[+-]\d{2}:?\d{2})$/.test(iso)) {
    return new Date(iso + "Z");
  }
  return new Date(iso);
}

// "5 days ago" style relative time from an ISO timestamp.
export function relativeTime(iso) {
  if (!iso) return "—";
  const then = parseTimestamp(iso).getTime();
  const secs = Math.max(0, (Date.now() - then) / 1000);
  const day = 86400;
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)} min ago`;
  if (secs < day) return `${Math.floor(secs / 3600)} h ago`;
  const days = Math.floor(secs / day);
  if (days === 1) return "yesterday";
  if (days < 30) return `${days} days ago`;
  if (days < 365) return `${Math.floor(days / 30)} mo ago`;
  return `${Math.floor(days / 365)} yr ago`;
}
