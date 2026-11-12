// One sheet, several datasets: the Data step's "dataset" selector splits the
// sheet by a column, each value its own dataset named by the value (the
// server does the same on save: backend/services/datasets.py, split_by_column).
// One mapping for all: the same column roles and c meanings read every
// dataset. Rows with no value in the column are left out, with a warning.

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

const filled = (v) => v != null && String(v).trim() !== "";
const isNum = (v) => filled(v) && Number.isFinite(Number(String(v).trim()));
const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

// What a flow's mapping asks of every row, for the split's counts and checks:
//   needs:  [{ row, col, label?, range?: [xl, xr] }]: a value in col (a
//           number), or, with ``range``, a value in either end instead;
//   status: (cell) => code (0 failed, 1 running, -1 / 2 failed before / between)
//           or null where there is no c column (every row with a value failed);
//   n:      the count column, if any; failed: false where nothing fails (degradation);
//   items:  the item column, counted as "N items" where there's no failed count.
// Counts a group: { rows, failed, items }.
export function groupCounts(header, rows, spec) {
  const col = (name) => (name ? header.indexOf(name) : -1);
  const ni = col(spec.n);
  const out = { rows: rows.length, failed: 0, items: null };
  if (spec.items) out.items = new Set(rows.map((r) => (r[col(spec.items)] || "").trim()).filter(Boolean)).size;
  if (spec.failed === false) return out;
  const x = spec.needs?.find((n) => n.row === "x");
  const [xl, xr] = (x?.range || []).map(col);
  for (const r of rows) {
    const weight = ni >= 0 && isNum(r[ni]) ? Number(r[ni]) : 1;
    let code;
    if (spec.status) code = spec.status(r[col(spec.c)] ?? "");
    else if (x && !filled(r[col(x.col)]) && xl >= 0) code = filled(r[xr]) ? 2 : 1;
    else code = 0;
    if (code === 0 || code === -1 || code === 2) out.failed += weight;
  }
  return out;
}

// Each dataset's problems, beside the selector they concern: [{ row, text }],
// e.g. "Boiler feed pump: 1 row has no x". A dataset with nothing failed is
// a note (it saves, but has nothing to fit yet): { row, text, note: true }.
export function splitProblems(header, groups, spec) {
  const out = [];
  const col = (name) => (name ? header.indexOf(name) : -1);
  for (const g of groups) {
    for (const need of spec.needs || []) {
      const at = col(need.col);
      const ends = (need.range || []).map(col).filter((i) => i >= 0);
      if (at < 0 && !ends.length) continue;
      const label = need.label || need.row;
      let missing = 0;
      let text = 0;
      for (const r of g.rows) {
        const v = at >= 0 ? r[at] : "";
        if (filled(v)) { if (need.number !== false && !isNum(v)) text += 1; }
        else if (!ends.some((i) => filled(r[i]))) missing += 1;
      }
      if (missing) out.push({ row: need.row, text: `${g.value}: ${plural(missing, "row")} ${missing === 1 ? "has" : "have"} no ${label}` });
      if (text) out.push({ row: need.row, text: `${g.value}: ${plural(text, "row")} ${text === 1 ? "has" : "have"} ${label} that isn't a number` });
    }
    if (spec.failed !== false && groupCounts(header, g.rows, spec).failed === 0) {
      out.push({ row: spec.c ? "c" : "x", text: `${g.value}: nothing failed, so there's nothing to fit yet`, note: true });
    }
  }
  return out;
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

// The words beside the selector for rows left out.
export function blankWarning(blank) {
  if (!blank) return null;
  return `${plural(blank, "row")} ${blank === 1 ? "has" : "have"} no dataset name and ${blank === 1 ? "is" : "are"} left out`;
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
    : `This sheet makes ${n} datasets, but your free plan allows ${cap} saved datasets and only ${room} more ${room === 1 ? "fits" : "fit"}.`;
  return { cap, room, text };
}

// The summary line for one dataset: "24 rows · 3 failed" (or "· 5 items").
export function countWords(c) {
  const parts = [plural(c.rows, "row")];
  if (c.failed != null && c.items == null) parts.push(`${Number.isInteger(c.failed) ? c.failed : c.failed.toFixed(1)} failed`);
  else if (c.items != null) parts.push(plural(c.items, "item"));
  return parts.join(" · ");
}

// The file name a split's names add when a value's name is taken: its stem.
export const sourceStem = (name) => String(name || "").replace(/\.(csv|tsv|txt|xlsx|xlsm|xls)$/i, "").trim();
