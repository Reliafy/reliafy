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

test("the photo viewer steps with the arrow keys and wraps", async () => {
  const { photoStep, photoLabel } = await import("./maintenancePhotoPlaces.js");
  assert.equal(photoStep(0, 5, "ArrowRight"), 1);
  assert.equal(photoStep(4, 5, "ArrowRight"), 0);
  assert.equal(photoStep(0, 5, "ArrowLeft"), 4);
  assert.equal(photoStep(2, 5, "Home"), 0);
  assert.equal(photoStep(2, 5, "End"), 4);
  assert.equal(photoStep(2, 5, "Enter"), null);
  assert.equal(photoStep(0, 1, "ArrowRight"), null);
  assert.equal(photoLabel(1, 5, "Nameplate"), "Open photo 2 of 5: Nameplate");
  assert.equal(photoLabel(0, 1, ""), "Open photo 1 of 1");
});

test("assetLists and inAsset: a photo's choices inside one asset", async () => {
  const { assetLists, inAsset } = await import("./maintenancePhotoPlaces.js");
  const tree = {
    positions: [
      { id: "b", name: "Boiler", parent_id: null, item: { id: "i1", name: "Burner", serial: "B-1" } },
      { id: "a", name: "Air handler", parent_id: null },
      { id: "f", name: "Fan", parent_id: "a" },
      { id: "x", name: "Orphan", parent_id: "elsewhere" },
    ],
    locations: [{ id: "site", name: "Site", parent_id: null }, { id: "plant", name: "Plant room", parent_id: "site" }],
    spares: [{ id: "i2", name: "Spare fan", location_id: "plant" }],
  };
  const a = assetLists(tree);
  assert.deepEqual(a.positions, [
    { id: "a", name: "Air handler", depth: 0 }, { id: "f", name: "Fan", depth: 1 },
    { id: "b", name: "Boiler", depth: 0 }, { id: "x", name: "Orphan", depth: 0 },
  ]);
  assert.deepEqual(a.locations.map((l) => [l.id, l.parent?.name ?? null]), [["site", null], ["plant", "Site"]]);
  assert.deepEqual(a.items.map((i) => i.id), ["i1", "i2"]);
  assert.equal(inAsset({ subject: { id: "f" } }, a.ids), true);
  assert.equal(inAsset({ subject: { id: "i9" }, position: { id: "b" } }, a.ids), true);
  assert.equal(inAsset({ location: { id: "plant" } }, a.ids), true);
  assert.equal(inAsset({ subject: { id: "zzz" }, position: { id: "other" }, location: { id: "far" } }, a.ids), false);
  assert.equal(inAsset(null, a.ids), false);
});
