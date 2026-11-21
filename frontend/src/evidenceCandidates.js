// The evidence a decision could link, as GET /api/maintenance/rcm/evidence-candidates lists it
// (backend/maintenance/rcm_evidence.py): searched and filtered here as the user types, and grouped
// by where each comes from (this failure mode, this position, its class, the library).

export const SCOPE_ORDER = ["mode", "position", "class", "library"];

// The candidates that hold every word typed (label or meta, any order and case) and are of `kind`
// ("" or null: every kind).
export function filterCandidates(candidates, q = "", kind = "") {
  const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
  return (candidates || []).filter((c) => {
    if (kind && c.kind !== kind) return false;
    const text = `${c.label || ""} ${c.meta || ""}`.toLowerCase();
    return words.every((w) => text.includes(w));
  });
}

// [{scope, words, items}] in scope order, empty groups left out.
export function groupByScope(candidates) {
  const out = [];
  for (const scope of SCOPE_ORDER) {
    const items = (candidates || []).filter((c) => c.scope === scope);
    if (items.length) out.push({ scope, words: items[0].scope_words || scope, items });
  }
  return out;
}

// The kind filter's options: every kind, then each kind found, with how many.
export function kindOptions(kinds) {
  const total = (kinds || []).reduce((n, k) => n + (k.count || 0), 0);
  return [{ value: "", label: `Every kind (${total})` },
    ...(kinds || []).map((k) => ({ value: k.id, label: `${k.label} (${k.count})` }))];
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const day = (iso) => {
  const [y, m, d] = String(iso).slice(0, 10).split("-").map(Number);
  return y && m && d ? `${d} ${MONTHS[m - 1]} ${y}` : String(iso);
};

// A window {since?, until?, lives?, failures?} in words, as the server says it:
// "52 lives fitted since 1 Jan 2022 (2 failed)"; "" with none.
export function windowWords(w) {
  if (!w || (!w.since && !w.until)) return "";
  const span = w.since && w.until ? `between ${day(w.since)} and ${day(w.until)}`
    : w.since ? `since ${day(w.since)}` : `up to ${day(w.until)}`;
  const head = w.lives != null ? `${w.lives.toLocaleString("en-AU")} li${w.lives === 1 ? "fe" : "ves"} fitted ${span}`
    : `lives fitted ${span}`;
  return w.failures != null ? `${head} (${w.failures.toLocaleString("en-AU")} failed)` : head;
}

// A window from two date fields ("" each: none), or null with neither.
export function windowFrom(since, until) {
  const w = {};
  if (since) w.since = since;
  if (until) w.until = until;
  return Object.keys(w).length ? w : null;
}

// What a decision saves as its evidence: {type, id} with the window when it has one.
export function evidenceBody(value) {
  if (!value?.type || !value?.id) return null;
  return { type: value.type, id: value.id, ...(value.window ? { window: value.window } : {}) };
}
