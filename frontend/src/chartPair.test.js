import test from "node:test";
import assert from "node:assert/strict";
import { MIN_CHART, PAIR_GAP, pairLayout, shownItem } from "./chartPair.js";

test("two charts sit side by side only where each gets the minimum width", () => {
  const fits = 2 * MIN_CHART + PAIR_GAP;
  assert.equal(pairLayout({ width: fits }), "side");
  assert.equal(pairLayout({ width: fits, together: true }), "side");
  assert.equal(pairLayout({ width: 1600 }), "side");
  assert.equal(pairLayout({ width: fits - 1 }), "switch");
});

test("too thin: alternatives get a switch, charts read together stack", () => {
  // A model tab at 1440 wide, beside a 268 px panel.
  assert.equal(pairLayout({ width: 822 }), "switch");
  assert.equal(pairLayout({ width: 822, together: true }), "stack");
});

test("a phone stacks both, whatever they are", () => {
  assert.equal(pairLayout({ width: 360, phone: true }), "stack");
  assert.equal(pairLayout({ width: 360, phone: true, together: true }), "stack");
  // Before the box is measured too: a phone needs no measurement.
  assert.equal(pairLayout({ width: null, phone: true }), "stack");
});

test("no layout until the box is measured", () => {
  assert.equal(pairLayout({ width: null }), null);
  assert.equal(pairLayout({ width: undefined, together: true }), null);
  assert.equal(pairLayout({ width: NaN }), null);
});

test("a caller's own minimum and gap", () => {
  assert.equal(pairLayout({ width: 700, min: 340, gap: 10 }), "side");
  assert.equal(pairLayout({ width: 689, min: 340, gap: 10 }), "switch");
});

test("the switch shows the chosen item, or the first when it has gone", () => {
  const items = [{ id: "a" }, null, { id: "b" }];
  assert.equal(shownItem(items, "b").id, "b");
  assert.equal(shownItem(items, null).id, "a");
  assert.equal(shownItem(items, "gone").id, "a");
  assert.equal(shownItem([], "a"), null);
  assert.equal(shownItem(null, "a"), null);
});
