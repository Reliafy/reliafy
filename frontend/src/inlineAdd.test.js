import test from "node:test";
import assert from "node:assert/strict";
import { CLOSED, commitAction, inlineAddReducer, refusalOf } from "./inlineAdd.js";

const run = (actions, from = CLOSED) => actions.reduce(inlineAddReducer, from);

test("the add row starts a new, empty row; starting again keeps what's typed", () => {
  const s = run([{ type: "start" }]);
  assert.deepEqual(s, { open: true, text: "", busy: false, error: null, onText: false });
  const typed = run([{ type: "start" }, { type: "type", text: "pH 7.2-7.8" }, { type: "start" }]);
  assert.equal(typed.text, "pH 7.2-7.8");
});

test("Enter (or leaving the row) saves the trimmed text; nothing more is sent while it saves", () => {
  const s = run([{ type: "start" }, { type: "type", text: "  pH 7.2-7.8 " }]);
  assert.deepEqual(commitAction(s), { act: "save", text: "pH 7.2-7.8" });
  const saving = inlineAddReducer(s, { type: "saving" });
  assert.equal(saving.busy, true);
  assert.deepEqual(commitAction(saving), { act: "wait" }); // a second Enter, or the blur after it
  assert.equal(inlineAddReducer(saving, { type: "type", text: "x" }).text, "  pH 7.2-7.8 "); // read-only while saving
  assert.equal(inlineAddReducer(saving, { type: "cancel" }).open, true); // Esc doesn't drop a save under way
});

test("once saved the row closes, ready for the next; consecutive adds each start empty", () => {
  let s = run([{ type: "start" }, { type: "type", text: "pH 7.2-7.8" }, { type: "saving" }, { type: "saved" }]);
  assert.deepEqual(s, CLOSED);
  s = run([{ type: "start" }], s);
  assert.equal(s.text, "");
  s = run([{ type: "type", text: "Free chlorine 1-3 ppm" }], s);
  assert.deepEqual(commitAction(s), { act: "save", text: "Free chlorine 1-3 ppm" });
});

test("Esc, or an empty box, cancels quietly", () => {
  const s = run([{ type: "start" }, { type: "type", text: "half typed" }, { type: "cancel" }]);
  assert.deepEqual(s, CLOSED);
  assert.deepEqual(commitAction(run([{ type: "start" }, { type: "type", text: "   " }])), { act: "cancel" });
  assert.deepEqual(commitAction(CLOSED), { act: "stay" });
});

test("a refusal keeps the text in the row with the reason; typing clears the reason", () => {
  let s = run([{ type: "start" }, { type: "type", text: "pH 7.2-7.8" }, { type: "saving" }, { type: "failed", error: "That function was deleted." }]);
  assert.deepEqual(s, { open: true, text: "pH 7.2-7.8", busy: false, error: "That function was deleted.", onText: true });
  assert.deepEqual(commitAction(s), { act: "save", text: "pH 7.2-7.8" }); // Enter tries again
  s = inlineAddReducer(s, { type: "type", text: "pH 7.2-7.6" });
  assert.equal(s.error, null);
  assert.equal(inlineAddReducer(s, { type: "failed" }).error, "It couldn't be added.");
});

test("a check stops a save the server would refuse (a task with no interval), the row kept", () => {
  const s = run([{ type: "start" }, { type: "type", text: "Clean the cell" }]);
  const why = (iv) => () => (iv ? null : "Enter how often: an interval above 0.");
  assert.deepEqual(commitAction(s, { check: why("") }), { act: "invalid", error: "Enter how often: an interval above 0." });
  assert.deepEqual(commitAction(s, { check: why("6") }), { act: "save", text: "Clean the cell" });
  // The reason is about the interval, not the name.
  const kept = inlineAddReducer(s, { type: "failed", error: "Enter how often: an interval above 0.", check: true });
  assert.equal(kept.onText, false);
  assert.equal(kept.text, "Clean the cell");
  // An empty name still cancels, whatever the check says.
  assert.deepEqual(commitAction(run([{ type: "start" }]), { check: why("") }), { act: "cancel" });
});

test("a save's answer: a string is a refusal, anything else is done", () => {
  assert.equal(refusalOf("No."), "No.");
  assert.equal(refusalOf(undefined), null);
  assert.equal(refusalOf("abc123".length), null);
  assert.equal(refusalOf(""), null);
});
