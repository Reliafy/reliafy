import { test } from "node:test";
import assert from "node:assert/strict";
import { costLabel, formatCost, formatCostRate } from "./money.js";

test("a cost carries the workspace's symbol", () => {
  assert.equal(formatCost(255.4, "$"), "$255");
  assert.equal(formatCost(1200, "€"), "€1,200");
  assert.equal(formatCost(3400, "AUD"), "AUD 3,400");
  assert.equal(formatCost(12.5, "A$"), "A$12.5");
  assert.equal(formatCost(-1200, "£"), "−£1,200");
});

test("the symbol defaults to $ and missing values show a dash", () => {
  assert.equal(formatCost(10), "$10");
  assert.equal(formatCost(10, ""), "$10");
  assert.equal(formatCost(null, "€"), "—");
  assert.equal(formatCost(NaN, "€"), "—");
});

test("significant figures follow formatNumber", () => {
  assert.equal(formatCost(1234.5, "$", { sig: 4 }), "$1,235");
  assert.equal(formatCost(0.4216, "$"), "$0.422");
});

test("a cost rate reads per unit of time", () => {
  assert.equal(formatCostRate(255, "$", "year"), "$255 a year");
  assert.equal(formatCostRate(0.42, "€", "Hours"), "€0.42 per hour");
  assert.equal(formatCostRate(3, "$", ""), "$3");
});

test("a field label names the symbol", () => {
  assert.equal(costLabel("Planned replacement cost", "€"), "Planned replacement cost (€)");
  assert.equal(costLabel("Cost each"), "Cost each ($)");
});

test("a server sentence's costs get the symbol", async () => {
  const { labelCostsInText } = await import("./money.js");
  assert.equal(labelCostsInText("Long-run cost about 255 a year, 12% less than running to failure.", "€"),
    "Long-run cost about €255 a year, 12% less than running to failure.");
  assert.equal(labelCostsInText("Long-run cost about 1,250 a year.", "AUD"), "Long-run cost about AUD 1,250 a year.");
  assert.equal(labelCostsInText("Replace at 12 days."), "Replace at 12 days.");
});

test("the workspace's symbol is the default for module-level formatters", async () => {
  const { formatCost, prefixCurrency, setWorkspaceCurrency, workspaceCurrency } = await import("./money.js");
  setWorkspaceCurrency("€");
  assert.equal(workspaceCurrency(), "€");
  assert.equal(formatCost(12), "€12");
  assert.equal(prefixCurrency("1,200"), "€1,200");
  assert.equal(prefixCurrency("-35"), "−€35");
  assert.equal(prefixCurrency("—"), "—");
  assert.equal(prefixCurrency("10", "AUD"), "AUD 10");
  setWorkspaceCurrency("");
  assert.equal(workspaceCurrency(), "$");
});
