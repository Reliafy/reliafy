import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_TAB, EXPLORER_PARTS_CLASSES_TABS, EXPLORER_SIGNALS_TAB, TABS, branchOf, classesInBranch, isDesignRow, isProductRow, partsInBranch, rowKind, shownTab, tabParam, tabsFor,
  addressTab, hasTabBar, tabCarried, tabForArrangement,
} from "./explorerTabs.js";

const pos = { type: "pos" };
const item = { type: "item" };
const loc = { type: "loc" };

// Parts and stock, Classes and Signals are switched off for now (EXPLORER_PARTS_CLASSES_TABS,
// EXPLORER_SIGNALS_TAB): `shown(ids)` is the tab list a row has with the switches as they are.
const shown = (ids) => ids.filter((id) => (EXPLORER_PARTS_CLASSES_TABS || (id !== "parts" && id !== "classes"))
  && (EXPLORER_SIGNALS_TAB || id !== "signals"));

test("Signals is hidden for now, on every kind of row, behind one switch", () => {
  assert.equal(EXPLORER_SIGNALS_TAB, false);
  const asset = { type: "pos", ref: { name: "Pump" } };
  const product = { type: "pos", ref: { design: { rev: "A" } } };
  const fitted = { type: "item", ref: { fitted_to: { id: "p" } } };
  for (const r of [pos, item, loc, asset, product, fitted, { type: "pos", ref: { in_design: true } }, { type: "group" }]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "signals"));
    assert.equal(shownTab("signals", r), "summary");
  }
  // An address that names it shows Summary.
  assert.equal(tabParam("signals"), "summary");
  // Its entry stays, for when it comes back.
  assert.equal(TABS.find((t) => t.id === "signals").label, "Signals");
  assert.deepEqual(tabsFor(item).map((t) => t.id), ["summary", "reports", "measurements"]);
});

test("Parts and stock and Classes are hidden for now, on assets and designs alike, behind one switch", () => {
  assert.equal(EXPLORER_PARTS_CLASSES_TABS, false);
  const asset = { type: "pos", ref: { name: "Pump" } };
  const product = { type: "pos", ref: { design: { rev: "A" } } };
  const designLoc = { type: "loc", ref: { design_of: "d", in_design: true } };
  for (const r of [pos, loc, asset, product, designLoc, { type: "pos", ref: { in_design: true } }]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "parts" || t.id === "classes"));
    assert.equal(shownTab("parts", r), "summary");
    assert.equal(shownTab("classes", r), "summary");
  }
  // An address that names one shows Summary.
  assert.equal(tabParam("parts"), "summary");
  assert.equal(tabParam("classes"), "summary");
  // Their entries stay, for when they come back.
  assert.equal(TABS.find((t) => t.id === "parts").label, "Parts and stock");
  assert.equal(TABS.find((t) => t.id === "classes").label, "Classes");
  assert.deepEqual(tabsFor(pos).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "models", "missions", "condition", "measurements", "lsa", "signals"]));
  assert.deepEqual(tabsFor(product).map((t) => t.id), ["summary", "rcm", "fmea", "reports", "models", "missions", "lsa"]);
});

test("a position has Summary, RCM, FME(C)A, Failure reports, Parts and stock, Classes and Signals; an item Summary, Failure reports and Signals; a location all but Signals; headings only Summary", () => {
  assert.deepEqual(tabsFor(pos).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "models", "missions", "condition", "measurements", "lsa", "signals"]));
  assert.equal(TABS.find((t) => t.id === "fmea").label, "FME(C)A");
  assert.equal(shownTab("fmea", pos), "fmea");
  assert.equal(shownTab("fmea", item), "summary");
  assert.equal(tabParam("fmea"), "fmea");
  // The Packages tab is the LSA tab now (9 Nov 2026): an old ?tab=packages address opens it.
  assert.equal(tabParam("lsa"), "lsa");
  assert.equal(tabParam("packages"), "lsa");
  assert.equal(TABS.find((t) => t.id === "lsa").label, "LSA");
  assert.match(TABS.find((t) => t.id === "lsa").title, /^Logistic support analysis: what each task needs/);
  assert.deepEqual(tabsFor(item).map((t) => t.id), shown(["summary", "reports", "measurements", "signals"]));
  // A place opens its positions' RCM (the Assets page opens the Explorer on the place).
  assert.deepEqual(tabsFor(loc).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "measurements", "lsa"]));
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

