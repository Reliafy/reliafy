// A fleet forecast's items in bulk: a block pasted from Excel (tab or comma
// separated) or a CSV / Excel file read into the same rows, its columns mapped
// by header, then each row read into an item with the reason any row is left
// out. Pure, so `node --test src/` covers it (FleetItemsImport.jsx is the panel).

import { CONVERTIBLE_UNITS, guessUnit, timeUnitOf } from "./datasetGuess.js";

export const MAX_ITEMS = 500; // a fleet's limit (backend/services/fleet.py)

// Hours in one of each calendar unit, to convert ages typed in another.
const HOURS = { Minutes: 1 / 60, Hours: 1, Days: 24, Weeks: 168, Months: 730.5, Years: 8766 };
// Days in one period, for the period labels the server knows (fleet.py PERIOD_DAYS).
const PERIOD_DAYS = { day: 1, week: 7, month: 30.4375, quarter: 91.3125, year: 365.25 };

export function periodDays(label) {
  const key = String(label || "").trim().toLowerCase();
  return PERIOD_DAYS[key] ?? PERIOD_DAYS[key.replace(/s$/, "")] ?? null;
}

// ---- Reading the block ------------------------------------------------------------

// The separator of a pasted block: a tab (Excel, Sheets), else ; or , (CSV).
export function sniffDelimiter(text) {
  const first = String(text || "").split(/\r?\n/).find((l) => l.trim()) || "";
  if (first.includes("\t")) return "\t";
  const count = (ch) => first.split(ch).length - 1;
  return count(";") > count(",") ? ";" : ",";
}

// Rows of cells, quotes understood ("Pump, east" is one cell); blank lines dropped.
export function splitRows(text, delimiter = sniffDelimiter(text)) {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const s = String(text || "");
  const end = () => { row.push(cell.trim()); cell = ""; };
  for (let i = 0; i < s.length; i += 1) {
    const ch = s[i];
    if (quoted) {
      if (ch === "\"" && s[i + 1] === "\"") { cell += "\""; i += 1; }
      else if (ch === "\"") quoted = false;
      else cell += ch;
    } else if (ch === "\"" && cell.trim() === "") {
      quoted = true;
      cell = "";
    } else if (ch === delimiter) {
      end();
    } else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && s[i + 1] === "\n") i += 1;
      end();
      if (row.some((c) => c !== "")) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  end();
  if (row.some((c) => c !== "")) rows.push(row);
  return rows;
}

// "1,200", "1 200", "1200 h", "3.5 years": { value, unit } (unit "" when none
// is written); null when the cell isn't a number.
export function readNumber(cell) {
  const text = String(cell ?? "").trim();
  if (!text) return null;
  const m = text.match(/^([-+]?[\d\s,.]*\d(?:[.,]\d+)?(?:e[-+]?\d+)?)\s*([A-Za-z]*\.?)$/i);
  if (!m) return null;
  let num = m[1].replace(/\s/g, "");
  // "1,200" / "1,200.5": thousands; "3,5" alone: a decimal comma.
  if (/^[-+]?\d{1,3}(,\d{3})+(\.\d+)?$/.test(num)) num = num.replace(/,/g, "");
  else if (/^[-+]?\d+,\d+$/.test(num)) num = num.replace(",", ".");
  const value = Number(num);
  if (!Number.isFinite(value)) return null;
  const unit = m[2] ? timeUnitOf(m[2]) || m[2] : "";
  return { value, unit };
}

const MONTHS = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, sept: 8, oct: 9, nov: 10, dec: 11 };

// A date cell as a UTC day (ms), or null: 2024-03-15, 15/03/2024 (day first),
// 15-Mar-2024, 15 March 2024, Mar 15 2024. An ISO time after the date is ignored.
export function readDate(cell) {
  const t = String(cell ?? "").trim();
  if (!t) return null;
  let y; let mo; let d;
  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?$/);
  if (m) [y, mo, d] = [+m[1], +m[2] - 1, +m[3]];
  else if ((m = t.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/))) [d, mo, y] = [+m[1], +m[2] - 1, +m[3]];
  else if ((m = t.match(/^(\d{1,2})[\s-]([A-Za-z]{3,9})[\s-,]*(\d{4})$/)) && MONTHS[m[2].slice(0, 3).toLowerCase()] != null) {
    [d, mo, y] = [+m[1], MONTHS[m[2].slice(0, 3).toLowerCase()], +m[3]];
  } else if ((m = t.match(/^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$/)) && MONTHS[m[1].slice(0, 3).toLowerCase()] != null) {
    [mo, d, y] = [MONTHS[m[1].slice(0, 3).toLowerCase()], +m[2], +m[3]];
  } else return null;
  const ms = Date.UTC(y, mo, d);
  const back = new Date(ms);
  return back.getUTCMonth() === mo && back.getUTCDate() === d ? ms : null;
}

