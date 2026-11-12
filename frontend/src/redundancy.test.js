import test from "node:test";
import assert from "node:assert/strict";
import { badge, blankDraft, draftBody, draftFrom, draftProblems, parsePercent, setWords } from "./redundancy.js";

const SET = { id: "g1", name: "Pumps", k: 1, n: 2, mode: "standby", standby: "cold", start_probability: 0.98,
  dormancy: null, members: [{ id: "a", name: "Pump A" }, { id: "b", name: "Pump B" }] };

test("a set reads in a line, and its members carry a short badge", () => {
  assert.equal(setWords(SET), "1 running, 1 on cold standby · starts 98% of the time");
  assert.equal(setWords({ ...SET, mode: "active", n: 3, k: 2 }), "Any 2 of 3 needed, all running");
  assert.equal(setWords({ ...SET, standby: "warm", dormancy: 0.2 }), "1 running, 1 on warm standby · ages at 20% while waiting");
  assert.deepEqual(badge({ ...SET, mode: "active" }), { text: "1 of 2", title: "In the redundancy set Pumps: Any 1 of 2 needed, all running" });
  assert.equal(badge(SET).text, "Standby set");
  assert.equal(badge(null), null);
});

test("a draft needs two members and a k below their count; percentages are checked", () => {
  const d = { ...blankDraft(), members: ["a"] };
  assert.match(draftProblems(d)[0], /at least two/);
  assert.match(draftProblems({ ...d, members: ["a", "b"], k: 2 })[0], /from 1 to 1/);
  assert.deepEqual(draftProblems({ ...d, members: ["a", "b"] }), []);
  const sb = { ...d, members: ["a", "b"], mode: "standby", start: "120" };
  assert.match(draftProblems(sb)[0], /starts/);
  assert.deepEqual(draftProblems({ ...sb, start: "98%" }), []);
  assert.equal(parsePercent(""), null);
  assert.ok(Number.isNaN(parsePercent("x")));
});

test("a new set's body, and an edit's changes only", () => {
  const d = { ...blankDraft(), name: " Pumps ", members: ["a", "b"], mode: "standby", start: "98", ages: "40" };
  assert.deepEqual(draftBody(d), { name: "Pumps", k: 1, mode: "standby", standby: "cold", member_ids: ["a", "b"],
    start_probability: 0.98 });  // a cold set has no ageing while waiting
  const edit = { ...draftFrom(SET), members: ["a", "b", "c"], standby: "warm", ages: "25" };
  assert.deepEqual(draftBody(edit, SET), { name: "Pumps", k: 1, mode: "standby", standby: "warm", add: ["c"], remove: [],
    start_probability: "", dormancy: 0.25 });
  assert.deepEqual(draftBody(draftFrom(SET), SET).add, []);
  assert.equal("start_probability" in draftBody(draftFrom(SET), SET), false);
});
