import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { clockText, dayText, outOfRange, parseClockText, parseDayText } from "./dateFields.js";

test("a day reads day first, whatever the browser's language", () => {
  assert.equal(dayText("2026-11-22"), "22 Nov 2026");
  assert.equal(dayText(""), "");
  for (const t of ["22/11/2026", "22-11-2026", "22.11.2026", "22 11 2026", "22 Nov 2026", "22 November 2026", "2026-11-22"]) {
    assert.equal(parseDayText(t), "2026-11-22", t);
  }
  assert.equal(parseDayText("1/2/2026"), "2026-02-01"); // 1 February, never 2 January
  assert.equal(parseDayText("31/02/2026"), null);
  assert.equal(parseDayText("11/22/2026"), null); // month first isn't taken
  assert.equal(parseDayText("22/11"), null);
  assert.equal(parseDayText("22/11/26"), null); // half-typed: not yet
  assert.equal(parseDayText("22/11/26", { loose: true }), "2026-11-22");
  assert.equal(parseDayText("22 Nov", { loose: true, year: "2027" }), "2027-11-22");
  assert.equal(parseDayText("22 No 2026"), null);
});

test("a time reads on a 24-hour clock", () => {
  const cases = { 8: "08:00", "08": "08:00", 830: "08:30", "0830": "08:30", "8:30": "08:30", "8.30": "08:30", "20:00": "20:00",
    "8pm": "20:00", "8:30 PM": "20:30", "12am": "00:00", "12pm": "12:00", "23:59": "23:59" };
  for (const [t, v] of Object.entries(cases)) assert.equal(parseClockText(t), v, t);
  for (const t of ["24:00", "8:60", "13pm", "", "abc"]) assert.equal(parseClockText(t), null, t);
  assert.equal(clockText("16:00:00"), "16:00");
  assert.equal(outOfRange("2026-11-23", null, "2026-11-22"), true);
  assert.equal(outOfRange("2026-11-22", "2026-11-01", "2026-11-22"), false);
});

// The browser's own date and time fields follow its language ("11/22/2026", "04:00 PM"): every
// date or time a person types goes through the shared fields (components/ui/DateTimeInput.jsx).
test("no page uses the browser's own date or time field", () => {
  const found = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const p = join(dir, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.jsx$/.test(name) && !p.endsWith(join("ui", "DateTimeInput.jsx"))) {
        const text = readFileSync(p, "utf8");
        if (/<input\b[^>]*\btype=(["'{])(date|time|datetime-local)\b/.test(text) || /type="datetime-local"/.test(text)) found.push(p);
      }
    }
  };
  walk(new URL(".", import.meta.url).pathname);
  assert.deepEqual(found, []);
});
