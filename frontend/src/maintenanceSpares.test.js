import { test } from "node:test";
import assert from "node:assert/strict";
import { entryText, partChoices, roleLabel, stockText } from "./maintenanceSpares.js";

const part = (id, number, onHand = 0, stock = []) => ({ id, part_number: number, name: number, on_hand: onHand, stock });

test("stock reads as how many and where", () => {
  assert.equal(stockText(part("a", "A1")), "none in stock");
  assert.equal(stockText(part("a", "A1", 3, [{ location: { name: "Store" }, quantity: 2 },
    { location: { name: "Van" }, quantity: 1 }, { location: { name: "Shed" }, quantity: 0 }])),
  "3 on hand · Store: 2, Van: 1");
  assert.equal(stockText(null), "");
});

test("a work order offers the parts list first, successors before what they replace", () => {
  const a = part("a", "A1"), b = part("b", "B1", 1), c = part("c", "C1"), kit = part("k", "K1"), other = part("o", "O1");
  const suggested = [
    { role: "replacement", quantity: 1, part: a, use_instead: b, alternatives: [c] },
    { role: "component", quantity: 2, part: kit, use_instead: null, alternatives: [c] },
  ];
  const { listed, others } = partChoices(suggested, [a, b, c, kit, other]);
  assert.deepEqual(listed.map((p) => [p.part_number, p.note, p.quantity]), [
    ["B1", "use instead of A1", 1], ["A1", "superseded", 1], ["C1", "alternative to A1", 1], ["K1", "component", 2]]);
  assert.deepEqual(others.map((p) => p.id), ["o"]);
  assert.deepEqual(partChoices(undefined, [other]).others, [other]);
});

test("an entry says its quantity and any critical minimum", () => {
  assert.equal(entryText({ quantity: 2, critical: false }), "2 per job");
  assert.equal(entryText({ quantity: 1, critical: true, min_on_hand: 3 }), "1 per job · critical: keep 3");
  assert.equal(roleLabel("consumable"), "Consumable");
});
