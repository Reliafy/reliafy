import { test } from "node:test";
import assert from "node:assert/strict";
import { NAV, SECTIONS, activeNav } from "./sections.js";

test("a section's landing page is never also one of its children", () => {
  for (const s of NAV) {
    for (const c of s.children || []) assert.notEqual(c.to, s.to, `${s.label} repeats its landing page`);
  }
});

test("Data comes first under Modelling, and Datasets is no longer a section", () => {
  const modelling = NAV.find((s) => s.key === "modelling");
  assert.equal(modelling.children[0].to, "/modelling/data");
  assert.equal(modelling.children[1].label, "Non-repairable models");
  assert.ok(!NAV.some((s) => s.to === "/datasets"));
  assert.ok(!modelling.children.some((c) => c.to === "/modelling/models"));
});

test("Maintenance's tabs are its children, and it stays gated", () => {
  const m = NAV.find((s) => s.key === "maintenance");
  assert.equal(m.gate, "maintenance");
  assert.deepEqual(m.children.map((c) => c.label), ["Items", "Locations", "Parts", "Classes"]);
});

test("the current entry: a child on its page and below it, else the section", () => {
  assert.deepEqual(activeNav("/modelling"), { section: "modelling", child: null });
  assert.deepEqual(activeNav("/modelling/data"), { section: "modelling", child: "/modelling/data" });
  assert.deepEqual(activeNav("/modelling/data/abc"), { section: "modelling", child: "/modelling/data" });
  assert.deepEqual(activeNav("/modelling/m/abc"), { section: "modelling", child: "/modelling/life" });
  assert.deepEqual(activeNav("/strategy/test-planning/life"), { section: "strategy", child: "/strategy/test-planning" });
  assert.deepEqual(activeNav("/strategy/analyses/x"), { section: "strategy", child: null });
  assert.deepEqual(activeNav("/fleet/forecasts/x"), { section: "fleet", child: null });
  assert.deepEqual(activeNav("/maintenance/items/i1"), { section: "maintenance", child: "/maintenance/items" });
  assert.deepEqual(activeNav("/home"), { section: "home", child: null });
  // A prefix of a word isn't a match.
  assert.deepEqual(activeNav("/rcmx"), { section: null, child: null });
  assert.equal(SECTIONS.modelling.to, "/modelling");
});
