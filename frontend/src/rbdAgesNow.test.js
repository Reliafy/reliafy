import test from "node:test";
import assert from "node:assert/strict";
import { prefillAges, takenAsNew } from "./rbdAgesNow.js";

const blocks = [{ id: "a" }, { id: "b" }, { id: "c" }, { id: "d" }];
const ages = {
  blocks: {
    a: { age: 14000.4, basis: "counter", item: "Pump 41", note: "from its Run hours (read 2026-11-16)" },
    b: { age: 240, basis: "continuous", item: "Pump 42" },
    c: { reason: "nothing is fitted at Controller" },
  },
  unlinked: ["d"],
};

test("prefillAges fills each block's age from the tree and says where it came from", () => {
  const { states, sources } = prefillAges(ages, blocks, {});
  assert.deepEqual(states.a, { mode: "age", value: "14000", fromTree: true });
  assert.match(sources.a.text, /^14,000 from Pump 41: its counter \(from its Run hours/);
  assert.equal(sources.b.guessed, true);
  assert.equal(states.c, undefined);
  assert.equal(sources.c.text, "No age: nothing is fitted at Controller.");
  assert.match(sources.d.text, /stands for no position/);
});

test("prefillAges never overwrites what the user set", () => {
  const { states } = prefillAges(ages, blocks, { a: { mode: "failed", value: "" } });
  assert.deepEqual(states.a, { mode: "failed", value: "" });
});

test("takenAsNew names the blocks run as new under As of now", () => {
  const result = { current_state: { a: { age: 1 } }, nodes: [
    { id: "a", type: "component", label: "Pump A" }, { id: "c", type: "component", label: "Controller" },
    { id: "in", type: "input" }] };
  assert.deepEqual(takenAsNew(result), ["Controller"]);
  assert.deepEqual(takenAsNew({ nodes: [] }), []);
});
