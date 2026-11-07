import { test } from "node:test";
import assert from "node:assert/strict";
import { NOTES_LIMIT, checkNotes, hasNotes, hasNotesField, notesChanged, notesCount, notesPrompt, notesTip } from "./rcmNotes.js";

const row = (type, ref = {}) => ({ type, key: "k", ref });

test("every RCM row kind carries notes, except a function's one old standard text", () => {
  for (const t of ["fn", "std", "fail", "mode"]) assert.equal(hasNotesField(row(t)), true, t);
  assert.equal(hasNotesField(row("std", { legacy: true })), false);
  for (const t of ["pos", "nostd", "unassigned", "cause", "task"]) assert.equal(hasNotesField(row(t)), false, t);
  assert.equal(hasNotesField(null), false);
});

test("the mark shows on rows with notes, its tooltip the first line with words in it", () => {
  assert.equal(hasNotes(row("fn", { notes: "" })), false);
  assert.equal(hasNotes(row("fn", { notes: "   \n " })), false);
  assert.equal(hasNotes(row("fn", {})), false);
  assert.equal(hasNotes(row("std", { notes: "AS 3633", legacy: true })), false);
  const r = row("std", { notes: "\n  Set by AS 3633 for public pools.  \nThe plaster needs it too." });
  assert.equal(hasNotes(r), true);
  assert.equal(notesTip(r), "Set by AS 3633 for public pools.");
  assert.equal(notesTip(row("mode", { notes: "a".repeat(200) })).length, 120);
  assert.ok(notesTip(row("mode", { notes: "a".repeat(200) })).endsWith("…"));
  assert.equal(notesTip(row("fail", { notes: "Line one\r\nLine two" })), "Line one");
  assert.equal(notesTip(row("fail", {})), "");
});

test("the empty section says what notes are for, by kind", () => {
  assert.equal(notesPrompt(row("std")), "Why this standard is here, what it rests on.");
  assert.equal(notesPrompt(row("fail")), "Why this failure is here, what it rests on.");
  assert.equal(notesPrompt(row("mode")), "Why this failure mode is here, what it rests on.");
  assert.equal(notesPrompt(row("fn")), "Why this function is here, what it rests on.");
});

test("notes are checked as the server checks them: trimmed, line breaks kept, at most 4,000 characters", () => {
  assert.deepEqual(checkNotes("  One\r\nTwo\rThree  "), { value: "One\nTwo\nThree" });
  assert.deepEqual(checkNotes(null), { value: "" });
  assert.deepEqual(checkNotes("x".repeat(NOTES_LIMIT)), { value: "x".repeat(NOTES_LIMIT) });
  assert.match(checkNotes("x".repeat(NOTES_LIMIT + 1)).error, /at most 4,000 characters; these are 4,001/);
  assert.equal(notesChanged("Same", "  Same \n"), false);
  assert.equal(notesChanged("", "New"), true);
  assert.equal(notesChanged("Old", ""), true);
  assert.equal(notesCount("abc").text, "3 / 4,000");
  assert.equal(notesCount("x".repeat(3700)).tone, "near");
  assert.equal(notesCount("x".repeat(4001)).over, true);
});
