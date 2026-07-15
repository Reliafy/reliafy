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

// Deterministic 0..1 value from a string — used to give each model a distinct
// (but stable) sparkline shape without storing anything.
export function seedFromString(str = "") {
  let h = 0;
  for (let i = 0; i < str.length; i++) {
    h = (h * 31 + str.charCodeAt(i)) >>> 0;
  }
  return (h % 1000) / 1000;
}

// Smooth reliability curve R(t): 1 -> 0 as an SVG path. `shape` skews the
// steepness so each model's sparkline looks distinct.
export function reliabilityPath(w, h, shape = 0.5, pad = 0) {
  const n = 28;
  const k = 1.2 + shape * 2.6; // Weibull-ish shape
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const x = i / n;
    const R = Math.exp(-Math.pow(x / (0.55 + shape * 0.3), k));
    const px = pad + x * (w - pad * 2);
    const py = pad + (1 - R) * (h - pad * 2);
    pts.push([px.toFixed(1), py.toFixed(1)]);
  }
  return "M " + pts.map((p) => `${p[0]},${p[1]}`).join(" L ");
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
