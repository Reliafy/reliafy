// Run with: node --test src/
// Positions linked to locations: inherited locations, where an item is, counts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { countsText, inheritedText, itemWhere, locationOptions } from "./maintenanceLocations.js";

test("a picker lists locations by their full path", () => {
  const options = locationOptions([
    { id: "b", name: "Substation 2", display: "Site › Area X › Substation 2" },
    { id: "a", name: "Area X", parent: { id: "s", name: "Site" } },
  ]);
  assert.deepEqual(options, [{ id: "a", label: "Site › Area X" }, { id: "b", label: "Site › Area X › Substation 2" }]);
  assert.deepEqual(locationOptions(null), []);
});

test("an inherited location says where it comes from", () => {
  assert.equal(inheritedText({ inherited: false }), "");
  assert.equal(inheritedText({ inherited: true, inherited_from: { name: "MCC-3", kind: "Position" } }),
    "inherited from MCC-3");
  assert.equal(inheritedText({ inherited: true, inherited_from: { name: "Engine", kind: "Item" } }),
    "from Engine, the item it's inside");
  assert.equal(inheritedText(null), "");
});

test("a fitted item is where its position is; a spare is where it's placed", () => {
  const fitted = itemWhere({ location: { id: "l", name: "Substation 2", display: "Site › Substation 2", how: "fitted",
    position: { id: "p", name: "Feeder 13" } } });
  assert.deepEqual(fitted, { label: "Site › Substation 2", locationId: "l", note: "where Feeder 13 is" });
  const placed = itemWhere({ location: { id: "s", name: "Store", how: "placed", since: "2026-10-01" } }, (d) => `on ${d}`);
  assert.deepEqual(placed, { label: "Store", locationId: "s", note: "placed on 2026-10-01" });
});

test("an item taken out and not placed is last at its position's location", () => {
  const page = itemWhere({ location: null, last_at: { location: { id: "l", name: "Substation 2" },
    position: { id: "p", name: "Feeder 13" }, since: "2026-10-09" } });
  assert.deepEqual(page, { label: "last at Substation 2", locationId: "l", note: "came out of Feeder 13 on 2026-10-09" });
  const unset = itemWhere({ location: null, last_at: { location: null, position: { name: "Feeder 13" } } });
  assert.equal(unset.label, "not placed");
  const listed = itemWhere({ location: null, last_at: { id: "l", name: "Substation 2", display: "Site › Substation 2" } });
  assert.deepEqual(listed, { label: "last at Site › Substation 2", locationId: "l", note: "" });
  assert.deepEqual(itemWhere({ location: null, last_at: null }), { label: "", locationId: null, note: "" });
});

test("a location's counts read as a line", () => {
  assert.equal(countsText({ positions: 5, fitted_items: 2, items: 1, open_work_orders: 1 }),
    "5 positions · 2 fitted items · 1 item placed · 1 open work order");
  assert.equal(countsText({ positions: 1, fitted_items: 0, items: 0, open_work_orders: 0 }), "1 position");
  assert.equal(countsText(null), "");
});
