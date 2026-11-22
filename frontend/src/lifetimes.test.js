// Run with: node --test src/
// The Lifetimes view's logic (lifetimes.js): the count summary, the hint when
// every unit (or none) is read as failed, sorting, the even sample, and the
// chart's traces.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  lifetimesTraces, readingHint, sampleLines, sortOptions, sortedLines, summaryText, timeRange,
} from "./lifetimes.js";

const payload = {
  mode: "rows",
  unit: "Hours",
  summary: { units: 150, failed: 98, running: 49, window: 3, before: 0, late: 0, events: 0 },
  groups: { site: ["B", "A", "A"] },
  lines: [
    { id: null, rows: [1], start: 0, end: 30, entered: null, n: 1, marks: [{ kind: "failed", at: 30 }] },
    { id: null, rows: [2], start: 5, end: 10, entered: 5, n: 1, marks: [{ kind: "running", at: 10 }] },
    { id: null, rows: [3], start: 0, end: 20, entered: null, n: 3, marks: [{ kind: "window", from: 12, at: 20, n: 3 }] },
  ],
};

test("the count summary says how each unit ended", () => {
  assert.equal(summaryText(payload), "150 units: 98 failed, 49 still running, 3 in a window");
  assert.equal(summaryText({ ...payload, summary: { ...payload.summary, late: 20 } }),
    "150 units: 98 failed, 49 still running, 3 in a window · 20 entered late");
  assert.equal(summaryText({ mode: "repairable", lines: [{ id: "A" }, { id: "B" }], summary: { units: 2, events: 5 } }),
    "2 systems · 5 failures");
  assert.equal(summaryText({ mode: "repairable", lines: [{ id: "All rows" }], summary: { units: 1, events: 30 } }),
    "1 stream · 30 failures");
});

test("a reading with every unit failed, or none, says what to check", () => {
  assert.equal(readingHint(payload), null);
  assert.match(readingHint({ ...payload, summary: { units: 4, failed: 4, running: 0, window: 0, before: 0 } }), /Every unit is read as failed/);
  assert.match(readingHint({ ...payload, summary: { units: 4, failed: 0, running: 4, window: 0, before: 0 } }), /No unit is read as failed/);
});

test("lines sort by time, by row order and by a group", () => {
  assert.deepEqual(sortedLines(payload, "time").map((l) => l.rows[0]), [2, 3, 1]);
  assert.deepEqual(sortedLines(payload, "unit").map((l) => l.rows[0]), [1, 2, 3]);
  const byGroup = sortedLines(payload, "group:site");
  assert.deepEqual(byGroup.map((l) => [l.group, l.rows[0]]), [["A", 2], ["A", 3], ["B", 1]]);
  assert.deepEqual(sortOptions(payload).map((o) => o.value), ["time", "unit", "group:site"]);
});

test("many lines show an even sample, first and last kept", () => {
  const lines = Array.from({ length: 1000 }, (_, k) => ({ end: k }));
  const s = sampleLines(lines, 200);
  assert.equal(s.length, 200);
  assert.equal(s[0].end, 0);
  assert.equal(s[199].end, 999);
  assert.equal(sampleLines(lines.slice(0, 50), 200).length, 50);
});

test("the traces mark each ending in its own shape, with counts and late entry", () => {
  const traces = lifetimesTraces(sortedLines(payload, "time"), { mode: "rows", unit: "Hours" });
  const names = traces.map((t) => t.name).filter(Boolean);
  assert.ok(names.includes("Failed") && names.includes("Still running (last seen working)"));
  assert.ok(names.includes("Failed in this window (between inspections)") && names.includes("Entered late (observed from here)"));
  const failed = traces.find((t) => t.name === "Failed");
  assert.equal(failed.marker.symbol, "circle");
  assert.equal(failed.y[0], 2); // the longest line last, at the bottom
  assert.match(failed.text[0], /Row 1: failed at 30 hours/);
  const counts = traces.find((t) => t.mode === "text");
  assert.deepEqual(counts.text, [" 3×"]);
  assert.deepEqual(timeRange(payload.lines), [0, 31.2]);
});

test("repairable failures are ticks on the system's line", () => {
  const lines = [{ id: "A", start: 0, end: 50, entered: null, n: 1,
    marks: [{ kind: "failed", at: 10 }, { kind: "failed", at: 25 }, { kind: "bound", at: 50 }] }];
  const traces = lifetimesTraces(lines, { mode: "repairable" });
  const events = traces.find((t) => t.name === "Failure");
  assert.equal(events.marker.symbol, "line-ns");
  assert.deepEqual(events.x, [10, 25]);
  assert.ok(traces.find((t) => t.name === "Record ends"));
});
