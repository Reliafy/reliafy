import test from "node:test";
import assert from "node:assert/strict";
import { fitTabs, nextStop } from "./tabsFit.js";

// Seven tabs of 100 px, a 40 px "⋯ N", no gap unless said.
const seven = Array(7).fill(100);

test("everything fits: every tab shows and there's no ⋯", () => {
  assert.deepEqual(fitTabs(seven, 700, 40, 0), { shown: [0, 1, 2, 3, 4, 5, 6], hidden: [] });
  assert.deepEqual(fitTabs([], 0, 40, -1), { shown: [], hidden: [] });
  // The gap counts: 7 × 100 + 6 × 4 = 724.
  assert.deepEqual(fitTabs(seven, 723, 40, 0, 4).hidden.length > 0, true);
  assert.deepEqual(fitTabs(seven, 724, 40, 0, 4).hidden, []);
});

test("too narrow: the tabs fold from the right into ⋯, leaving room for it", () => {
  // 600 px: five tabs (500) and ⋯ (40) fit; six (600) and ⋯ don't.
  assert.deepEqual(fitTabs(seven, 600, 40, 0), { shown: [0, 1, 2, 3, 4], hidden: [5, 6] });
  assert.deepEqual(fitTabs(seven, 540, 40, 2), { shown: [0, 1, 2, 3, 4], hidden: [5, 6] });
  assert.deepEqual(fitTabs(seven, 539, 40, 2), { shown: [0, 1, 2, 3], hidden: [4, 5, 6] });
  // With a gap: five tabs, four gaps, the gap before ⋯ and ⋯ = 500 + 16 + 4 + 40 = 560.
  assert.deepEqual(fitTabs(seven, 560, 40, 0, 4).shown, [0, 1, 2, 3, 4]);
  assert.deepEqual(fitTabs(seven, 559, 40, 0, 4).shown, [0, 1, 2, 3]);
});

test("the selected tab is never folded: it takes the last slot and the one it displaces goes into ⋯", () => {
  assert.deepEqual(fitTabs(seven, 600, 40, 6), { shown: [0, 1, 2, 3, 6], hidden: [4, 5] });
  assert.deepEqual(fitTabs(seven, 600, 40, 5), { shown: [0, 1, 2, 3, 5], hidden: [4, 6] });
  // A wider selected tab can push one more into ⋯.
  const w = [100, 100, 100, 100, 100, 100, 180];
  assert.deepEqual(fitTabs(w, 600, 40, 6), { shown: [0, 1, 2, 6], hidden: [3, 4, 5] });
});

test("so narrow only one tab fits: the selected one (or the first) and ⋯", () => {
  assert.deepEqual(fitTabs(seven, 150, 40, 3), { shown: [3], hidden: [0, 1, 2, 4, 5, 6] });
  assert.deepEqual(fitTabs(seven, 100, 40, -1), { shown: [0], hidden: [1, 2, 3, 4, 5, 6] });
});

test("the row's keys: ← → wrap over the tabs and ⋯, Home and End go to the ends", () => {
  assert.equal(nextStop("ArrowRight", 0, 6), 1);
  assert.equal(nextStop("ArrowRight", 5, 6), 0);
  assert.equal(nextStop("ArrowLeft", 0, 6), 5);
  assert.equal(nextStop("Home", 3, 6), 0);
  assert.equal(nextStop("End", 3, 6), 5);
  // ↓ and Enter aren't moves: on ⋯ they open its menu.
  assert.equal(nextStop("ArrowDown", 3, 6), null);
  assert.equal(nextStop("Enter", 3, 6), null);
  assert.equal(nextStop("ArrowRight", 0, 0), null);
});
