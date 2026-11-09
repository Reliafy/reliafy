import { test } from "node:test";
import assert from "node:assert/strict";
import { closeBlocker, closePayload, groupLines, lineChoice, lineText, markBody, unanswered } from "./packageLines.js";

const P1 = { kind: "position", id: "p1", name: "Pump 1" };
const P2 = { kind: "position", id: "p2", name: "Pump 2" };
const LINES = [
  { task_id: "t1", name: "Clean basket", subject: P1, state: "done" },
  { task_id: "t2", name: "Check seal", subject: P2, state: "not_done", reason: "no access" },
  { task_id: "t3", name: "Grease bearing", subject: P1, state: "todo" },
  { task_id: "t4", name: "Check gauge", subject: P2, state: "problem", finding: { kind: "other", notes: "cracked glass" } },
];

test("lines group by where they are, in order", () => {
  const g = groupLines(LINES);
  assert.deepEqual(g.map((x) => x.subject.name), ["Pump 1", "Pump 2"]);
  assert.deepEqual(g[0].lines.map((l) => l.task_id), ["t1", "t3"]);
  assert.deepEqual(groupLines([{ task_id: "x", name: "x" }])[0].subject, null);
});

test("a line's choice and its words", () => {
  assert.deepEqual(LINES.map(lineChoice), ["done", "not_done", "", "problem"]);
  assert.deepEqual(LINES.map(lineText), ["", "no access", "", "cracked glass"]);
});

test("marking bodies match the backend's states", () => {
  assert.deepEqual(markBody("done"), { state: "done" });
  assert.deepEqual(markBody("not_done", " no key "), { state: "not_done", reason: "no key" });
  assert.deepEqual(markBody("problem", "leaking"), { state: "problem", finding: { kind: "other", notes: "leaking" } });
  assert.deepEqual(markBody(""), { state: "todo" });
});

test("what's unanswered, and what the Close button says", () => {
  assert.deepEqual(unanswered(LINES), ["Grease bearing"]);
  assert.equal(closeBlocker(LINES), "Answer 1 more line to close");
  assert.equal(closeBlocker([...LINES, { task_id: "t5", name: "x", state: "todo" }]), "Answer 2 more lines to close");
  assert.equal(closeBlocker(LINES.filter((l) => l.state !== "todo")), null);
  assert.equal(closeBlocker([]), null);
});

test("the close payload lists each line not done with its reason", () => {
  const body = closePayload({ actions: [], on: "2026-11-10", notes: "n", readings: [], lines: LINES });
  assert.deepEqual(body, {
    actions: [], on: "2026-11-10", notes: "n", readings: [],
    not_done: [{ task_id: "t2", reason: "no access" }],
  });
  // Not a package's work order: no not_done.
  assert.equal("not_done" in closePayload({ actions: [{ kind: "repair" }], on: "2026-11-10" }), false);
});
