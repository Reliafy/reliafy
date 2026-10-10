// Simulation run history (#112) and runtime quotes (#286): the words the runs
// views use, kept here so they can be tested without a browser.
import { pctAt, pctDigits } from "./components/availabilityPrecision.js";

// "0.4 s", "12 s", "3 min 20 s": how long a run took.
export function runtimeText(s) {
  if (s == null || !Number.isFinite(s)) return "—";
  if (s < 10) return `${s.toFixed(1)} s`;
  if (s < 59.5) return `${Math.round(s)} s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s - 60 * m);
  if (m >= 60) {
    const h = Math.floor(m / 60);
    return `${h} h ${m - 60 * h} min`;
  }
  return rest ? `${m} min ${rest} s` : `${m} min`;
}

// "You", a teammate's name, or "A teammate".
export const byText = (row) => (row?.by?.you ? "You" : row?.by?.name || "A teammate");

// "App", "Claude (MCP)", or "—" for a run from before this was recorded.
export const viaText = (row) => row?.via?.label || "—";

// A run's status as a chip: colour for meaning only (a failure is red, a run
// still going is the accent; a finished run is plain).
export function statusChip(status) {
  switch (status) {
    case "done":
      return { tone: "neutral", label: "Done" };
    case "failed":
      return { tone: "danger", label: "Failed" };
    case "running":
      return { tone: "accent", label: "Running" };
    case "queued":
      return { tone: "accent", label: "Queued" };
    default:
      return { tone: "neutral", label: status || "—" };
  }
}

// Decimals that show an availability to its interval's precision.
export function availabilityDigits(a) {
  if (!a) return 3;
  const half = a.lower != null && a.upper != null ? (a.upper - a.lower) / 2 : null;
  return half ? Math.max(3, pctDigits(half)) : 3;
}

// "99.968%" and "99.951–99.982%": a run's window availability and its interval.
export function availabilityText(a, digits = null) {
  if (!a || a.value == null) return { value: "—", interval: null };
  const d = digits ?? availabilityDigits(a);
  const interval =
    a.lower != null && a.upper != null ? `${pctAt(a.lower, d).replace("%", "")}–${pctAt(a.upper, d)}` : null;
  return { value: pctAt(a.value, d), interval };
}

// "12 s · quoted about 15 s, up to 40 s" (the quote only once the run is done).
export function runtimeVsQuote(row) {
  const took = runtimeText(row?.runtime_s);
  const quoted = row?.quote?.text;
  if (row?.runtime_s == null) return quoted ? `Quoted ${quoted}` : "—";
  return quoted ? `${took} · quoted ${quoted}` : took;
}

// The comparison's answer: the spread of the runs' window availabilities, and
// whether their intervals overlap (all share a common range).
export function compareSummary(runs) {
  const rows = (runs || []).filter((r) => r?.availability?.value != null);
  if (rows.length < 2) return null;
  const values = rows.map((r) => r.availability.value);
  const lows = rows.map((r) => r.availability.lower).filter((v) => v != null);
  const highs = rows.map((r) => r.availability.upper).filter((v) => v != null);
  const withBands = lows.length === rows.length && highs.length === rows.length;
  const digits = Math.max(...rows.map((r) => availabilityDigits(r.availability)));
  return {
    count: rows.length,
    low: pctAt(Math.min(...values), digits),
    high: pctAt(Math.max(...values), digits),
    overlap: withBands ? Math.max(...lows) <= Math.min(...highs) : null,
  };
}

// The queue status line while a simulation job is in flight (#146, #286):
// "Queued — 2 ahead of you, starts in about 40 s. Then about 15 s, up to 40 s."
export function jobStatusLine(job) {
  if (!job) return "";
  const quote = job.quote?.text;
  if (job.status === "running") return quote ? `Running the simulation — ${quote}…` : "Running the simulation…";
  const ahead = job.queue_position;
  const head = ahead == null || ahead <= 0 ? "Queued — you're next" : `Queued — ${ahead} ahead of you`;
  const wait = ahead > 0 && job.wait_text ? `, starts in ${job.wait_text}` : "";
  return quote ? `${head}${wait}. Then ${quote}.` : `${head}${wait}…`;
}

// "/rbds/runs?rbd=…": a diagram's runs.
export const runsPath = (rbdId = null) => (rbdId ? `/rbds/runs?rbd=${encodeURIComponent(rbdId)}` : "/rbds/runs");
