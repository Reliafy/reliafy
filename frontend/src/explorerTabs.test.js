import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_TAB, TABS, shownTab, tabParam, tabsFor } from "./explorerTabs.js";

const pos = { type: "pos" };
const item = { type: "item" };
const loc = { type: "loc" };

test("a position has Summary, RCM and Failure reports; items and locations Summary and Failure reports; headings only Summary", () => {
  assert.deepEqual(tabsFor(pos).map((t) => t.id), ["summary", "rcm", "reports"]);
  assert.deepEqual(tabsFor(item).map((t) => t.id), ["summary", "reports"]);
  assert.deepEqual(tabsFor(loc).map((t) => t.id), ["summary", "reports"]);
  assert.deepEqual(tabsFor({ type: "group" }).map((t) => t.id), ["summary"]);
  assert.deepEqual(tabsFor(null), []);
  assert.equal(DEFAULT_TAB, "summary");
  assert.ok(TABS.every((t) => t.label && t.title));
  // Appended last, after RCM (so a tab added between them lands cleanly).
  assert.equal(TABS.at(-1).id, "reports");
  assert.equal(TABS.at(-1).label, "Failure reports");
});

test("the tab picked stays while walking the tree, Summary where a row hasn't it", () => {
  assert.equal(shownTab("rcm", pos), "rcm");
  assert.equal(shownTab("rcm", item), "summary");
  assert.equal(shownTab("rcm", loc), "summary");
  assert.equal(shownTab("reports", loc), "reports");
  assert.equal(shownTab("reports", { type: "group" }), "summary");
  assert.equal(shownTab("nope", pos), "summary");
});

test("the address names the tab", () => {
  assert.equal(tabParam("rcm"), "rcm");
  assert.equal(tabParam("reports"), "reports");
  assert.equal(tabParam("work"), "summary");
  assert.equal(tabParam(null), "summary");
});