test("Measurements: positions, locations and items (before Signals), never a design's rows or a heading", () => {
  const m = TABS.find((t) => t.id === "measurements");
  assert.equal(m.label, "Measurements");
  assert.deepEqual(m.kinds, ["pos", "loc", "item"]);
  // Then LSA (Packages, Derryn, 8 Nov 2026; renamed 9 Nov), then Signals.
  assert.equal(TABS.findIndex((t) => t.id === "measurements") + 1, TABS.findIndex((t) => t.id === "lsa"));
  assert.equal(TABS.findIndex((t) => t.id === "lsa") + 1, TABS.findIndex((t) => t.id === "signals"));
  assert.equal(tabParam("measurements"), "measurements");
  assert.equal(shownTab("measurements", loc), "measurements");
  assert.equal(shownTab("measurements", { type: "group" }), "summary");
  for (const r of [{ type: "pos", ref: { design: { rev: "A" } } }, { type: "pos", ref: { in_design: true } },
    { type: "loc", ref: { design_of: "p1" } }]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "measurements"));
    assert.equal(shownTab("measurements", r), "summary");
  }
});

test("the tab picked stays while walking the tree, Summary where a row hasn't it", () => {
  assert.equal(shownTab("rcm", pos), "rcm");
  assert.equal(shownTab("rcm", item), "summary");
  assert.equal(shownTab("signals", item), EXPLORER_SIGNALS_TAB ? "signals" : "summary");
  assert.equal(shownTab("signals", loc), "summary");
  assert.equal(shownTab("rcm", loc), "rcm");
  assert.equal(shownTab("reports", loc), "reports");
  assert.equal(shownTab("reports", { type: "group" }), "summary");
  assert.equal(shownTab("nope", pos), "summary");
});

test("the address names the tab", () => {
  assert.equal(tabParam("rcm"), "rcm");
  assert.equal(tabParam("reports"), "reports");
  assert.equal(tabParam("signals"), EXPLORER_SIGNALS_TAB ? "signals" : "summary");
  assert.equal(tabParam("work"), "summary");
  assert.equal(tabParam(null), "summary");
});

test("a product's design has no maintenance: no Measurements, Signals or stock; it keeps RCM, FME(C)A, Parts (the parts list), Classes and the LSA (its programme's logistics), and its built items' Failure reports", () => {
  const top = { type: "pos", ref: { design: { rev: "C" } } };
  const inside = { type: "pos", ref: { in_design: true } };
  const asset = { type: "pos", ref: { name: "Pump" } };
  for (const r of [top, inside]) {
    assert.ok(isDesignRow(r));
    assert.deepEqual(tabsFor(r).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "models", "missions", "lsa"]));
    if (EXPLORER_PARTS_CLASSES_TABS) assert.equal(tabsFor(r).find((t) => t.id === "parts").label, "Parts");
    // The LSA keeps its name; its title says it's the design's tasks (no packaging there).
    const lsa = tabsFor(r).find((t) => t.id === "lsa");
    assert.equal(lsa.label, "LSA");
    assert.match(lsa.title, /each task in the design needs/);
    assert.equal(shownTab("lsa", r), "lsa");
    assert.equal(shownTab("measurements", r), "summary");
    // Failure reports: the reports raised on the items built from the product, here and below.
    const reports = tabsFor(r).find((t) => t.id === "reports");
    assert.equal(reports.label, "Failure reports");
    assert.match(reports.title, /items built from this product/);
    assert.equal(shownTab("reports", r), "reports");
    assert.equal(shownTab("signals", r), "summary");
    assert.equal(shownTab("parts", r), EXPLORER_PARTS_CLASSES_TABS ? "parts" : "summary");
  }
  assert.ok(isProductRow(top));
  assert.ok(!isProductRow(inside));
  // The product's row is headed "Product"; its design's positions stay "Position".
  assert.equal(rowKind(top), "Product");
  assert.equal(rowKind(inside), "Position");
  assert.equal(rowKind(asset), "Position");
  assert.equal(rowKind({ type: "item", ref: {} }), "Item");
  assert.equal(rowKind({ type: "cls", ref: {} }), "Item class"); // the Explorer by Classes
  assert.equal(rowKind({ type: "group", ref: {} }), "");
  // An asset (an item's tree built from a design is an asset too) keeps everything.
  assert.ok(!isDesignRow(asset));
  assert.ok(!isDesignRow({ type: "pos", ref: { design_position_id: "d1" } }));
  assert.deepEqual(tabsFor(asset).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "models", "missions", "condition", "measurements", "lsa", "signals"]));
  if (EXPLORER_PARTS_CLASSES_TABS) assert.equal(tabsFor(asset).find((t) => t.id === "parts").label, "Parts and stock");
  assert.equal(tabsFor(asset).find((t) => t.id === "reports").title, "What has failed here and below, and what was done about it");
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

