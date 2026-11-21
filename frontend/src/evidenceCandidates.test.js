import { test } from "node:test";
import assert from "node:assert/strict";
import { evidenceBody, filterCandidates, groupByScope, kindOptions, windowFrom, windowWords } from "./evidenceCandidates.js";

const C = [
  { type: "model", id: "m1", kind: "model", label: "Seal (from maintenance records)", meta: "Weibull", scope: "mode", scope_words: "For this failure mode" },
  { type: "history", id: "p1", kind: "history", label: "Pump: failure history", meta: "12 lives, 4 failed", scope: "position", scope_words: "On this position" },
  { type: "failure_report", id: "r1", kind: "failure_report", label: "FR-3: Seal leaking at the gland", meta: "2026-10-01", scope: "mode", scope_words: "For this failure mode" },
  { type: "strategy_analysis", id: "a9", kind: "analysis", label: "Brake circuit", meta: "", scope: "library", scope_words: "Elsewhere in your library" },
];

test("search needs every word, in any order, and the kind filter keeps one kind", () => {
  assert.deepEqual(filterCandidates(C, "gland seal").map((c) => c.id), ["r1"]);
  assert.deepEqual(filterCandidates(C, "", "history").map((c) => c.id), ["p1"]);
  assert.deepEqual(filterCandidates(C, "seal", "model").map((c) => c.id), ["m1"]);
  assert.equal(filterCandidates(C, "nothing like it").length, 0);
});

test("groups follow the scope order and drop empty ones", () => {
  const g = groupByScope(C);
  assert.deepEqual(g.map((x) => x.scope), ["mode", "position", "library"]);
  assert.deepEqual(g[0].items.map((c) => c.id), ["m1", "r1"]);
  assert.equal(g[0].words, "For this failure mode");
});

test("kind options count each kind", () => {
  assert.deepEqual(kindOptions([{ id: "model", label: "Life models", count: 2 }, { id: "history", label: "Failure history", count: 1 }]),
    [{ value: "", label: "Every kind (3)" }, { value: "model", label: "Life models (2)" }, { value: "history", label: "Failure history (1)" }]);
});

test("a window in words, from fields, and on the saved evidence", () => {
  assert.equal(windowWords({ since: "2022-01-01", lives: 52, failures: 2 }), "52 lives fitted since 1 Jan 2022 (2 failed)");
  assert.equal(windowWords({ since: "2022-01-01", until: "2024-06-30" }), "lives fitted between 1 Jan 2022 and 30 Jun 2024");
  assert.equal(windowWords({ until: "2021-12-31", lives: 1 }), "1 life fitted up to 31 Dec 2021");
  assert.equal(windowWords(null), "");
  assert.equal(windowFrom("", ""), null);
  assert.deepEqual(windowFrom("2022-01-01", ""), { since: "2022-01-01" });
  assert.equal(evidenceBody(null), null);
  assert.deepEqual(evidenceBody({ type: "model", id: "m1", label: "x" }), { type: "model", id: "m1" });
  assert.deepEqual(evidenceBody({ type: "history", id: "p1", window: { since: "2022-01-01" } }),
    { type: "history", id: "p1", window: { since: "2022-01-01" } });
});
