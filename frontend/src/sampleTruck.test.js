import test from "node:test";
import assert from "node:assert/strict";
import { normaliseConfirm } from "./confirm.js";
import { addSampleTruck, anotherCopyConfirm } from "./sampleTruck.js";

const made = (name) => ({ added: true, position: { id: name, name }, message: `Added “${name}”.` });
const there = { added: false, position: { id: "t1", name: "Delivery truck (sample)" }, message: "Already there." };

test("the first click adds it, with no question", async () => {
  const calls = [];
  const out = await addSampleTruck(async (again) => { calls.push(again); return made("Delivery truck (sample)"); },
    async () => assert.fail("nothing to ask"));
  assert.deepEqual(calls, [false]);
  assert.equal(out.added, true);
});

test("with a copy there it asks; another copy only when the person says so", async () => {
  const calls = [];
  const add = async (again) => { calls.push(again); return again ? made("Delivery truck (sample 2)") : there; };
  const kept = await addSampleTruck(add, async () => false);
  assert.deepEqual(calls, [false]);
  assert.equal(kept.added, false);
  assert.equal(kept.position.id, "t1");
  const asked = [];
  const again = await addSampleTruck(add, async (opts) => { asked.push(opts); return true; });
  assert.deepEqual(calls, [false, false, true]);
  assert.equal(again.position.name, "Delivery truck (sample 2)");
  assert.match(asked[0].body, /Delivery truck \(sample\)/);
});

test("the question names the action and isn't a warning", () => {
  const q = normaliseConfirm(anotherCopyConfirm("Delivery truck (sample)"));
  assert.equal(q.confirmLabel, "Add another copy");
  assert.equal(q.cancelLabel, "Keep the one I have");
  assert.equal(q.destructive, false);
});