test("a product's design locations have the design's tabs: no Failure reports, Signals, or Parts and stock", () => {
  const designLoc = { type: "loc", ref: { name: "Forward left arm", design_of: "d", in_design: true } };
  assert.ok(isDesignRow(designLoc));
  assert.deepEqual(tabsFor(designLoc).map((t) => t.id), shown(["summary", "rcm", "fmea", "classes", "lsa"]));
  assert.equal(rowKind(designLoc), "Design location");
  assert.equal(shownTab("reports", designLoc), "summary");
  assert.equal(shownTab("parts", designLoc), "summary");
  // A location a built item carries is a real place on a real thing: the usual location tabs.
  const carried = { type: "loc", ref: { name: "Forward left arm", carried_by: "b" } };
  assert.ok(!isDesignRow(carried));
  assert.deepEqual(tabsFor(carried).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "measurements", "lsa"]));
  assert.equal(rowKind(carried), "Location");
  // A design's positions keep their Parts (the parts list), and have their built items' Failure reports.
  const designPos = { type: "pos", ref: { name: "Motor 1", in_design: true } };
  assert.deepEqual(tabsFor(designPos).map((t) => t.id), shown(["summary", "rcm", "fmea", "reports", "parts", "classes", "models", "missions", "lsa"]));
});

test("an item class has one tab, Condition monitoring, and opens on it", () => {
  const cls = { type: "cls", ref: { id: "c1", name: "Pumps" } };
  const tabs = tabsFor(cls);
  assert.deepEqual(tabs.map((t) => t.id), ["condition"]);
  assert.equal(tabs[0].label, "Condition monitoring");
  assert.equal(tabs[0].title, "Each position of this class with its risk now, highest first");
  // The address names it (?tab=condition).
  assert.equal(tabParam("condition"), "condition");
  // A class has no Summary: with no tab picked, or one a class doesn't have, it shows its own.
  assert.equal(shownTab(DEFAULT_TAB, cls), "condition");
  assert.equal(shownTab("condition", cls), "condition");
  for (const other of ["rcm", "reports", "lsa", "models", "nope"]) assert.equal(shownTab(other, cls), "condition");
  // Walking from a class to another row keeps the usual rule: the tab picked if the row has it
  // (a position on an asset does), else Summary.
  assert.equal(shownTab("condition", pos), "condition");
  for (const r of [item, loc, { type: "group" }, { type: "pos", ref: { in_design: true } }]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "condition"));
    assert.equal(shownTab("condition", r), "summary");
  }
  assert.equal(shownTab("rcm", pos), "rcm");
  assert.equal(shownTab("condition", null), "summary");
});

