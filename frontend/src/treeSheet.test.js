import { test } from "node:test";
import assert from "node:assert/strict";
import { doneText, exportChoices, importBlocker, notInFileText, previewLines, roomText, sortedByRow, whereText } from "./treeSheet.js";

const PREVIEW = {
  dry_run: true, ok: false, rows: 650, positions_created: 312, positions_updated: 4, positions_moved: 2,
  positions_unchanged: 1, not_in_file: 41, locations_created: 40, classes_created: 18, items_created: 290,
  items_updated: 0, problem_count: 3,
  problems: [{ sheet: "Hierarchy", row: 12, text: "b" }, { sheet: "Locations", row: 3, text: "c" }, { sheet: "Hierarchy", row: 5, text: "a" }],
  limits: { positions: { now: 100, adding: 312, max: 20000, room: 19900, fits: true } },
  summary: "Will create 312 positions, 40 locations, 18 classes and 290 items.",
};

test("the preview's lines say what changes, in order, leaving out noughts", () => {
  assert.deepEqual(previewLines(PREVIEW).map((l) => l.text), [
    "312 new positions", "4 positions updated", "2 positions moved", "40 new locations", "18 new item classes",
    "290 new items fitted", "1 position already as the file has it",
  ]);
  assert.deepEqual(previewLines({ dry_run: false, positions_created: 1, classes_created: 1 }).map((l) => l.text),
    ["1 position made", "1 item class made"]);
  assert.deepEqual(previewLines(null), []);
});

test("what isn't in the file, and what fits", () => {
  assert.match(notInFileText(PREVIEW), /^41 positions in Reliafy .* aren't in the file\. They stay as they are: an import never deletes\.$/);
  assert.equal(notInFileText({ not_in_file: 0 }), null);
  assert.equal(roomText(PREVIEW), "Fits: adds 312 positions, with room for 19,588 more.");
  assert.equal(roomText({ limits: { positions: { adding: 5, room: 2, fits: false } } }), "Doesn't fit: adds 5 positions, and there's room for 2.");
  assert.equal(roomText({ limits: { positions: { adding: 0, room: 2, fits: true } } }), null);
});

test("problems are listed by sheet, then row, with where they are", () => {
  assert.deepEqual(sortedByRow(PREVIEW.problems).map(whereText), ["Row 5", "Row 12", "Locations, row 3"]);
  assert.equal(whereText({ sheet: "Hierarchy", row: null }), "File");
  assert.equal(whereText({ sheet: "Classes", row: null }), "Classes sheet");
});

test("Import waits for a clean check with something to change", () => {
  assert.match(importBlocker(null), /Check the file/);
  assert.match(importBlocker(PREVIEW), /Fix the problems/);
  assert.equal(importBlocker({ ...PREVIEW, problems: [], problem_count: 0 }), null);
  assert.match(importBlocker({ positions_unchanged: 3, problems: [] }), /already matches/);
  assert.equal(importBlocker(PREVIEW, { viewOnly: "View only" }), "View only");
  assert.equal(doneText({ summary: "Created 3 positions." }), "Imported. Created 3 positions.");
});

test("export offers the branch it was opened from", () => {
  assert.deepEqual(exportChoices(null).map((c) => c.id), ["all"]);
  assert.deepEqual(exportChoices({ id: "p", name: "Unit 2" }).map((c) => c.label), ["The whole tree", "This branch: Unit 2"]);
});
