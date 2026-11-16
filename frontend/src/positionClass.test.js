import test from "node:test";
import assert from "node:assert/strict";
import { builtAsTitle, carriedAsTitle, classKey, classLabel, isDesignClass } from "./positionClass.js";

test("a design class is grouped by its key and shown by product and path", () => {
  const row = { position_class: "Motor", class_key: "design:abc", class_label: "UAV › Propulsion › Motor 1" };
  assert.equal(classKey(row), "design:abc");
  assert.equal(classLabel(row), "UAV › Propulsion › Motor 1");
  assert.equal(isDesignClass(row), true);
  const read = { position_class: "Motor", class: { class_key: "design:abc", position_class: "UAV › Motor 1" } };
  assert.equal(classKey(read), "design:abc");
  assert.equal(classLabel(read), "UAV › Motor 1");
});

test("any other class is its free text", () => {
  assert.equal(classKey({ position_class: " Pool pump " }), "Pool pump");
  assert.equal(classLabel({ position_class: "Pool pump" }), "Pool pump");
  assert.equal(isDesignClass({ position_class: "Pool pump" }), false);
  assert.equal(classKey({}), "");
  assert.equal(classKey(null), "");
});

test("the built-as and carried-as headings", () => {
  assert.equal(builtAsTitle(0), "Not built yet");
  assert.equal(builtAsTitle(1), "Built as 1 position");
  assert.equal(builtAsTitle(2), "Built as 2 positions");
  assert.equal(carriedAsTitle(3), "Carried as 3 locations");
});