test("a position on an asset has Condition monitoring too: the same tab as a class's, with its own hover text", () => {
  const asset = { type: "pos", ref: { id: "p1", name: "Feed pump 1" } };
  const mine = tabsFor(asset).find((t) => t.id === "condition");
  const classes = tabsFor({ type: "cls", ref: { id: "c1" } }).find((t) => t.id === "condition");
  // One id and one label, so the tab stays picked from a class to a position and between positions.
  assert.equal(mine.label, "Condition monitoring");
  assert.equal(mine.label, classes.label);
  assert.match(mine.title, /^This position's risk now/);
  assert.notEqual(mine.title, classes.title);
  assert.equal(shownTab("condition", asset), "condition");
  assert.equal(shownTab("condition", { type: "pos", ref: { id: "p2" } }), "condition");
  // A position keeps its Summary: with no tab picked it opens on Summary, not on this one.
  assert.equal(shownTab(DEFAULT_TAB, asset), "summary");
  // Assets only: not a product's own row, a position of its design, or a design location.
  const product = { type: "pos", ref: { design: { rev: "A" } } };
  const inDesign = { type: "pos", ref: { in_design: true } };
  const designLoc = { type: "loc", ref: { design_of: "d", in_design: true } };
  for (const r of [product, inDesign, designLoc]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "condition"));
    assert.equal(shownTab("condition", r), "summary");
  }
  // Positions only: not a location, an item or a heading.
  for (const r of [loc, item, { type: "loc", ref: { carried_by: "b" } }, { type: "item", ref: { fitted_to: { id: "p" } } }, { type: "group" }]) {
    assert.ok(!tabsFor(r).some((t) => t.id === "condition"));
    assert.equal(shownTab("condition", r), "summary");
  }
  // The entry itself: assets only, a class and a position.
  const entry = TABS.find((t) => t.id === "condition");
  assert.deepEqual(entry.kinds, ["cls", "pos"]);
  assert.equal(entry.asset, true);
});

test("the tab bar: two tabs or more, or one that isn't Summary", () => {
  assert.ok(hasTabBar({ type: "cls", ref: {} })); // one tab, Condition monitoring
  assert.ok(hasTabBar(pos));
  assert.ok(hasTabBar(item));
  assert.ok(!hasTabBar({ type: "group" })); // Summary alone
  assert.ok(!hasTabBar(null));
});

test("Condition monitoring comes along when the tree's arrangement changes: positions have it everywhere", () => {
  for (const m of ["positions", "locations", "classes"]) {
    assert.equal(tabForArrangement("condition", m), "condition");
    assert.equal(tabForArrangement("reports", m), "reports");
    assert.equal(tabForArrangement("summary", m), "summary");
  }
  // No tab is a class's alone now, so none is left behind off Classes.
  assert.ok(!TABS.some((t) => t.kinds.every((k) => k === "cls")));
});

test("walking on from a class keeps its Condition monitoring on a position, when the address names no tab", () => {
  const cls = { type: "cls", ref: { id: "pump" } };
  const asset = { type: "pos", ref: { name: "Pump A" } };
  assert.equal(tabCarried(cls, asset), "condition");
  // The address names a tab: that one is the tab picked, so nothing is added.
  assert.equal(tabCarried(cls, asset, { named: true }), null);
  // Rows that haven't the tab (a design's position, an item, a place, a group), and another class.
  for (const to of [{ type: "pos", ref: { in_design: true } }, item, loc, { type: "group" }, cls, null]) {
    assert.equal(tabCarried(cls, to), null);
  }
  // Only a class shows a tab nobody picked: from any other row there's nothing to carry.
  for (const from of [asset, item, loc, { type: "group" }, null]) assert.equal(tabCarried(from, asset), null);
});

test("an address with a class picked by Classes opens on the class's tab, whatever tab it names", () => {
  const cls = { arrange: "classes", sel: "cls:pump" };
  assert.equal(addressTab("rcm", cls), "condition");
  assert.equal(addressTab("reports", cls), "condition");
  assert.equal(addressTab(null, cls), "condition");
  // A position picked, or another arrangement: the tab asked for, as ever.
  assert.equal(addressTab("rcm", { arrange: "classes", sel: "p1" }), "rcm");
  assert.equal(addressTab("rcm", { arrange: "positions", sel: "cls:pump" }), "rcm");
  assert.equal(addressTab("packages", {}), "lsa");
  assert.equal(addressTab("nonsense"), "summary");
});