// ---- Columns ----------------------------------------------------------------------

const NAME_RE = /^(name|id|unit|units|unit id|serial|serial no|serial number|s n|sn|asset|asset id|asset tag|item|item id|tag|tag no|equipment|equipment id|pump|truck|machine|position|system|description|fleet no)\b/;
const AGE_RE = /\b(age|current|use|used|hours?|hrs?|running|run|operating|km|kms|miles?|cycles?|starts?|life|time|odometer|meter|reading)\b/;
const RATE_RE = /\b(rate|per (day|week|month|quarter|year)|a (day|week|month|quarter|year)|usage|utili[sz]ation|duty)\b/;
const DATE_RE = /\b(date|replaced|installed|fitted|changed|in service|commissioned|since)\b/;
const NEXT_SERVICE_RE = /\b(next service|service due|due at|next overhaul|next pm)\b/;
const IN_SERVICE_RE = /\b(in service|time in service|service (months?|periods?))\b/;

// A converted figure without floating-point noise (2.24 years is 26.88 months, not 26.880000000000003).
const clean = (v) => Number(Number(v).toPrecision(12));

const words = (s) => String(s || "").toLowerCase().replace(/[_/\-()[\].,:#]+/g, " ").replace(/\s+/g, " ").trim();

// What each column can map to, for the forecast's kind: the item's name, its
// current use (age), the date it was last replaced (an age from the date), its
// own usage rate, and per kind its covariates, its time in service or its next
// service. ``fields``: the model's covariate (or stress) fields.
export function targets({ fields = [], repairable = false, warranty = false } = {}) {
  return [
    { key: "name", label: "Name" },
    { key: "current_use", label: "Current use (age)" },
    { key: "last_replaced", label: "Last replaced (date)" },
    { key: "rate", label: "Own usage rate" },
    ...(warranty ? [{ key: "service_periods", label: "Time in service" }] : []),
    ...(repairable ? [{ key: "next_service_at", label: "Next service at" }] : []),
    ...fields.map((f) => ({ key: `cov:${f.name}`, label: f.label || f.name, field: f })),
  ];
}

const share = (values, test) => {
  const filled = values.filter((v) => String(v ?? "").trim() !== "");
  return filled.length ? filled.filter(test).length / filled.length : 0;
};

// Does the first row name the columns? Yes when none of its cells is a number
// or a date and some later row has one.
export function hasHeader(rows) {
  if (!rows.length) return false;
  const first = rows[0];
  const dataLike = (c) => readNumber(c) !== null || readDate(c) !== null;
  if (first.some(dataLike)) return false;
  return rows.length === 1 || rows.slice(1, 6).some((r) => r.some(dataLike));
}

// A first guess of each column's target (or "" to leave it out), by header
// and by what the column holds. Without a header: the first text column is
// the name, the first number column the age.
export function guessMapping(headers, rows, opts = {}) {
  const avail = targets(opts);
  const taken = new Set();
  const columns = headers.map((_, j) => rows.map((r) => r[j]));
  const numeric = columns.map((vals) => share(vals, (v) => readNumber(v) !== null) >= 0.8);
  const datey = columns.map((vals) => share(vals, (v) => readDate(v) !== null) >= 0.8);
  const out = headers.map(() => "");
  const claim = (j, key) => { if (!out[j] && !taken.has(key)) { out[j] = key; taken.add(key); } };
  const named = headers.map((h) => words(h));
  // Covariates by their own name or label first: "Load" is a covariate, not an age.
  for (const t of avail.filter((x) => x.field)) {
    const j = named.findIndex((h, k) => !out[k] && (h === words(t.field.name) || h === words(t.label)));
    if (j >= 0) claim(j, t.key);
  }
  named.forEach((h, j) => { if (datey[j] && (DATE_RE.test(h) || !h)) claim(j, "last_replaced"); });
  named.forEach((h, j) => { if (opts.repairable && NEXT_SERVICE_RE.test(h) && numeric[j]) claim(j, "next_service_at"); });
  named.forEach((h, j) => { if (opts.warranty && IN_SERVICE_RE.test(h) && numeric[j]) claim(j, "service_periods"); });
  named.forEach((h, j) => { if (RATE_RE.test(h) && numeric[j]) claim(j, "rate"); });
  named.forEach((h, j) => { if (NAME_RE.test(h) && !datey[j]) claim(j, "name"); });
  named.forEach((h, j) => { if (AGE_RE.test(h) && numeric[j] && !DATE_RE.test(h)) claim(j, "current_use"); });
  // Still unclaimed: the first text column is the name, the first number column the age.
  if (!taken.has("name")) {
    const j = columns.findIndex((_, k) => !out[k] && !numeric[k] && !datey[k]);
    if (j >= 0) claim(j, "name");
  }
  if (!taken.has("current_use") && !taken.has("last_replaced")) {
    const j = columns.findIndex((_, k) => !out[k] && numeric[k]);
    if (j >= 0) claim(j, "current_use");
  }
  return out;
}

// The unit the age column is in, from its header ("Age (days)") or the units
// written in its cells ("1200 h"); "" when neither says.
export function guessAgeUnit(header, values = []) {
  const fromHeader = guessUnit(header);
  if (fromHeader) return fromHeader;
  for (const v of values) {
    const n = readNumber(v);
    if (n?.unit) return n.unit;
  }
  return "";
}

// The model's unit in the converter's spelling ("hours" → "Hours"), or "".
export const calendarUnit = (unit) => {
  const u = timeUnitOf(unit) || guessUnit(unit);
  return CONVERTIBLE_UNITS.includes(u) ? u : "";
};

// Factor from ``from`` to ``to`` (both calendar units), or null.
export function unitFactor(from, to) {
  if (!from || !to || from === to) return 1;
  if (!(from in HOURS) || !(to in HOURS)) return null;
  return HOURS[from] / HOURS[to];
}

// ---- Rows into items --------------------------------------------------------------

// ``rows`` (after the header) into items, ``mapping`` the target of each
// column. ``modelUnit`` the forecast's time unit; ``ageUnit`` the unit the
// ages were typed in (converted when both are calendar units). A date of last
// replacement becomes an age: the time since, at the item's usage rate (own,
// else ``defaultRate``) per ``periodLabel`` when there is one, else in the
// model's unit when that is a calendar unit. ``today`` (UTC ms) for tests.
// Returns { items, skipped: [{ row, why }], notes }. ``firstRow`` is the
// spreadsheet row number of rows[0], for the reasons.
export function readItems(rows, mapping, {
  modelUnit = "", ageUnit = "", defaultRate = 0, periodLabel = "months", fields = [], today = Date.now(),
  firstRow = 2,
} = {}) {
  const col = (key) => mapping.indexOf(key);
  const at = (r, key) => (col(key) >= 0 ? String(r[col(key)] ?? "").trim() : "");
  const target = calendarUnit(modelUnit);
  const notes = new Set();
  const items = [];
  const skipped = [];
  const day = 86400000;
  const todayUtc = Math.floor(today / day) * day;
  const perDays = periodDays(periodLabel);
  rows.forEach((r, k) => {
    const row = firstRow + k;
    const skip = (why) => skipped.push({ row, why });
    const name = at(r, "name") || (col("name") < 0 ? `Item ${k + 1}` : "");
    if (!name) return skip("no name");
    const item = { name: name.slice(0, 200), current_use: null, rate: null };
    const rate = at(r, "rate");
    if (rate) {
      const n = readNumber(rate);
      if (!n || n.value < 0) return skip(`the usage rate “${rate.slice(0, 20)}” isn't a number of at least 0`);
      item.rate = n.value;
    }
    const age = at(r, "current_use");
    if (age) {
      const n = readNumber(age);
      if (!n || n.value < 0) return skip(`the current use “${age.slice(0, 20)}” isn't a number of at least 0`);
      const from = n.unit && CONVERTIBLE_UNITS.includes(n.unit) ? n.unit : ageUnit;
      const f = target && from ? unitFactor(from, target) : 1;
      if (f === null) return skip(`can't convert ${from.toLowerCase()} to ${modelUnit}`);
      if (f !== 1) notes.add(`Ages in ${from.toLowerCase()} converted to ${target.toLowerCase()}.`);
      item.current_use = clean(n.value * f);
    }
    const replaced = at(r, "last_replaced");
    if (item.current_use === null && replaced) {
      const when = readDate(replaced);
      if (when === null) return skip(`“${replaced.slice(0, 20)}” isn't a date`);
      const days = (todayUtc - when) / day;
      if (days < 0) return skip("the replacement date is in the future");
      const use = item.rate ?? (Number(defaultRate) > 0 ? Number(defaultRate) : null);
      if (use !== null && perDays) {
        item.current_use = clean((days / perDays) * use);
        notes.add(`Ages from the replacement dates: the time since, at each item's usage per ${String(periodLabel).replace(/s$/i, "")}.`);
      } else if (target) {
        item.current_use = clean(days * (HOURS.Days / HOURS[target]));
        notes.add(`Ages from the replacement dates: the ${target.toLowerCase()} since.`);
      } else {
        return skip("an age from a date needs the usage per period set first");
      }
      if (perDays) item.service_periods = clean(days / perDays);
    }
    if (item.current_use === null) return skip("no current use or replacement date");
    const inService = at(r, "service_periods");
    if (inService) {
      const n = readNumber(inService);
      if (!n || n.value < 0) return skip(`the time in service “${inService.slice(0, 20)}” isn't a number`);
      item.service_periods = n.value;
    }
    const next = at(r, "next_service_at");
    if (next) {
      const n = readNumber(next);
      if (!n || n.value < 0) return skip(`the next service “${next.slice(0, 20)}” isn't a number`);
      item.next_service_at = n.value;
    }
    const covariates = {};
    for (const f of fields) {
      const v = at(r, `cov:${f.name}`);
      if (!v) continue;
      if (f.type === "number") {
        const n = readNumber(v);
        if (!n) return skip(`${f.label || f.name} “${v.slice(0, 20)}” isn't a number`);
        covariates[f.name] = n.value;
      } else {
        const level = (f.options || []).find((o) => String(o).toLowerCase() === v.toLowerCase());
        if ((f.options || []).length && level === undefined) {
          return skip(`${f.label || f.name} “${v.slice(0, 20)}” isn't one of ${f.options.join(", ")}`);
        }
        covariates[f.name] = level ?? v;
      }
    }
    if (Object.keys(covariates).length) item.covariates = covariates;
    items.push(item);
  });
  return { items, skipped, notes: [...notes] };
}

// Everything from a pasted block or a file's text: { headers, rows, header,
// mapping, firstRow }. ``mapping`` is the first guess; the panel lets the user
// change it.
export function readBlock(text, opts = {}) {
  const all = splitRows(text);
  if (!all.length) return { headers: [], rows: [], header: false, mapping: [], firstRow: 1 };
  const width = Math.max(...all.map((r) => r.length));
  const header = hasHeader(all);
  const headers = header
    ? Array.from({ length: width }, (_, j) => all[0][j] || `Column ${j + 1}`)
    : Array.from({ length: width }, (_, j) => `Column ${j + 1}`);
  const rows = (header ? all.slice(1) : all).map((r) => Array.from({ length: width }, (_, j) => r[j] ?? ""));
  return { headers, rows, header, mapping: guessMapping(header ? headers : headers.map(() => ""), rows, opts),
           firstRow: header ? 2 : 1 };
}

// The preview's sentence: "30 items read; 2 rows skipped".
export function summary({ items = [], skipped = [] }, existing = 0) {
  const n = items.length;
  const parts = [`${n} item${n === 1 ? "" : "s"} read`];
  if (skipped.length) parts.push(`${skipped.length} row${skipped.length === 1 ? "" : "s"} skipped`);
  let text = parts.join("; ");
  const room = MAX_ITEMS - existing;
  if (n > room) text += ` (a forecast holds ${MAX_ITEMS} items: only the first ${Math.max(room, 0)} fit)`;
  return text;
}

// Items added to ``current`` (or replacing them); new items get no id, so the
// server gives each one. Capped at the fleet's limit.
export function mergeItems(current, incoming, replace = false) {
  const base = replace ? [] : current;
  return [...base, ...incoming].slice(0, MAX_ITEMS);
}

// ---- Many items at once -----------------------------------------------------------

// ``items`` with ``patch`` applied to the rows whose index is in ``selected``.
export function patchSelected(items, selected, patch) {
  return items.map((it, i) => (selected.has(i) ? { ...it, ...patch } : it));
}

export function removeSelected(items, selected) {
  return items.filter((_, i) => !selected.has(i));
}
