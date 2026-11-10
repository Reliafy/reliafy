import test from "node:test";
import assert from "node:assert/strict";
import { normaliseConfirm } from "./confirm.js";
import {
  OPEN_SAMPLE_PRODUCT_LABEL, OPEN_SAMPLE_UNITS_LABEL, SAMPLES, SAMPLE_PRODUCT_LABEL, addSample, addedNote, anotherCopyConfirm, hasCopy,
  sampleProductId, sampleProductView, sampleUnitsPath,
} from "./sampleProduct.js";

const NAME = "Survey quadcopter";
const made = (name) => ({ added: true, product: { id: name, name }, position: { id: name, name }, message: `Added “${name}”.` });
const there = { added: false, product: { id: "p1", name: NAME }, position: { id: "p1", name: NAME }, message: "Already there." };

test("the first click adds it, with no question", async () => {
  const calls = [];
  const out = await addSample(async (again) => { calls.push(again); return made(NAME); },
    async () => assert.fail("nothing to ask"));
  assert.deepEqual(calls, [false]);
  assert.equal(out.added, true);
});

test("with a copy there it asks; another copy only when the person says so", async () => {
  const calls = [];
  const add = async (again) => { calls.push(again); return again ? made("Survey quadcopter 2") : there; };
  const kept = await addSample(add, async () => false);
  assert.deepEqual(calls, [false]);
  assert.equal(kept.added, false);
  assert.equal(kept.position.id, "p1");
  const asked = [];
  const again = await addSample(add, async (opts) => { asked.push(opts); return true; });
  assert.deepEqual(calls, [false, false, true]);
  assert.equal(again.position.name, "Survey quadcopter 2");
  assert.equal(asked[0].title, "Add another Survey quadcopter?");
  assert.equal(asked[0].body, "Survey quadcopter is already in your workspace as “Survey quadcopter”. Add another copy, or keep the one you have.");
});

test("the question names the action and isn't a warning", () => {
  const q = normaliseConfirm(anotherCopyConfirm(NAME));
  assert.equal(q.confirmLabel, "Add another copy");
  assert.equal(q.cancelLabel, "Keep the one I have");
  assert.equal(q.destructive, false);
});

test("nothing that adds or opens it says sample", () => {
  const said = [SAMPLE_PRODUCT_LABEL, OPEN_SAMPLE_PRODUCT_LABEL, OPEN_SAMPLE_UNITS_LABEL, ...Object.values(SAMPLES.product),
    ...Object.values(anotherCopyConfirm("Survey quadcopter"))].filter((v) => typeof v === "string");
  assert.equal(SAMPLE_PRODUCT_LABEL, "Add the Survey quadcopter");
  assert.equal(OPEN_SAMPLE_PRODUCT_LABEL, "Open the Survey quadcopter");
  assert.equal(SAMPLES.product.added, "Added the Survey quadcopter.");
  for (const text of said) assert.doesNotMatch(text, /sample/i);
});

test("Products' header offers it only while the workspace has no copy", () => {
  assert.equal(hasCopy(null), false);
  assert.equal(hasCopy([{ id: "a", name: "Pump skid", template: null }]), false);
  assert.equal(hasCopy([{ id: "a", name: "Pump skid", template: null }, { id: "b", name: "Survey quadcopter", template: "survey-quadcopter" }]), true);
  // One renamed since is still a copy.
  assert.equal(hasCopy([{ id: "b", name: "Inspection drone", template: "survey-quadcopter" }]), true);
});

test("once added, its page says so, and names any record the workspace had no room for", () => {
  assert.deepEqual(addedNote(made(NAME)), { text: "Added the Survey quadcopter.", fade: true });
  const kept = "Your plan's storage had no room for Quadcopter avionics — Exponential: that one stays linked to the shared library's record.";
  assert.deepEqual(addedNote({ ...made(NAME), kept_note: kept }), { text: `Added the Survey quadcopter. ${kept}`, fade: false });
  assert.equal(addedNote(there), null);
});

test("the product's id comes from either shape of the answer", () => {
  assert.equal(sampleProductId({ added: true, product: { id: "p1" }, position: { id: "p1" } }), "p1");
  assert.equal(sampleProductId({ added: false, position: { id: "p2" } }), "p2");
});

test("one ready-made product (no truck, no asset-tree UAV)", () => {
  assert.deepEqual(Object.keys(SAMPLES), ["product"]);
});

test("the Explorer opens it on the FME(C)A tab from there, on the RCM tab otherwise", () => {
  assert.equal(sampleProductView("fmea"), "fmea");
  assert.equal(sampleProductView("rcm"), "rcm");
  assert.equal(sampleProductView("summary"), "rcm");
  assert.equal(sampleProductView(undefined), "rcm");
});

test("Assets opens the first item built from it, on its tree, adding nothing twice", async () => {
  const fresh = { ...made(NAME), items: [{ serial: "SQ-0007", top_position_id: "t7" }, { serial: "SQ-0008", top_position_id: "t8" }] };
  const calls = [];
  assert.equal(await sampleUnitsPath(async (again) => { calls.push(again); return fresh; },
    async () => assert.fail("the answer carries the items")), "/asset-register/explorer?arrange=positions&root=t7");
  assert.deepEqual(calls, [false]);
  // A copy there already: its items are read.
  assert.equal(await sampleUnitsPath(async () => there, async (id) => {
    assert.equal(id, "p1");
    return { items: [{ serial: "SQ-0009", top_position_id: "t9" }] };
  }), "/asset-register/explorer?arrange=positions&root=t9");
  // No item built: the product's page.
  assert.equal(await sampleUnitsPath(async () => there, async () => ({ items: [] })), "/products/p1");
});
