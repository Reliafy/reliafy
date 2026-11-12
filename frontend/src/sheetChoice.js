// Which sheet of a workbook the picker opens on. Adding a second part from
// the same workbook (life data, then its readings) should open on a sheet not
// used yet, not on the first one again. The sheets used are remembered for
// this page's life, by the workbook's name, size and date.

const used = new Map(); // workbook key → Set of sheet names

export function workbookKey(file) {
  if (!file) return "";
  return `${file.name || ""}|${file.size ?? ""}|${file.lastModified ?? ""}`;
}

export function rememberSheet(file, sheet) {
  const key = workbookKey(file);
  if (!key || !sheet) return;
  if (!used.has(key)) used.set(key, new Set());
  used.get(key).add(sheet);
}

export const usedSheets = (file) => used.get(workbookKey(file)) || new Set();

// The sheet to open on: the first with data not used yet, else the first
// with data, else the first. ``sheets``: [{ name, rows }].
export function nextSheet(sheets, usedNames = new Set()) {
  const list = sheets || [];
  const withData = list.filter((s) => s.rows > 0);
  return withData.find((s) => !usedNames.has(s.name)) || withData[0] || list[0] || null;
}

// For tests: forget every workbook.
export function forgetSheets() {
  used.clear();
}
