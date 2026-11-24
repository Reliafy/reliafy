import { test } from "node:test";
import assert from "node:assert/strict";
import { choiceAsk, positiveAsk, urlAsk } from "./urlAsks.js";

test("urlAsk reads one value from a query, null when absent or blank", () => {
  assert.equal(urlAsk("calc", "?tab=calc&calc=1"), "1");
  assert.equal(urlAsk("compare", "?tab=calc"), null);
  assert.equal(urlAsk("next", "?next="), null);
  assert.equal(urlAsk("next", ""), null);
});

test("positiveAsk keeps the typed text of a positive number only", () => {
  assert.equal(positiveAsk("next", "?next=500"), "500");
  assert.equal(positiveAsk("next", "?next=0"), null);
  assert.equal(positiveAsk("next", "?next=-3"), null);
  assert.equal(positiveAsk("next", "?next=abc"), null);
  assert.equal(positiveAsk("repair", "?repair=1500&overhaul=6000"), "1500");
});

test("choiceAsk accepts only an allowed value", () => {
  const tabs = ["builder", "calc", "tree"];
  assert.equal(choiceAsk("tab", tabs, "builder", "?tab=tree"), "tree");
  assert.equal(choiceAsk("tab", tabs, "builder", "?tab=nope"), "builder");
  assert.equal(choiceAsk("tab", tabs, "builder", ""), "builder");
  assert.equal(choiceAsk("status", ["open", "all"], null, "?status=all"), "all");
});
