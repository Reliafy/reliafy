// Picking systems out of a repairable dataset, and its downtime and cost
// columns. Pure, so `node --test src/` covers it.

// Every system id in the rows (a dataset rows window: { columns, rows }), in
// natural order ("P-2" before "P-10"), blanks left out.
export function systemIds(columns, rows, col) {
  const k = (columns || []).indexOf(col);
  if (k < 0) return [];
  const seen = new Set();
  for (const row of rows || []) {
    const v = Array.isArray(row) ? row[k] : row?.[col];
    if (v == null || String(v).trim() === "") continue;
    seen.add(String(v));
  }
  return [...seen].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

// A fit's chosen systems toggled: added, or taken out.
export function toggleSystem(chosen, sid) {
  const cur = chosen || [];
  return cur.includes(sid) ? cur.filter((s) => s !== sid) : [...cur, sid];
}

const DOWNTIME = /\b(downtime|down time|hours? (stopped|down|lost)|stopped|outage|lost hours)\b/;
const COST = /\b(cost|costs|total cost|dollars|\$|amount|spend)\b/;
const words = (name) => String(name ?? "").replace(/[_\-.()/#:]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();

// First guesses for the downtime and cost columns: a column named like
// "downtime hours" and one named like "total cost". A column already read as
// something else (the system, the time, the end of record) isn't offered.
// Only one cost column: a "parts cost" alone isn't the whole cost, so a
// name with "total" wins over the others, and none is guessed when several
// cost columns are there with no total.
export function guessCostColumns(columns, used = []) {
  const free = (columns || []).filter((c) => !used.includes(c));
  const downtime = free.find((c) => DOWNTIME.test(words(c))) || "";
  const costs = free.filter((c) => c !== downtime && COST.test(words(c)));
  const total = costs.find((c) => /\btotal\b/.test(words(c)));
  const cost = total || (costs.length === 1 ? costs[0] : "");
  return { downtime, cost };
}
