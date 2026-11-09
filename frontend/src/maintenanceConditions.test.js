import { test } from "node:test";
import assert from "node:assert/strict";
import {
  conditionImportSummary, conditionKindText, conditionText, pickable, sourcePath, sourceText,
} from "./maintenanceConditions.js";

const temp = { id: "t", name: "Ambient temperature", display: "Ambient temperature", kind: "value", unit: "°C" };
const outdoor = { id: "o", name: "Outdoor", display: "Outdoor", kind: "presence", unit: "" };

test("a condition reads with its value and unit", () => {
  assert.equal(conditionText({ condition: outdoor, value: null }), "Outdoor");
  assert.equal(conditionText({ condition: temp, value: 45 }), "Ambient temperature: 45 °C");
  assert.equal(conditionText({ condition: temp, value: 0.1 + 0.2 }), "Ambient temperature: 0.3 °C");
  assert.equal(conditionText({ condition: { ...temp, display: "Climate › Ambient temperature" }, value: 0 }),
    "Climate › Ambient temperature: 0 °C");
  assert.equal(conditionText(null), "");
  assert.equal(conditionKindText(temp), "value in °C");
  assert.equal(conditionKindText(outdoor), "applies or not");
  assert.equal(conditionKindText({ kind: "value", unit: "" }), "value");
});

test("where a condition comes from", () => {
  assert.equal(sourceText({ own: true, excluded: false }), "set here");
  assert.equal(sourceText({ own: true, excluded: true }), "excluded here");
  assert.equal(sourceText({ own: false, excluded: false, source: { name: "Site" } }), "from Site");
  assert.equal(sourceText({ own: false, excluded: true, source: { name: "Control room" } }), "excluded at Control room");
  assert.equal(sourcePath({ kind: "Location", id: "l1" }), "/asset-register/locations/l1");
  assert.equal(sourcePath({ kind: "Item", id: "i1" }), "/asset-register/items/i1");
  assert.equal(sourcePath({ kind: "Interface", id: "x" }), null);
});

test("the picker leaves out what's already set on the target, and an import reads as a sentence", () => {
  const view = { conditions: [{ own: true, condition: outdoor }, { own: false, condition: temp }], excluded_conditions: [] };
  assert.deepEqual(pickable([outdoor, temp], view).map((c) => c.id), ["t"]);
  assert.equal(conditionImportSummary({ dry_run: true, counts: { create: 3, update: 1, unchanged: 2, conflicts: 1, errors: 0 } }),
    "It would add 3 conditions, fill in 1 condition, 2 already there, 1 conflict left as they are.");
  assert.equal(conditionImportSummary({ dry_run: false, counts: { create: 1 } }), "Added 1 condition.");
  assert.equal(conditionImportSummary({ dry_run: true, counts: { errors: 1 } }), "1 error: nothing would be imported.");
});
