import { test } from "node:test";
import assert from "node:assert/strict";
import {
  bomImportSummary, levelsIn, partsForest, positionsPlanSummary, qtyNumber, qtyText, treeKeys,
} from "./maintenanceStructure.js";

test("a line's quantity reads without float noise", () => {
  assert.equal(qtyText(2), "× 2");
  assert.equal(qtyText(0.1 + 0.2), "× 0.3");
  assert.equal(qtyText(null), "");
  assert.equal(qtyNumber("1.50"), "1.5");
  assert.equal(qtyNumber("x"), "");
});

const parts = [
  { id: "sys", part_number: "SYS", name: "System", level: "System", used_in: 0, components: [{ id: "pu", qty: 2, ref: "P1, P2" }] },
  { id: "pu", part_number: "PU", name: "Pump unit", level: "Subsystem", used_in: 1,
    components: [{ id: "brg", qty: 2, ref: "" }, { id: "mtr", qty: 1, ref: "M1" }] },
  { id: "mtr", part_number: "MTR", name: "Motor", level: "LRU", used_in: 1, components: [{ id: "brg", qty: 2, ref: "" }] },
  { id: "brg", part_number: "BRG", name: "Bearing", level: "Component", used_in: 2, components: [] },
  { id: "pad", part_number: "PAD", name: "Brake pad", used_in: 0, components: [] },
];

test("the catalogue reads as structures, a shared part under each assembly", () => {
  const { roots, loose } = partsForest(parts);
  assert.deepEqual(roots.map((r) => r.part_number), ["SYS"]);
  assert.deepEqual(loose.map((p) => p.part_number), ["PAD"]);
  const pu = roots[0].children[0];
  assert.equal(pu.qty, 2);
  assert.equal(pu.ref, "P1, P2");
  assert.deepEqual(pu.children.map((c) => c.part_number), ["BRG", "MTR"]);
  assert.deepEqual(pu.children[1].children.map((c) => c.part_number), ["BRG"]);
  assert.equal(pu.children[1].children[0].key, "sys/pu/mtr/brg");
  // A loop in the data (never written, but never trusted) stops instead of running forever.
  const looped = partsForest([{ id: "a", part_number: "A", used_in: 0, components: [{ id: "b", qty: 1 }] },
    { id: "b", part_number: "B", used_in: 1, components: [{ id: "c", qty: 1 }] },
    { id: "c", part_number: "C", used_in: 1, components: [{ id: "b", qty: 1 }] }]);
  assert.deepEqual(looped.roots.map((r) => r.part_number), ["A"]);
  assert.deepEqual(looped.roots[0].children[0].children[0].children, []);
});

test("tree keys and the levels found in a tree", () => {
  const tree = { id: "sys", level: "System", children: [{ id: "pu", level: "Subsystem", children: [
    { id: "brg", level: "Component", children: [] }, { id: "x", level: "Widget", children: [] }, { id: "y", level: "", children: [] }] }] };
  assert.deepEqual(treeKeys(tree), ["sys", "sys/pu", "sys/pu/brg", "sys/pu/x", "sys/pu/y"]);
  assert.deepEqual(levelsIn(tree, ["System", "Subsystem", "Assembly", "Component"]), ["System", "Subsystem", "Component", "Widget"]);
  assert.deepEqual(levelsIn(null), []);
});

test("a BOM import and positions from a structure, each in a sentence", () => {
  assert.equal(bomImportSummary({ dry_run: true, counts: { parts_created: 6, lines_added: 6 } }),
    "It would add 6 parts, add 6 structure lines.");
  assert.equal(bomImportSummary({ dry_run: false, counts: { unchanged: 6 } }), "Nothing changed; 6 lines already as the file says.");
  assert.equal(bomImportSummary({ dry_run: true, counts: { errors: 1 } }), "1 error: nothing would be imported.");
  assert.equal(bomImportSummary({ dry_run: false, counts: { lines_changed: 1, conflicts: 2, levels_added: 1 } }),
    "Changed 1 line, added 1 indenture level; 2 differences left as they are.");
  assert.equal(bomImportSummary(null), "");
  assert.equal(positionsPlanSummary({ dry_run: true, counts: { create: 5, reuse: 0, parts_list: 5, skipped: 0 } }),
    "It would make 5 positions, put the part on 5 parts lists.");
  assert.equal(positionsPlanSummary({ dry_run: false, counts: { create: 0, reuse: 5, parts_list: 0, skipped: 2 } }),
    "Made 0 positions, used 5 positions already there; 2 lines with part quantities (a consumable?) left off.");
});
