import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeChange, mergeCounts, mergeSentence, mergeSourceKind, mergeSpots, mergeTargets, separateChange } from "./assetMerge.js";

test("what can merge: a place or a top position, never a product's design", () => {
  assert.equal(mergeSourceKind({ kind: "place" }), "place");
  assert.equal(mergeSourceKind({ kind: "unit" }), "unit");
  assert.equal(mergeSourceKind({ kind: "design" }), null);
  assert.equal(mergeSourceKind(null), null);
});

test("the assets it can join: every other one, searched, A to Z", () => {
  const places = [{ id: "b", name: "Site B" }, { id: "a", name: "site a" }, { id: "me", name: "Pump station 2" }];
  assert.deepEqual(mergeTargets(places, "me").map((p) => p.id), ["a", "b"]);
  assert.deepEqual(mergeTargets(places, "me", "b").map((p) => p.id), ["b"]);
});

test("where it can go: a place inside a location; a position inside a position or at a location", () => {
  const tree = {
    locations: [{ id: "A", name: "Site A", parent_id: null }, { id: "hall", name: "Pump hall", parent_id: "A" }],
    positions: [{ id: "line", name: "Feed line", parent_id: null }, { id: "on", name: "Carried", parent_id: null, carried_by: { id: "i" } }],
  };
  assert.deepEqual(mergeSpots(tree, "place").rows.map((r) => [r.id, r.kind, r.depth]), [["A", "loc", 0], ["hall", "loc", 1]]);
  assert.deepEqual(mergeSpots(tree, "unit").rows.map((r) => [r.id, r.kind]), [["A", "loc"], ["hall", "loc"], ["line", "pos"]]);
  assert.deepEqual(mergeSpots(tree, "unit", "feed").rows.map((r) => r.id), ["line"]);
  assert.deepEqual(mergeSpots(null, "unit").rows, []);
});

test("the preview names what comes along and where it goes", () => {
  const data = {
    locations: [{ id: "me" }, { id: "l1" }, { id: "l2" }, { id: "l3" }],
    positions: [{ id: "p1", fitted: true }, { id: "p2" }],
    spares: [{ id: "s1" }],
  };
  const counts = mergeCounts(data, "place");
  assert.deepEqual(counts, { positions: 2, items: 2, locations: 3 });
  assert.equal(mergeSentence("Pump station 2", counts, { id: "A", name: "Site A" }, { id: "hall", kind: "loc", name: "Pump hall" }),
    "Pump station 2 and its 2 positions, 2 items and 3 locations will become part of Site A, at Pump hall.");
  assert.equal(mergeSentence("Skid", mergeCounts({ positions: [{ id: "skid" }] }, "unit"), { id: "A", name: "Site A" }, { id: "A", kind: "loc", name: "Site A" }),
    "Skid will become part of Site A.");
  assert.equal(mergeSentence("Skid", { positions: 1, items: 0, locations: 0 }, { id: "A", name: "Site A" }, { id: "line", kind: "pos", name: "Feed line" }),
    "Skid and its 1 position will become part of Site A, inside Feed line.");
});

test("the merge is a move; making a row its own asset clears the same", () => {
  assert.deepEqual(mergeChange("place", "me", { id: "hall", kind: "loc" }), { kind: "location", id: "me", body: { parent_id: "hall" } });
  assert.equal(mergeChange("place", "me", { id: "line", kind: "pos" }), null);
  assert.deepEqual(mergeChange("unit", "skid", { id: "line", kind: "pos" }), { kind: "position", id: "skid", body: { parent_id: "line" } });
  assert.deepEqual(mergeChange("unit", "skid", { id: "hall", kind: "loc" }), { kind: "position", id: "skid", body: { location_id: "hall" } });
  assert.equal(mergeChange("unit", "skid", null), null);

  assert.deepEqual(separateChange({ key: "me", type: "loc", ref: { parent_id: "hall" } }), { kind: "location", id: "me", body: { parent_id: null } });
  assert.deepEqual(separateChange({ key: "skid", type: "pos", ref: { parent_id: "line", location: { id: "hall", inherited: true } } }),
    { kind: "position", id: "skid", body: { parent_id: null } });
  assert.deepEqual(separateChange({ key: "skid", type: "pos", ref: { parent_id: null, location_id: "hall", location: { id: "hall" } } }),
    { kind: "position", id: "skid", body: { location_id: null } });
  assert.equal(separateChange({ key: "x", type: "item", ref: {} }), null);
});

test("making a row its own asset says what happens and how to undo it", async () => {
  const { separateConfirm } = await import("./assetMerge.js");
  const { normaliseConfirm } = await import("./confirm.js");
  const loc = normaliseConfirm(separateConfirm({ key: "hall", type: "loc", ref: { name: "Pump hall" } }, "Site A"));
  assert.equal(loc.title, "Make Pump hall its own asset?");
  assert.match(loc.body, /leave Site A/);
  assert.match(loc.body, /Merge into another asset…/);
  assert.equal(loc.destructive, false);
  const pos = separateConfirm({ key: "p", type: "pos", ref: { name: "Skid" } }, "Site A");
  assert.match(pos.body, /Cause-and-effect links/);
  assert.match(pos.body, /Not at a place yet/);
});
