// Run with: node --test src/
// Phone polish (#301): scroll cues, the number keyboard, chart file names.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { scrollEdges, scrollStep, scrollToReveal } from "./scrollCue.js";
import { chartFileName } from "./plotTheme.js";

test("a strip that fits shows no cue", () => {
  assert.deepEqual(scrollEdges({ scrollLeft: 0, scrollWidth: 300, clientWidth: 300 }), { start: false, end: false });
  // Sub-pixel overflow (zoom rounding) is not "more content".
  assert.deepEqual(scrollEdges({ scrollLeft: 0, scrollWidth: 300.6, clientWidth: 300 }), { start: false, end: false });
});

test("the cue sits on whichever side hides content", () => {
  const strip = { scrollWidth: 600, clientWidth: 300 };
  assert.deepEqual(scrollEdges({ ...strip, scrollLeft: 0 }), { start: false, end: true });
  assert.deepEqual(scrollEdges({ ...strip, scrollLeft: 150 }), { start: true, end: true });
  assert.deepEqual(scrollEdges({ ...strip, scrollLeft: 300 }), { start: true, end: false });
  assert.deepEqual(scrollEdges({ ...strip, scrollLeft: 299.5 }), { start: true, end: false });
});

test("the active tab is scrolled clear of the fade, only when hidden", () => {
  const strip = { scrollLeft: 0, clientWidth: 300, scrollWidth: 700 };
  // "Outage history" at 560-680: scroll so its right edge sits 40px in.
  assert.equal(scrollToReveal(strip, { left: 560, width: 120 }, 40), 400);
  // Already in view: leave the strip alone.
  assert.equal(scrollToReveal(strip, { left: 100, width: 80 }, 40), null);
  // Off the left edge: bring it back, never past the start.
  assert.equal(scrollToReveal({ ...strip, scrollLeft: 300 }, { left: 20, width: 80 }, 40), 0);
  // Never past the end.
  assert.equal(scrollToReveal(strip, { left: 640, width: 60 }, 40), 400);
});

test("an arrow scrolls most of a view, within bounds", () => {
  const strip = { clientWidth: 300, scrollWidth: 700 };
  assert.equal(scrollStep({ ...strip, scrollLeft: 0 }, 1), 210);
  assert.equal(scrollStep({ ...strip, scrollLeft: 300 }, 1), 400);
  assert.equal(scrollStep({ ...strip, scrollLeft: 100 }, -1), 0);
});

test("a chart downloads under its title, as PNG or SVG", () => {
  assert.equal(chartFileName("Bearings — probability plot", "png"), "bearings-probability-plot.png");
  assert.equal(chartFileName("Bearings — probability plot", "svg"), "bearings-probability-plot.svg");
  assert.equal(chartFileName("", "svg"), "chart.svg");
});

// Every number field that can't go below zero brings up the number keyboard
// on a phone: digits for whole numbers (step 1), digits and a point otherwise.
// Fields that can be negative keep the default keyboard, which has a minus.
test("non-negative number inputs declare a phone keyboard", () => {
  const src = fileURLToPath(new URL(".", import.meta.url));
  const files = [];
  const walk = (dir) => {
    for (const e of readdirSync(dir, { withFileTypes: true })) {
      const p = join(dir, e.name);
      if (e.isDirectory()) walk(p);
      else if (e.name.endsWith(".jsx")) files.push(p);
    }
  };
  walk(src);
  const missing = [];
  for (const f of files) {
    const text = readFileSync(f, "utf8");
    // An <input …> tag, allowing {…} expressions (one level of nesting) in it.
    for (const m of text.matchAll(/<input\b(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*>/g)) {
      const tag = m[0];
      if (!tag.includes('type="number"') || /\binputMode=/.test(tag)) continue;
      const min = tag.match(/\bmin=(?:"([^"]*)"|\{([^}]*)\})/);
      const value = min ? Number(min[1] ?? min[2]) : NaN;
      if (Number.isFinite(value) && value >= 0) missing.push(`${f.slice(src.length)}: ${tag.slice(0, 80)}`);
    }
  }
  assert.deepEqual(missing, []);
});
