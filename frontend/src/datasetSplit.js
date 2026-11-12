// One sheet, several datasets: the Data section's upload (New dataset) can
// split a file by a column, each value its own dataset named by the value (the
// server does the same on save: backend/services/datasets.py, split_by_column).
// Datasets are stored as their rows; the columns are read when fitting, so the
// split only counts rows. Rows with no value in the column are left out, with
// a warning.

// RFC 4180 CSV text → { header, rows } (cells as text, exactly as written).
export function parseCsv(text) {
  const src = String(text || "").replace(/^﻿/, "");
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < src.length; i += 1) {
    const ch = src[i];
    if (quoted) {
      if (ch === '"' && src[i + 1] === '"') { cell += '"'; i += 1; }
      else if (ch === '"') quoted = false;
      else cell += ch;
    } else if (ch === '"') quoted = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i += 1;
      row.push(cell); rows.push(row); row = []; cell = "";
    } else cell += ch;
  }
  if (cell !== "" || row.length) { row.push(cell); rows.push(row); }
  const [header = [], ...body] = rows;
  return { header: header.map((h) => h.trim()), rows: body.filter((r) => r.some((c) => c.trim())) };
}

// A file's text as a sheet: ``parseCsv``, or with ``noHeader`` every row is
// data and the columns are named "col 1", "col 2", … (as the server names them).
export function readSheet(text, noHeader = false) {
  if (!noHeader) return parseCsv(text);
  const { header, rows } = parseCsv(text);
  const all = header.length && header.some((h) => h) ? [header, ...rows] : rows;
  const width = Math.max(0, ...all.map((r) => r.length));
  return { header: Array.from({ length: width }, (_, i) => `col ${i + 1}`), rows: all };
}

// Each dataset the split makes, for the list before saving:
// [{ value, name, rows }] plus ``blank`` (rows with no value, left out).
export function splitPlan(sheet, column, taken, source) {
  const { groups, blank } = splitSheet(sheet, column);
  const names = splitNames(groups.map((g) => g.value), taken, source);
  return { blank, parts: groups.map((g, i) => ({ value: g.value, name: names[i], rows: g.rows.length })) };
}

// The sheet's rows grouped by ``column``: { groups: [{ value, rows }], blank }
// in the order each value first appears; ``blank``: rows with no value.
export function splitSheet(sheet, column) {
  const at = sheet.header.indexOf(column);
  if (at < 0) return { groups: [], blank: 0 };
  const byValue = new Map();
  let blank = 0;
  for (const row of sheet.rows) {
    const value = (row[at] || "").trim();
    if (!value) { blank += 1; continue; }
    if (!byValue.has(value)) byValue.set(value, []);
    byValue.get(value).push(row);
  }
  return { groups: [...byValue.entries()].map(([value, rows]) => ({ value, rows })), blank };
}

// Each value's dataset name: the value, or "<value> – <source>" when the
// workspace already has a dataset of that name (as the server names them).
export function splitNames(values, taken, source) {
  const used = new Set([...taken].map((t) => String(t).trim().toLowerCase()));
  return values.map((value) => {
    let name = value.slice(0, 200);
    if (used.has(name.toLowerCase()) && source) name = `${value} – ${source}`.slice(0, 200);
    const base = name;
    for (let k = 2; used.has(name.toLowerCase()); k += 1) name = `${base} (${k})`;
    used.add(name.toLowerCase());
    return name;
  });
}

// The warning for rows left out: "Rows with no Equipment are left out: 4".
export function blankWarning(blank, column = "") {
  if (!blank) return null;
  return `Rows with no ${column || "value"} are left out: ${blank}`;
}

// The Free plan's room for ``n`` new datasets (billing from GET /api/billing):
// null when they all fit (or there is no cap), else { cap, room, text }.
export function splitRoom(billing, n) {
  if (!billing || !billing.billing_enabled || billing.admin) return null;
  const cap = billing.plan_caps?.datasets;
  const used = billing.usage?.datasets;
  if (cap == null || used == null) return null;
  const room = Math.max(0, cap - used);
  if (n <= room) return null;
  const text = room === 0
    ? `You've reached the free-plan limit of ${cap} saved datasets, so none of these ${n} fit.`
    : `This file makes ${n} datasets, but your free plan allows ${cap} saved datasets: you can save ${room} more.`;
  return { cap, room, text };
}

// The file name a split's names add when a value's name is taken: its stem.
export const sourceStem = (name) => String(name || "").replace(/\.(csv|tsv|txt|xlsx|xlsm|xls)$/i, "").trim();
