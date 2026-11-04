import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_TAB, TABS, shownTab, tabParam, tabsFor } from "./explorerTabs.js";

const pos = { type: "pos" };
const item = { type: "item" };
const loc = { type: "loc" };

test("a position has Summary, RCM, FME(C)A, Failure reports and Signals; an item Summary, Failure reports and Signals; a location Summary and Failure reports; headings only Summary", () => {
  assert.deepEqual(tabsFor(pos).map((t) => t.id), ["summary", "rcm", "fmea", "reports", "signals"]);
  assert.equal(TABS.find((t) => t.id === "fmea").label, "FME(C)A");
  assert.equal(shownTab("fmea", pos), "fmea");
  assert.equal(shownTab("fmea", item), "summary");
  assert.equal(tabParam("fmea"), "fmea");
  assert.deepEqual(tabsFor(item).map((t) => t.id), ["summary", "reports", "signals"]);
  assert.deepEqual(tabsFor(loc).map((t) => t.id), ["summary", "reports"]);
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
  assert.equal(shownTab("rcm", loc), "summary");
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
