// Run with: node --test src/
// The two "how many to hold" answers each say when to use them and link to the other.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`./components/${f}`, import.meta.url), "utf8").replace(/\s+/g, " ");

test("Stock to hold says when to use it and links to the Forecasts spares card", () => {
  const src = read("RecurrentCalculator.jsx");
  assert.ok(src.includes("a stream of replacements counted as one process, such as a fleet's replacements against fleet hours"));
  assert.ok(src.includes('<Link to="/forecasts">Forecasts</Link>'));
});

test("the Forecasts spares card says when to use it and links to the repairable model's Stock to hold", () => {
  const src = read("FleetSparesCard.jsx");
  assert.ok(src.includes("a fleet of individual items with known ages and a life model, with a lead time"));
  assert.ok(src.includes('<Link to="/models/recurrent">repairable model</Link>'));
});
