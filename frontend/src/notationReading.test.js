import { test } from "node:test";
import assert from "node:assert/strict";
import { createNotationReader, readingView } from "./notationReading.js";

// A fake clock: timers run when flush() says.
function clock() {
  let next = 1;
  const timers = new Map();
  return {
    setTimer: (fn) => { const id = next++; timers.set(id, fn); return id; },
    clearTimer: (id) => timers.delete(id),
    flush: () => { const fns = [...timers.values()]; timers.clear(); fns.forEach((f) => f()); },
    pending: () => timers.size,
  };
}
const tick = () => new Promise((r) => setTimeout(r, 0));

test("the live reading says what the text was read as", async () => {
  const c = clock();
  const answers = [];
  const reader = createNotationReader(async (text) => ({
    summary: `read ${text}`, columns: ["x", "c"], rows: [["120", "0"]], n_rows: 1, kind: "lives",
  }), (a) => answers.push(a), c);
  reader.read("120");
  reader.read("120, 1000+");
  assert.equal(c.pending(), 1); // one read, after the pause
  c.flush();
  await tick();
  assert.equal(answers.length, 1);
  const view = readingView("120, 1000+", answers[0]);
  assert.equal(view.state, "ok");
  assert.equal(view.summary, "read 120, 1000+");
  assert.deepEqual(view.columns, ["x", "c"]);
  // Text changed since: "reading" until its own answer comes.
  assert.equal(readingView("120, 1000+, 5", answers[0]).state, "reading");
  assert.equal(readingView("  ", answers[0]).state, "empty");
});

test("an error says where, in SurPyval's words", async () => {
  const c = clock();
  const answers = [];
  const reader = createNotationReader(async () => ({
    error: "Entry 2 (line 1, “abc”): Can't read 'abc'.", where: { entry: "abc", line: 1, column: 6 },
  }), (a) => answers.push(a), c);
  reader.read("120, abc");
  c.flush();
  await tick();
  const view = readingView("120, abc", answers[0]);
  assert.equal(view.state, "error");
  assert.match(view.error, /Entry 2.*abc/);
  assert.deepEqual(view.where, { entry: "abc", line: 1, column: 6 });
});

test("a request that fails says so", async () => {
  const c = clock();
  const answers = [];
  const reader = createNotationReader(async () => { throw new Error("Network down"); }, (a) => answers.push(a), c);
  reader.read("10");
  c.flush();
  await tick();
  assert.equal(readingView("10", answers[0]).error, "Network down");
});

test("a slow answer to old text never replaces the newest", async () => {
  const c = clock();
  const answers = [];
  const waits = {};
  const reader = createNotationReader((text) => new Promise((resolve) => { waits[text] = resolve; }),
    (a) => answers.push(a), c);
  reader.read("10");
  c.flush();
  reader.read("10, 20");
  c.flush();
  waits["10, 20"]({ summary: "new" });
  waits["10"]({ summary: "old" });
  await tick();
  assert.deepEqual(answers.map((a) => a.result.summary), ["new"]);
  reader.read("");
  assert.equal(c.pending(), 0); // nothing to read in blank text
});
