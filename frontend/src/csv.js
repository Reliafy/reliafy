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

// A file name for a download: the thing's name, with characters a file name
// can't hold removed, then what's in it ("reliability curve"), then .csv.
export function csvFileName(name, what = "") {
  // eslint-disable-next-line no-control-regex
  const stem = String(name ?? "").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "").replace(/\s+/g, " ").trim().replace(/\.+$/, "");
  return [stem, what].filter(Boolean).join(" ").trim().concat(".csv").replace(/^\.csv$/, "download.csv");
}

// The one way the app saves a table it already has as a CSV file ("Download
// CSV"). ``rows`` is [[header…], [cell…], …]; numbers go in as they are, at
// full precision (String(n) gives the shortest text that reads back to the
// same number), so a spreadsheet gets what the page computed, not the
// rounded figures on screen. A UTF-8 byte-order mark goes first so Excel
// reads units such as "°C" and "λ" correctly.
export function downloadCsv(rows, filename) {
  if (typeof document === "undefined") return filename;
  const blob = new Blob(["﻿" + toCsv(rows) + "\n"], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}
