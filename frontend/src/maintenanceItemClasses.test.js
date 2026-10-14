import { test } from "node:test";
import assert from "node:assert/strict";
import {
  attributeRows, attributeText, attributeValueText, attributesBody, flattenClasses, importSummary, subtreeIds, viaText,
} from "./maintenanceItemClasses.js";

test("attributes read with their unit, and a choice with its options", () => {
  assert.equal(attributeText({ name: "Flow", unit: "m3/h", kind: "number" }), "Flow (m3/h)");
  assert.equal(attributeText({ name: "Stages", unit: "", kind: "number" }), "Stages");
  assert.equal(attributeText({ name: "Seal", kind: "choice", options: ["mechanical", "packing"] }), "Seal: mechanical / packing");
  assert.equal(attributeValueText({ kind: "number", unit: "m3/h", value: 45 }), "45 m3/h");
  assert.equal(attributeValueText({ kind: "number", unit: "", value: 0.1 + 0.2 }), "0.3");
  assert.equal(attributeValueText({ kind: "text", value: "bronze" }), "bronze");
  assert.equal(attributeValueText({ kind: "number", value: null }), "—");
  assert.equal(attributeValueText({ kind: "number", value: 0, unit: "bar" }), "0 bar");
});

test("the tree flattens parents first, and a subtree is the class and everything inside it", () => {
  const tree = [{ id: "r", children: [{ id: "p", children: [{ id: "c", children: [] }] }, { id: "f", children: [] }] },
    { id: "e", children: [] }];
  assert.deepEqual(flattenClasses(tree).map((c) => [c.id, c.depth]), [["r", 0], ["p", 1], ["c", 2], ["f", 1], ["e", 0]]);
  assert.deepEqual([...subtreeIds(tree, "p")].sort(), ["c", "p"]);
  assert.deepEqual([...subtreeIds(tree, "e")], ["e"]);
});

test("the attribute editor's rows go back to what the API takes", () => {
  const own = [{ name: "Seal", unit: "", kind: "choice", options: ["mechanical", "packing"] },
    { name: "Flow", unit: "m3/h", kind: "number", options: [] }];
  const rows = attributeRows(own);
  assert.equal(rows[0].options, "mechanical | packing");
  assert.deepEqual(attributesBody([...rows, { name: " ", unit: "", kind: "text", options: "" }]), own);
  assert.deepEqual(attributesBody([{ name: "Note ", unit: "", kind: "text", options: "x|y" }]),
    [{ name: "Note", unit: "", kind: "text", options: [] }]);
});

test("an import result reads as a sentence", () => {
  assert.equal(importSummary({ dry_run: true, counts: { create: 3, update: 1, unchanged: 2, conflicts: 1, errors: 0 } }),
    "It would add 3 classes, fill in 1 class, 2 already there, 1 conflict left as they are.");
  assert.equal(importSummary({ dry_run: false, counts: { create: 1, update: 0, unchanged: 0, conflicts: 0, errors: 0 } }),
    "Added 1 class.");
  assert.equal(importSummary({ dry_run: true, counts: { errors: 2 } }), "2 errors: nothing would be imported.");
  assert.equal(importSummary(null), "");
  assert.equal(viaText("part"), "from its part");
  assert.equal(viaText("item"), "");
});
