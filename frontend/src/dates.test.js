// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { MONTHS, formatDate, formatDateTime, formatMonth } from "./dates.js";

test("a day reads day first, with a short month and no leading zero", () => {
  assert.equal(formatDate("2026-11-01"), "1 Nov 2026");
  assert.equal(formatDate("2026-09-30"), "30 Sep 2026");
  assert.equal(formatDate("2026-11-01", { weekday: true }), "Sun 1 Nov 2026");
  assert.equal(formatDate("2026-11-01", { year: false }), "1 Nov");
  assert.equal(formatDate("2026-11-01", { long: true }), "1 November 2026");
  assert.equal(formatMonth("2026-11-01"), "Nov 2026");
  assert.equal(MONTHS.length, 12);
});

test("a timestamp reads with a 24-hour clock", () => {
  assert.equal(formatDateTime("2026-11-01T14:05:09Z", { utc: true }), "1 Nov 2026, 14:05");
  assert.equal(formatDateTime("2026-11-01T08:04:00Z", { utc: true }), "1 Nov 2026, 08:04");
  assert.equal(formatDateTime("2026-11-01T00:00:00Z", { utc: true }), "1 Nov 2026, 00:00");
  assert.equal(formatDateTime("2026-11-01T14:05:09Z", { utc: true, year: false }), "1 Nov, 14:05");
  assert.equal(formatDate("2026-11-01T23:30:00Z", { utc: true }), "1 Nov 2026");
  assert.equal(formatDate("2026-10-31T23:30:00-05:00", { utc: true, weekday: true }), "Sun 1 Nov 2026");
  assert.equal(formatMonth("2026-12-31T23:59:00Z", { utc: true }), "Dec 2026");
  assert.equal(formatDate(Date.UTC(2026, 10, 1), { utc: true }), "1 Nov 2026");
});

test("an instant shows in the viewer's time zone unless UTC is asked for", () => {
  const local = new Date(2026, 10, 1, 14, 5);
  assert.equal(formatDate(local), "1 Nov 2026");
  assert.equal(formatDateTime(local), "1 Nov 2026, 14:05");
  assert.equal(formatDateTime(new Date(2026, 0, 9, 7, 3)), "9 Jan 2026, 07:03");
});

test("a day on its own is shown as written, whatever the time zone", () => {
  const before = process.env.TZ;
  try {
    for (const zone of ["America/Los_Angeles", "Australia/Brisbane", "Pacific/Kiritimati"]) {
      process.env.TZ = zone;
      assert.equal(formatDate("2026-11-01"), "1 Nov 2026", zone);
      assert.equal(formatDateTime("2026-11-01"), "1 Nov 2026, 00:00", zone);
    }
  } finally {
    if (before === undefined) delete process.env.TZ; else process.env.TZ = before;
  }
});

test("what isn't a date gives an empty string, never 'Invalid Date'", () => {
  for (const bad of [null, undefined, "", "not a date", "2026-13-01", "2026-02-31", NaN, new Date(NaN), {}]) {
    assert.equal(formatDate(bad), "");
    assert.equal(formatDateTime(bad), "");
    assert.equal(formatMonth(bad), "");
  }
});

// ---- The guard ---------------------------------------------------------------
// A date formatted with the browser's locale reads month first for a browser
// set to US English ("Nov 1, 2026", "2:05 PM"), so every date a person reads
// goes through dates.js. This fails, naming the file and line, on:
//   - toLocaleDateString( and toLocaleTimeString(, anywhere;
//   - Intl.DateTimeFormat(, anywhere but ALLOWED;
//   - toLocaleString( with date options (day, month, hour, timeZone, …), or
//     called on `new Date(…)` / `parseTimestamp(…)`, or on a name the same file
//     sets to one of those.
// Numbers are left alone: `n.toLocaleString("en-AU")` and number options pass.

const SRC = fileURLToPath(new URL(".", import.meta.url));

// file → why it may call Intl.DateTimeFormat.
const ALLOWED = {
  // Reads the browser's time zone, checks a zone's name, and reads today's
  // numeric year, month and day in a zone: nothing it formats is shown.
  "workspaceDate.js": "reads date parts and the time zone",
};

const DATE_OPTION = /\b(weekday|era|year|month|day|hour|minute|second|fractionalSecondDigits|dayPeriod|hour12|hourCycle|timeZone|timeZoneName|dateStyle|timeStyle)\s*:/;
const MAKES_DATE = /(new Date|parseTimestamp)$/;

