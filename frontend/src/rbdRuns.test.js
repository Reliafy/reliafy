// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  availabilityText, byText, compareSummary, jobStatusLine, runsPath, runtimeText, runtimeVsQuote, statusChip, viaText,
} from "./rbdRuns.js";

test("runtimes read in seconds, then minutes", () => {
  assert.equal(runtimeText(0.42), "0.4 s");
  assert.equal(runtimeText(12.3), "12 s");
  assert.equal(runtimeText(200), "3 min 20 s");
  assert.equal(runtimeText(180), "3 min");
  assert.equal(runtimeText(3725), "1 h 2 min");
  assert.equal(runtimeText(null), "—");
});

test("who and from where, with old runs that didn't record it", () => {
  assert.equal(byText({ by: { you: true } }), "You");
  assert.equal(byText({ by: { you: false, name: "Sam" } }), "Sam");
  assert.equal(byText({ by: { you: false, name: null } }), "A teammate");
  assert.equal(viaText({ via: { label: "Claude (MCP)" } }), "Claude (MCP)");
  assert.equal(viaText({ via: { label: null } }), "—");
});

test("status colour carries meaning only", () => {
  assert.deepEqual(statusChip("done"), { tone: "neutral", label: "Done" });
  assert.deepEqual(statusChip("failed"), { tone: "danger", label: "Failed" });
  assert.equal(statusChip("queued").tone, "accent");
});

test("a window availability with its interval, to its precision", () => {
  const a = { value: 0.99968, lower: 0.99951, upper: 0.99982 };
  assert.deepEqual(availabilityText(a), { value: "99.968%", interval: "99.951–99.982%" });
  assert.deepEqual(availabilityText(null), { value: "—", interval: null });
  assert.deepEqual(availabilityText({ value: 0.95 }), { value: "95.000%", interval: null });
});

test("runtime beside its quote", () => {
  assert.equal(runtimeVsQuote({ runtime_s: 12.3, quote: { text: "about 15 s, up to 40 s" } }),
    "12 s · quoted about 15 s, up to 40 s");
  assert.equal(runtimeVsQuote({ runtime_s: 1.5 }), "1.5 s");
  assert.equal(runtimeVsQuote({ runtime_s: null, quote: { text: "about 15 s" } }), "Quoted about 15 s");
});

test("compare: the spread, and whether the intervals overlap", () => {
  const run = (value, lower, upper) => ({ availability: { value, lower, upper } });
  const overlapping = compareSummary([run(0.9990, 0.9985, 0.9995), run(0.9992, 0.9988, 0.9996)]);
  assert.equal(overlapping.count, 2);
  assert.equal(overlapping.overlap, true);
  assert.equal(overlapping.low, "99.900%");
  assert.equal(overlapping.high, "99.920%");
  assert.equal(compareSummary([run(0.99, 0.989, 0.991), run(0.995, 0.994, 0.996)]).overlap, false);
  assert.equal(compareSummary([run(0.99, null, null), run(0.995, 0.994, 0.996)]).overlap, null);
  assert.equal(compareSummary([run(0.99, 0.98, 1)]), null);
});

test("queue status with the quote and the wait", () => {
  assert.equal(jobStatusLine({ status: "queued", queue_position: 0 }), "Queued — you're next…");
  assert.equal(jobStatusLine({ status: "queued", queue_position: 2 }), "Queued — 2 ahead of you…");
  assert.equal(
    jobStatusLine({ status: "queued", queue_position: 2, wait_text: "about 40 s", quote: { text: "about 15 s, up to 40 s" } }),
    "Queued — 2 ahead of you, starts in about 40 s. Then about 15 s, up to 40 s.");
  assert.equal(jobStatusLine({ status: "queued", queue_position: 0, quote: { text: "about 15 s" } }),
    "Queued — you're next. Then about 15 s.");
  assert.equal(jobStatusLine({ status: "running", quote: { text: "about 15 s" } }), "Running the simulation — about 15 s…");
  assert.equal(jobStatusLine({ status: "running" }), "Running the simulation…");
  assert.equal(jobStatusLine(null), "");
});

test("runs paths", () => {
  assert.equal(runsPath(), "/rbds/runs");
  assert.equal(runsPath("a b"), "/rbds/runs?rbd=a%20b");
});
