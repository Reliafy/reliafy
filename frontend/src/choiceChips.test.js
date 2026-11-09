import { test } from "node:test";
import assert from "node:assert/strict";
import { chipPick, chipStep, chipTabStop } from "./choiceChips.js";

test("the arrows move round the chips; other keys don't", () => {
  assert.equal(chipStep(0, "ArrowRight", 5), 1);
  assert.equal(chipStep(4, "ArrowRight", 5), 0);
  assert.equal(chipStep(0, "ArrowLeft", 5), 4);
  assert.equal(chipStep(2, "ArrowUp", 5), 1);
  assert.equal(chipStep(2, "ArrowDown", 5), 3);
  assert.equal(chipStep(2, "Tab", 5), null);
  assert.equal(chipStep(0, "ArrowRight", 0), null);
});

test("choosing the chosen chip clears it only when the chips can be cleared", () => {
  assert.equal(chipPick("safety", "safety", true), "");
  assert.equal(chipPick("safety", "safety", false), "safety");
  assert.equal(chipPick("hidden", "safety", true), "hidden");
});

test("Tab lands on the chosen chip, else the first", () => {
  const opts = [{ value: "a" }, { value: "b" }, { value: "c" }];
  assert.equal(chipTabStop(opts, "b"), 1);
  assert.equal(chipTabStop(opts, ""), 0);
});