// The index of the bracket that closes (forwards) or opens (backwards) the one at `at`.
function match(text, at, step) {
  let depth = 0;
  for (let i = at; i >= 0 && i < text.length; i += step) {
    if ("([{".includes(text[i])) depth += step;
    else if (")]}".includes(text[i])) depth -= step;
    if (depth === 0) return i;
  }
  return -1;
}

function dateFormattingOutsideHelper(text) {
  const found = [];
  const lineOf = (i) => text.slice(0, i).split("\n").length;
  const add = (i, what) => found.push({ line: lineOf(i), what });
  for (const m of text.matchAll(/\.toLocale(Date|Time)String\(/g)) add(m.index, `toLocale${m[1]}String`);
  for (const m of text.matchAll(/\bIntl\s*\.\s*DateTimeFormat\b/g)) add(m.index, "Intl.DateTimeFormat");
  const dates = new Set([...text.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=[^;\n]*\b(?:new Date|parseTimestamp)\(/g)].map((m) => m[1]));
  for (const m of text.matchAll(/\.toLocaleString\(/g)) {
    const open = m.index + m[0].length - 1;
    const close = match(text, open, 1);
    const args = text.slice(open + 1, close < 0 ? open + 400 : close);
    let onDate = false;
    if (text[m.index - 1] === ")") {
      const start = match(text, m.index - 1, -1);
      onDate = start >= 0 && MAKES_DATE.test(text.slice(0, start).trimEnd());
    } else {
      const name = /([A-Za-z_$][\w$]*)$/.exec(text.slice(0, m.index));
      const before = name ? text[m.index - name[0].length - 1] : "";
      onDate = !!name && before !== "." && dates.has(name[1]);
    }
    if (onDate || DATE_OPTION.test(args)) add(m.index, "toLocaleString on a date");
  }
  return found;
}

function sources(dir = SRC, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = `${dir}${entry.name}`;
    if (entry.isDirectory()) sources(`${path}/`, out);
    else if (/\.(js|jsx)$/.test(entry.name) && !/\.test\.js$/.test(entry.name)) out.push(path);
  }
  return out;
}

test("the guard tells a date from a number", () => {
  const hits = (code) => dateFormattingOutsideHelper(code).map((h) => h.what);
  assert.deepEqual(hits("d.toLocaleDateString()"), ["toLocaleDateString"]);
  assert.deepEqual(hits('x\n  .toLocaleTimeString("en-GB")'), ["toLocaleTimeString"]);
  assert.deepEqual(hits('new Intl.DateTimeFormat("en-GB").format(d)'), ["Intl.DateTimeFormat"]);
  assert.deepEqual(hits("new Date(row.created_at).toLocaleString()"), ["toLocaleString on a date"]);
  assert.deepEqual(hits("parseTimestamp(pick(a, b)).toLocaleString()"), ["toLocaleString on a date"]);
  assert.deepEqual(hits('when.toLocaleString(undefined, {\n  day: "numeric",\n  month: "short",\n})'), ["toLocaleString on a date"]);
  assert.deepEqual(hits('x.toLocaleString("en-GB", { timeZone: "UTC" })'), ["toLocaleString on a date"]);
  assert.deepEqual(hits("const d = new Date(iso);\nreturn d.toLocaleString();"), ["toLocaleString on a date"]);
  assert.equal(dateFormattingOutsideHelper("a;\nb;\nd.toLocaleDateString()")[0].line, 3);
  // Numbers.
  assert.deepEqual(hits('n.toLocaleString("en-AU")'), []);
  assert.deepEqual(hits("(r.n_rows ?? 0).toLocaleString()"), []);
  assert.deepEqual(hits("Number(v.toPrecision(4)).toLocaleString(undefined, { maximumFractionDigits: 2 })"), []);
  assert.deepEqual(hits('new Intl.NumberFormat("en-US", { maximumSignificantDigits: 3 }).format(n)'), []);
  assert.deepEqual(hits("const d = new Date(iso);\nreturn d.count.toLocaleString() + row.d.toLocaleString();"), []);
});

test("no date is formatted outside dates.js", () => {
  const problems = [];
  for (const path of sources()) {
    const file = path.slice(SRC.length);
    if (file === "dates.js") continue;
    for (const hit of dateFormattingOutsideHelper(readFileSync(path, "utf8"))) {
      if (hit.what === "Intl.DateTimeFormat" && ALLOWED[file]) continue;
      problems.push(`src/${file}:${hit.line} ${hit.what}`);
    }
  }
  assert.deepEqual(problems, [], "Format dates with src/dates.js (formatDate, formatDateTime, formatMonth), not the browser's locale.");
});
