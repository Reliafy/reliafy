// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_SECTIONS, addSection, applyDraft, moveSection, pickerGroups, removeSection, reportBody, setNote,
} from "./reportComposer.js";
import { printZoom } from "./printFit.js";

const item = (id, extra = {}) => ({ collection: "models", artifact_id: id, name: `M${id}`, kind: "Life model", ...extra });

test("an item is added once, and not past the limit", () => {
  let s = addSection([], item("a"));
  s = addSection(s, item("a"));
  assert.deepEqual(s.map((x) => x.artifact_id), ["a"]);
  assert.equal(s[0].note, "");
  const full = Array.from({ length: MAX_SECTIONS }, (_, i) => item(String(i)));
  assert.equal(addSection(full, item("x")), full);
});

test("sections move, stop at the ends, and are removed", () => {
  const s = [item("a"), item("b"), item("c")];
  assert.deepEqual(moveSection(s, 0, 1).map((x) => x.artifact_id), ["b", "a", "c"]);
  assert.equal(moveSection(s, 0, -1), s);
  assert.equal(moveSection(s, 2, 1), s);
  assert.deepEqual(removeSection(s, 1).map((x) => x.artifact_id), ["a", "c"]);
  assert.equal(setNote(s, 1, "hi")[1].note, "hi");
});

test("a draft fills the introduction and notes, keeping a note it skips", () => {
  const s = [item("a", { note: "mine" }), item("b", { note: "keep" })];
  const out = applyDraft("old", s, { introduction: " New intro. ", notes: ["Drafted.", ""] });
  assert.equal(out.introduction, "New intro.");
  assert.deepEqual(out.sections.map((x) => x.note), ["Drafted.", "keep"]);
  assert.equal(applyDraft("old", s, { introduction: "", notes: [] }).introduction, "old");
});

test("the API body carries only what the server takes", () => {
  const body = reportBody({ title: " T ", author: " A ", introduction: "I", sections: [item("a", { note: "n" })] });
  assert.deepEqual(body, { title: "T", author: "A", introduction: "I",
    sections: [{ collection: "models", artifact_id: "a", note: "n" }] });
});

test("the picker groups own items by kind, then samples, without chosen items", () => {
  const items = [item("a"), item("s", { is_sample: true }), { ...item("r"), collection: "rbds", kind: "Block diagram" }];
  const groups = pickerGroups(items, [item("a")]);
  assert.deepEqual(groups.map(([label, list]) => [label, list.map((x) => x.artifact_id)]),
    [["Block diagram", ["r"]], ["Samples", ["s"]]]);
});

test("print zoom shrinks a drawing to its room and never enlarges it", () => {
  assert.equal(printZoom(1000, 640), 0.64);
  assert.equal(printZoom(500, 640), 1);
  assert.equal(printZoom(0, 640), 1);
  assert.equal(printZoom(1000, 0), 1);
  assert.ok(printZoom(683, 655) * 683 <= 655);
});
