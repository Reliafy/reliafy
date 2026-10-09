// Pure helpers for the degradation wizard (no React, so `node --test` runs them).

// Distinct values in `column`, counted over every row: the server's count
// (`n_unique`, from /api/columns or a dataset's detail) when it sent one,
// otherwise the preview's own rows, but only when the preview holds every row.
// null when the count isn't known, so the wizard says nothing rather than
// warning off a first-rows sample that shows one item.
export function distinctCount(csv, column) {
  if (!csv || !column) return null;
  const idx = (csv.columns || []).indexOf(column);
  if (idx === -1) return null;
  const n = csv.n_unique?.[idx];
  if (Number.isFinite(n)) return n;
  const rows = csv.preview || [];
  if (csv.n_rows != null && rows.length < csv.n_rows) return null;
  return new Set(rows.map((r) => r[idx]).filter((v) => v !== null && v !== undefined && v !== "")).size;
}

// A dataset the wizard can fit: an item id, a time and a measurement column.
export const usableForDegradation = (d) => (d?.n_columns ?? 0) >= 3;

// A column name's words, lower-case: "wear_mm" → ["wear", "mm"],
// "Time (h)" → ["time", "h"], "wearMm" → ["wear", "mm"].
function words(name) {
  return String(name ?? "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-zµ°%]+/)
    .filter(Boolean);
}

// The text inside brackets, if the name has any: "Wear (mm)" → "mm".
function bracketed(name) {
  const m = String(name ?? "").match(/[([]\s*([^)\]]+?)\s*[)\]]/);
  return m ? m[1] : null;
}

// Time units in the pickers' spelling, keyed by the ways columns write them.
const TIME_WORDS = {
  Seconds: ["s", "sec", "secs", "second", "seconds"],
  Minutes: ["min", "mins", "minute", "minutes"],
  Hours: ["h", "hr", "hrs", "hour", "hours"],
  Days: ["d", "day", "days"],
  Weeks: ["wk", "wks", "week", "weeks"],
  Months: ["mo", "mon", "month", "months"],
  Years: ["y", "yr", "yrs", "year", "years"],
  Cycles: ["cyc", "cycle", "cycles"],
  Kilometres: ["km", "kms", "kilometre", "kilometres", "kilometer", "kilometers"],
  Miles: ["mi", "mile", "miles"],
  Operations: ["op", "ops", "operation", "operations"],
};
// The time-unit field's suggestions.
export const TIME_UNITS = Object.keys(TIME_WORDS);
const TIME_BY_WORD = Object.fromEntries(
  Object.entries(TIME_WORDS).flatMap(([unit, ws]) => ws.map((w) => [w, unit]))
);

// The time unit a column's name gives, in the pickers' spelling, or "".
// "hours" → "Hours", "time_h" → "Hours", "Age (days)" → "Days". A lone
// letter counts only beside another word ("time_h"), never as the whole name.
export function guessTimeUnit(column) {
  const inside = bracketed(column);
  if (inside) {
    const unit = TIME_BY_WORD[inside.toLowerCase()];
    if (unit) return unit;
  }
  const ws = words(column);
  for (let i = ws.length - 1; i >= 0; i--) {
    const w = ws[i];
    if (w.length === 1 && ws.length === 1) continue;
    if (TIME_BY_WORD[w]) return TIME_BY_WORD[w];
  }
  return "";
}

// Measurement units as they're usually written, keyed by lower-case spelling.
const MEASURE_UNITS = Object.fromEntries(
  [
    "mm", "cm", "m", "µm", "um", "in", "inch", "mil", "mils", "%", "pct", "percent",
    "kg", "g", "n", "kn", "mpa", "kpa", "pa", "psi", "bar", "v", "mv", "a", "ma",
    "ohm", "ohms", "db", "hz", "khz", "c", "degc", "°c", "f", "degf", "°f", "k", "ppm", "w", "kw",
  ].map((u) => [u, u])
);
// How to write the ones that aren't simply lower-case.
const MEASURE_SPELLING = {
  um: "µm", inch: "in", mils: "mil", pct: "%", percent: "%", n: "N", kn: "kN", mpa: "MPa",
  kpa: "kPa", pa: "Pa", v: "V", mv: "mV", a: "A", ma: "mA", ohm: "Ω", ohms: "Ω", db: "dB",
  hz: "Hz", khz: "kHz", c: "°C", degc: "°C", "°c": "°C", f: "°F", degf: "°F", "°f": "°F",
  k: "K", w: "W", kw: "kW",
};

// The measurement unit a column's name gives, or "". "wear_mm" → "mm",
// "Crack (µm)" → "µm", "temp_c" → "°C". Brackets are taken as written; a bare
// unit word counts only when it's the last word after another ("wear_mm", not
// "mm" or "m_wear").
export function guessMeasurementUnit(column) {
  const inside = bracketed(column);
  if (inside) return MEASURE_SPELLING[inside.toLowerCase()] || inside;
  const ws = words(column);
  if (ws.length < 2) return "";
  const last = ws[ws.length - 1];
  if (!MEASURE_UNITS[last]) return "";
  return MEASURE_SPELLING[last] || last;
}
