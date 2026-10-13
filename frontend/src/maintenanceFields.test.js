// Run with: node --test src/
// Reliafy Maintenance's structured fields: rough dates shown honestly, ranges of
// days, safe document links, costs.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  costText, costValue, datedText, daysText, moneyText, roughDateInput, roughDateValue, safeHref,
} from "./maintenanceFields.js";

test("a rough date is shown as it's known, never as a made-up day", () => {
  assert.equal(datedText("2022-01-01", "year"), "2022");
  assert.equal(datedText("2022-03-01", "month"), "Mar 2022");
  assert.equal(datedText("2022-03-20", "estimated"), "~Mar 2022");
  assert.equal(datedText("2022-03-05", "exact"), "5 Mar 2022");
  assert.equal(datedText("2022-03-05", undefined, (d) => `day ${d}`), "day 2022-03-05");
  assert.equal(datedText(null, "year"), "—");
});

test("a rough-date input sends a year, a month or a day", () => {
  assert.equal(roughDateValue("2022", "year"), "2022");
  assert.equal(roughDateValue("2022-03", "month"), "2022-03");
  assert.equal(roughDateValue("2022-03-15", "month"), "2022-03");
  assert.equal(roughDateValue("2022-03-15", "estimated"), "2022-03-15");
  assert.equal(roughDateValue("  ", "exact"), "");
  assert.equal(roughDateInput("2022-01-01", "year"), "2022");
  assert.equal(roughDateInput("2022-03-01", "month"), "2022-03");
  assert.equal(roughDateInput("2022-03-15", "exact"), "2022-03-15");
});

test("a life with rough dates is a range of days", () => {
  assert.equal(daysText({ x: 623, xl: 426, xr: 820 }), "426–820");
  assert.equal(daysText({ x: 438 }), "438");
  assert.equal(daysText({ x: 10, xl: 10, xr: 10 }), "10");
});

test("only web links become links", () => {
  assert.equal(safeHref("https://example.com/manual.pdf"), "https://example.com/manual.pdf");
  assert.equal(safeHref("HTTP://example.com/a"), "http://example.com/a");
  for (const bad of ["javascript:alert(1)", " javascript:alert(1)", "data:text/html,x", "//example.com", "ftp://x/y",
    "example.com", "", null, "https://"]) {
    assert.equal(safeHref(bad), null, String(bad));
  }
});

test("costs read with their currency, source and date", () => {
  const cost = { amount: 1150.5, currency: "AUD", source: "supplier quote", as_of: "2026-09-01" };
  assert.match(moneyText(cost), /^AUD 1,150\.5$/);
  assert.match(costText(cost), /^AUD 1,150\.5 \(supplier quote, as of 1 Sep 2026\)$/);
  assert.equal(costText(null), "—");
  assert.equal(costValue({ amount: "" }), null);
  assert.deepEqual(costValue({ amount: "800", currency: "AUD" }), { amount: 800, currency: "AUD", source: "", as_of: null });
});
