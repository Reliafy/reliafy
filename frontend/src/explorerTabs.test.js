import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_TAB, TABS, branchOf, classesInBranch, isDesignRow, isProductRow, partsInBranch, shownTab, tabParam, tabsFor,
} from "./explorerTabs.js";

const pos = { type: "pos" };
const item = { type: "item" };
const loc = { type: "loc" };

test("a position has Summary, RCM, FME(C)A, Failure reports, Parts and stock, Classes and Signals; an item Summary, Failure reports and Signals; a location all but Signals; headings only Summary", () => {
  assert.deepEqual(tabsFor(pos).map((t) => t.id), ["summary", "rcm", "fmea", "reports", "parts", "classes", "signals"]);
  assert.equal(TABS.find((t) => t.id === "fmea").label, "FME(C)A");
  assert.equal(shownTab("fmea", pos), "fmea");
  assert.equal(shownTab("fmea", item), "summary");
  assert.equal(tabParam("fmea"), "fmea");
  assert.deepEqual(tabsFor(item).map((t) => t.id), ["summary", "reports", "signals"]);
  // A place opens its positions' RCM (the Assets page opens the Explorer on the place).
  assert.deepEqual(tabsFor(loc).map((t) => t.id), ["summary", "rcm", "fmea", "reports", "parts", "classes"]);
  assert.equal(TABS.find((t) => t.id === "parts").label, "Parts and stock");
  assert.equal(TABS.find((t) => t.id === "classes").label, "Classes");
  assert.deepEqual(tabsFor({ type: "group" }).map((t) => t.id), ["summary"]);
  assert.deepEqual(tabsFor(null), []);
  assert.equal(DEFAULT_TAB, "summary");
  assert.ok(TABS.every((t) => t.label && t.title));
  // Order: Summary, RCM, Failure reports, then Signals.
  assert.equal(TABS.at(-1).id, "signals");
  assert.equal(TABS.at(-1).label, "Signals");
  assert.equal(TABS.find((t) => t.id === "reports").label, "Failure reports");
});

test("the tab picked stays while walking the tree, Summary where a row hasn't it", () => {
  assert.equal(shownTab("rcm", pos), "rcm");
  assert.equal(shownTab("rcm", item), "summary");
  assert.equal(shownTab("signals", item), "signals");
  assert.equal(shownTab("signals", loc), "summary");
  assert.equal(shownTab("rcm", loc), "rcm");
  assert.equal(shownTab("reports", loc), "reports");
  assert.equal(shownTab("reports", { type: "group" }), "summary");
  assert.equal(shownTab("nope", pos), "summary");
});

test("the address names the tab", () => {
  assert.equal(tabParam("rcm"), "rcm");
  assert.equal(tabParam("reports"), "reports");
  assert.equal(tabParam("signals"), "signals");
  assert.equal(tabParam("work"), "summary");
  assert.equal(tabParam(null), "summary");
});

test("a product's design has no maintenance: no Failure reports, Signals or stock; it keeps RCM, FME(C)A, Parts (the parts list) and Classes", () => {
  const top = { type: "pos", ref: { design: { rev: "C" } } };
  const inside = { type: "pos", ref: { in_design: true } };
  const asset = { type: "pos", ref: { name: "Pump" } };
  for (const r of [top, inside]) {
    assert.ok(isDesignRow(r));
    assert.deepEqual(tabsFor(r).map((t) => t.id), ["summary", "rcm", "fmea", "parts", "classes"]);
    assert.equal(tabsFor(r).find((t) => t.id === "parts").label, "Parts");
    assert.equal(shownTab("reports", r), "summary");
    assert.equal(shownTab("signals", r), "summary");
    assert.equal(shownTab("parts", r), "parts");
  }
  assert.ok(isProductRow(top));
  assert.ok(!isProductRow(inside));
  // An asset (an item's tree built from a design is an asset too) keeps everything.
  assert.ok(!isDesignRow(asset));
  assert.ok(!isDesignRow({ type: "pos", ref: { design_position_id: "d1" } }));
  assert.deepEqual(tabsFor(asset).map((t) => t.id), ["summary", "rcm", "fmea", "reports", "parts", "classes", "signals"]);
  assert.equal(tabsFor(asset).find((t) => t.id === "parts").label, "Parts and stock");
  // The tab list itself is unchanged by a design row.
  assert.equal(TABS.find((t) => t.id === "parts").label, "Parts and stock");
});

test("a branch's parts and classes: what's kept or used there and inside it", () => {
  const rows = new Map([
    ["site", { key: "site", type: "loc", ref: {}, kids: ["store", "p1"] }],
    ["store", { key: "store", type: "loc", ref: {}, kids: [] }],
    ["p1", { key: "p1", type: "pos", ref: { position_class: "Pump" }, kids: ["p2"] }],
    ["p2", { key: "p2", type: "pos", ref: { position_class: "Motor" }, kids: [] }],
    ["other", { key: "other", type: "pos", ref: { position_class: "Fan" }, kids: [] }],
  ]);
  const display = { rows };
  const site = branchOf(display, "site");
  assert.deepEqual([...site.loc].sort(), ["site", "store"]);
  assert.deepEqual([...site.pos].sort(), ["p1", "p2"]);
  assert.deepEqual([...branchOf(display, "nope").pos], []);
  const parts = [
    { id: "a", stock: [{ location: { id: "store" } }], used_at: [] },
    { id: "b", stock: [], used_at: [{ position: { id: "p2" } }] },
    { id: "c", stock: [{ location: { id: "elsewhere" } }], used_at: [{ position: { id: "other" } }] },
  ];
  assert.deepEqual(partsInBranch(parts, site).map((p) => p.id), ["a", "b"]);
  assert.deepEqual(partsInBranch(parts, branchOf(display, "p1")).map((p) => p.id), ["b"]);
  // A design's parts list: by parts lists only, never by stock.
  assert.deepEqual(partsInBranch(parts, site, { design: true }).map((p) => p.id), ["b"]);
  assert.deepEqual(classesInBranch(display, site), [{ position_class: "Motor", here: 1 }, { position_class: "Pump", here: 1 }]);
});
