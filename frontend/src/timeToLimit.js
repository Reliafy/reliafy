// Time to the limit (Signals tab): the small pieces of logic behind the panel,
// kept apart from the screen so they can be tested.

export const PROCESSES = [
  { id: "wiener", label: "Random walk with drift", hint: "Can wobble down as well as up. The usual choice." },
  { id: "gamma", label: "Rises only", hint: "Wear that only ever goes up. Refuses a series that falls anywhere." },
];

// "about 40 days", "about 3 months": the same wording the server uses.
export function daysText(d) {
  if (d === null || d === undefined || !Number.isFinite(d)) return "?";
  if (d < 1) return d >= 1 / 24 ? `${Math.round(d * 24)} hours` : "under an hour";
  if (d < 60) return `${Math.round(d)} days`;
  if (d < 730) return `${Math.round(d / 30.4)} months`;
  return `${(d / 365.25).toFixed(1)} years`;
}

export function dateText(iso) {
  if (!iso) return "";
  const t = new Date(iso);
  return Number.isNaN(t.getTime()) ? "" : t.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function percent(p) {
  return p === null || p === undefined ? "–" : `${Math.round(p * 100)}%`;
}

// Where the "chance" rows start to matter: skip the horizons where the chance is still ~0 and
// stop at the first that is ~1, so the table is not a wall of 0% and 100%.
export function usefulHorizons(rows) {
  const out = [];
  for (const r of rows || []) {
    if (r.chance !== null && r.chance < 0.005 && (r.high === undefined || r.high < 0.02)) continue;
    out.push(r);
    if (r.chance >= 0.995 && (r.low === undefined || r.low >= 0.95)) break;
  }
  return out;
}

// The readings as CSV lines for a dataset: unit, age_days, value (what the server sends as `csv`).
export function datasetName(bandName, channelName) {
  return `${channelName || "Signal"} - ${bandName} (trend)`.slice(0, 120);
}

// Tracked-item measurements from a series: {t: age in days, y: value}, age counted from the first reading.
export function measurementsOf(rows) {
  return (rows || []).map((r) => ({ t: r.age_days, y: r.value }));
}
