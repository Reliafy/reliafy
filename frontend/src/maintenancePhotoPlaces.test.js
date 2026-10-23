import { test } from "node:test";
import assert from "node:assert/strict";
import {
  alsoOnText, normaliseKind, placeKindWord, placeOptions, placePath, suggestions,
} from "./maintenancePhotoPlaces.js";

test("kinds read in words and link to their pages", () => {
  assert.equal(placeKindWord("WorkOrder"), "work order");
  assert.equal(placeKindWord("position"), "position");
  assert.equal(normaliseKind("work_order"), "WorkOrder");
  assert.equal(normaliseKind("nonsense"), null);
  assert.equal(placePath({ id: "w1", kind: "WorkOrder" }), "/maintenance/work-orders/w1");
  assert.equal(placePath({ id: "l1", kind: "location" }), "/asset-register/locations/l1");
  assert.equal(placePath({ id: "x", kind: "Document" }), null);
});

test("also-on text names the first other place and counts the rest", () => {
  assert.equal(alsoOnText([]), "");
  assert.equal(alsoOnText([{ id: "p", kind: "Position", name: "Pool pump" }]), "also on Pool pump");
  assert.equal(alsoOnText([{ id: "p", kind: "Position", name: "Pool pump" }, { id: "l", kind: "Location", name: "Shed" }]),
    "also on Pool pump and 1 more");
});

test("suggestions skip this page, places it's on already, and repeats", () => {
  const related = [
    { id: "wo", kind: "WorkOrder", title: "Fix" },
    { id: "p", kind: "position", name: "Pump" },
    { id: "p", kind: "Position", name: "Pump" },
    { id: "l", kind: "Location", name: "Shed" },
    null,
    { id: "z", kind: "Document", name: "Manual" },
  ];
  assert.deepEqual(suggestions(related, "wo", [{ id: "l" }]), [{ id: "p", kind: "Position", name: "Pump" }]);
});

test("picker options for each kind", () => {
  const lists = {
    positions: [{ id: "a", name: "Plant", depth: 0 }, { id: "b", name: "Pump", depth: 1 }],
    locations: [{ id: "s", name: "Site" }, { id: "r", name: "Room", parent: { name: "Site" } }],
    items: [{ id: "i", name: "Motor", serial: "SN1" }, { id: "j", name: "Fan" }],
    workOrders: [{ id: "w", number: 7, title: "Replace seal" }],
  };
  assert.deepEqual(placeOptions("Position", lists).map((o) => o.id), ["a", "b"]);
  assert.ok(placeOptions("Position", lists)[1].label.endsWith("Pump"));
  assert.deepEqual(placeOptions("Location", lists).map((o) => o.label), ["Site", "Site › Room"]);
  assert.deepEqual(placeOptions("Item", lists).map((o) => o.label), ["Motor (SN1)", "Fan"]);
  assert.deepEqual(placeOptions("WorkOrder", lists), [{ id: "w", label: "#7 Replace seal" }]);
  assert.deepEqual(placeOptions("Other", lists), []);
});
