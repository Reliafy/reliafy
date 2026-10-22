// Run with: node --test src/
// Names and titles: the 200-character limit shown before the server refuses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SHORT_TEXT, lengthNote, textLength, tooLong } from "./maintenanceText.js";

test("length is counted as the server counts it: trimmed, an emoji is one character", () => {
  assert.equal(textLength("  Grease bearings  "), 15);
  assert.equal(textLength("🛠️ pump"), 7);
  assert.equal(textLength(null), 0);
  assert.equal(SHORT_TEXT, 200);
});

test("well within the limit says nothing; near it counts; past it says what to do", () => {
  assert.equal(lengthNote("a".repeat(160)), null);
  assert.deepEqual(lengthNote("a".repeat(170)), { text: "170 / 200 characters", over: false });
  assert.deepEqual(lengthNote("a".repeat(200)), { text: "200 / 200 characters", over: false });
  assert.deepEqual(lengthNote("a".repeat(397), SHORT_TEXT, "put the detail in the instructions"),
    { text: "397 / 200 characters: shorten it and put the detail in the instructions.", over: true });
  assert.ok(tooLong("a".repeat(201)));
  assert.ok(!tooLong("a".repeat(200)));
});
