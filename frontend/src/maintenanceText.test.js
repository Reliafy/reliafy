// Run with: node --test src/
// Names and titles: the 200-character limit shown before the server refuses.
import { test } from "node:test";
import assert from "node:assert/strict";
import { SHORT_TEXT, charCount, lengthNote, textLength, tooLong } from "./maintenanceText.js";

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

test("the 200-character counter: quiet, amber near the limit, red past it", () => {
  const a = (n) => "a".repeat(n);
  assert.deepEqual(charCount(""), { n: 0, max: 200, text: "0 / 200", tone: "", over: false, blocked: false, message: "" });
  assert.equal(charCount(a(179)).tone, "");
  assert.equal(charCount(a(180)).tone, "near"); // the last tenth
  const c190 = charCount(a(190));
  assert.equal(c190.text, "190 / 200");
  assert.equal(c190.tone, "near");
  assert.equal(c190.blocked, false);
  const c200 = charCount(a(200));
  assert.equal(c200.tone, "near");
  assert.equal(c200.over, false);
  assert.equal(c200.blocked, false);
  // Counted as the server counts: trimmed.
  assert.equal(charCount(`  ${a(200)}  `).over, false);
  // A new text past the limit can't be saved.
  const c201 = charCount(a(201));
  assert.equal(c201.tone, "over");
  assert.equal(c201.blocked, true);
  assert.equal(c201.message, "Shorten it to 200 characters or fewer to save the change (it's 201).");
});

test("a text saved before the limit stays as it is, red, and a change can't be saved until it's short enough", () => {
  const long = "b".repeat(1203);
  const same = charCount(long, { before: long });
  assert.equal(same.tone, "over");
  assert.equal(same.text, "1,203 / 200");
  assert.equal(same.blocked, false); // untouched: nothing to save, nothing changed
  assert.equal(same.message, "Shorten it to 200 characters or fewer (it's 1,203).");
  const edited = charCount(long.slice(0, 900), { before: long });
  assert.equal(edited.blocked, true); // shorter, but still too long
  const shortened = charCount(long.slice(0, 200), { before: long });
  assert.equal(shortened.blocked, false);
  assert.equal(shortened.over, false);
  assert.equal(charCount("x".repeat(30), { max: 20 }).blocked, true);
});
