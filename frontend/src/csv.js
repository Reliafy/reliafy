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
