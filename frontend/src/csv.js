// CSV export helpers shared by the pages that download a table.

// Text a spreadsheet would read as a formula: a leading = + - @, or a tab /
// carriage return before one. Such cells are prefixed with ' so the
// spreadsheet shows them as text. Numbers are left as they are.
const FORMULA_START = /^[=+\-@\t\r]/;

export function csvCell(v) {
  let s = String(v ?? "");
  if (typeof v === "string" && FORMULA_START.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

export function toCsv(rows) {
  return rows.map((r) => r.map(csvCell).join(",")).join("\n");
}

// A number for an export: 4 significant figures, like the screen, so a
// spreadsheet gets 1 rather than 0.9999999999999997 (floating-point noise
// read as precision). Kept a plain number (no thousands separators) so it
// stays a number in the spreadsheet; anything else is passed through.
export function csvNumber(v, sig = 4) {
  if (typeof v !== "number" || !Number.isFinite(v)) return v;
  return Number(v.toPrecision(sig));
}
