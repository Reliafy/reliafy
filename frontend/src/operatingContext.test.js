import test from "node:test";
import assert from "node:assert/strict";
import { CONTEXT_LIMIT, CONTEXT_PROMPT, charsLeft, checkContext, contextChanged } from "./operatingContext.js";

test("the text is trimmed, and empty clears it", () => {
  assert.deepEqual(checkContext("  Runs 20 hours a day.\n\nSalt air.  "), { value: "Runs 20 hours a day.\n\nSalt air." });
  assert.deepEqual(checkContext("   "), { value: "" });
  assert.deepEqual(checkContext(null), { value: "" });
});

test("over the limit says how long it is and what to do", () => {
  assert.deepEqual(checkContext("x".repeat(CONTEXT_LIMIT)), { value: "x".repeat(CONTEXT_LIMIT) });
  const { error } = checkContext("x".repeat(CONTEXT_LIMIT + 5));
  assert.equal(error, "The operating context is at most 4,000 characters; this one is 4,005. Shorten it.");
});

test("a change is a change once trimmed", () => {
  assert.equal(contextChanged("Indoors.", " Indoors. "), false);
  assert.equal(contextChanged("", "Indoors."), true);
  assert.equal(contextChanged(undefined, ""), false);
});

test("characters left only near the limit", () => {
  assert.equal(charsLeft("short"), "");
  assert.equal(charsLeft("x".repeat(CONTEXT_LIMIT - 1)), "1 character left");
  assert.equal(charsLeft("x".repeat(CONTEXT_LIMIT - 150)), "150 characters left");
  assert.equal(charsLeft("x".repeat(CONTEXT_LIMIT + 2)), "2 characters too many");
});

test("the empty prompt is plain and never says duty", () => {
  assert.match(CONTEXT_PROMPT, /^How is it used\?/);
  assert.doesNotMatch(CONTEXT_PROMPT.toLowerCase(), /duty/);
});
