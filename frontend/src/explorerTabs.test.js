import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_TAB, TABS, insideParam, shownTab, tabParam, tabsFor } from "./explorerTabs.js";

const pos = { type: "pos" };
const item = { type: "item" };
const loc = { type: "loc" };

test("a position has Summary and RCM; items and locations only Summary", () => {
  assert.deepEqual(tabsFor(pos).map((t) => t.id), ["summary", "rcm"]);
  assert.deepEqual(tabsFor(item).map((t) => t.id), ["summary"]);
  assert.deepEqual(tabsFor(loc).map((t) => t.id), ["summary"]);
  assert.deepEqual(tabsFor(null), []);
  assert.equal(DEFAULT_TAB, "summary");
  assert.ok(TABS.every((t) => t.label && t.title));
});

test("the tab picked stays while walking the tree, Summary where a row hasn't it", () => {
  assert.equal(shownTab("rcm", pos), "rcm");
  assert.equal(shownTab("rcm", item), "summary");
  assert.equal(shownTab("rcm", loc), "summary");
  assert.equal(shownTab("nope", pos), "summary");
});

test("the address names the tab and whether the positions inside are included", () => {
  assert.equal(tabParam("rcm"), "rcm");
  assert.equal(tabParam("work"), "summary");
  assert.equal(tabParam(null), "summary");
  assert.equal(insideParam("1"), true);
  assert.equal(insideParam(null), false);
  assert.equal(insideParam("yes"), false);
});
