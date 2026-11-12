// Run with: node --test src/
// The chart theme: where the download buttons go when a legend reaches their corner.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  DOWNLOAD_OVER, DOWNLOAD_ROW, MIN_PLOT_AREA, PLOTLY_HEIGHT, downloadCorner, logTicks, minPlotSize, ownHeight, reachesCorner, shorterBy, themedLayout,
} from "./plotTheme.js";

const box = (left, top, width, height = 14) => ({ left, top, right: left + width, bottom: top + height });
// A chart 800 px wide at (100, 50); the buttons, with their clear space, 117 px.
const chart = { left: 100, top: 50, right: 900, bottom: 450 };
const corner = downloadCorner(chart, 117);

test("the buttons' corner is the chart's top right", () => {
  assert.deepEqual(corner, { left: 783, right: 900, top: 50, bottom: 50 + DOWNLOAD_OVER });
});

test("a short legend leaves the corner clear", () => {
  // One to three entries from the plot's left edge, ending well short of the buttons.
  assert.equal(reachesCorner(corner, [box(190, 55, 80)]), false);
  assert.equal(reachesCorner(corner, [box(190, 55, 80), box(310, 55, 80), box(430, 55, 120)]), false);
  // No legend at all.
  assert.equal(reachesCorner(corner, []), false);
});

test("a legend whose last entry runs under the buttons reaches the corner", () => {
  const row = [box(190, 55, 180), box(410, 55, 180), box(630, 55, 180)];
  assert.equal(reachesCorner(corner, row), true);
  // Six entries on two rows: the first row reaches it, whatever the second does.
  assert.equal(reachesCorner(corner, [...row, box(190, 74, 180), box(410, 74, 180), box(630, 74, 100)]), true);
});

test("a second legend row reaches the corner only while it is as high as the buttons", () => {
  // The buttons are 32 px tall: a row starting 24 px down is under their lower edge.
  assert.equal(reachesCorner(corner, [box(700, 74, 150)]), true);
  assert.equal(reachesCorner(corner, [box(700, 50 + DOWNLOAD_OVER, 150)]), false);
});

test("a legend inside the plot's top right corner counts too", () => {
  assert.equal(reachesCorner(corner, [box(800, 71, 84)]), true);
  // Lower down the plot, or at its left, it doesn't.
  assert.equal(reachesCorner(corner, [box(800, 300, 84)]), false);
  assert.equal(reachesCorner(corner, [box(190, 71, 84)]), false);
});

test("text that only touches the corner's edge, or isn't drawn, doesn't count", () => {
  assert.equal(reachesCorner(corner, [box(683, 55, 100)]), false);
  assert.equal(reachesCorner(corner, [{ left: 0, right: 0, top: 0, bottom: 0 }]), false);
  assert.equal(reachesCorner(corner, [box(800, 55, 0)]), false);
});

test("the answer doesn't change when the chart moves down by the buttons' row", () => {
  // Legend text and the chart move together, so the row coming can't undo itself.
  const row = [box(190, 55, 180), box(410, 55, 180), box(630, 55, 180)];
  const down = (b) => ({ ...b, top: b.top + DOWNLOAD_ROW, bottom: b.bottom + DOWNLOAD_ROW });
  assert.equal(reachesCorner(downloadCorner(down(chart), 117), row.map(down)), reachesCorner(corner, row));
});

test("a chart with a height of its own gives the buttons' row its height", () => {
  assert.equal(shorterBy({ height: 320 }).height, 320 - DOWNLOAD_ROW);
  assert.equal(shorterBy({ height: 320 }, 10).height, 310);
  // Plotly's own height when the chart sets none.
  assert.equal(shorterBy({}).height, PLOTLY_HEIGHT - DOWNLOAD_ROW);
  assert.equal(shorterBy(undefined).height, PLOTLY_HEIGHT - DOWNLOAD_ROW);
  assert.equal(shorterBy({ height: 10 }).height, 0);
  // The rest of the layout is kept, and the caller's object left alone.
  const layout = { height: 300, showlegend: true, xaxis: { title: { text: "Hours" } } };
  const out = shorterBy(layout);
  assert.deepEqual(out, { ...layout, height: 300 - DOWNLOAD_ROW });
  assert.equal(layout.height, 300);
  assert.equal(themedLayout(out).height, 300 - DOWNLOAD_ROW);
});

test("a chart's box is as tall as its layout, with or without the row", () => {
  // Plot.jsx sets this on the chart's box, so a window resize (when Plotly
  // reads the box, not the layout) leaves the chart the height it was.
  assert.equal(ownHeight({ height: 440 }), 440);
  assert.equal(ownHeight({ height: 440 }, DOWNLOAD_ROW), shorterBy({ height: 440 }).height);
  assert.equal(ownHeight({}), PLOTLY_HEIGHT);
  assert.equal(ownHeight(undefined), PLOTLY_HEIGHT);
  assert.equal(ownHeight({ height: undefined }, DOWNLOAD_ROW), PLOTLY_HEIGHT - DOWNLOAD_ROW);
  assert.equal(ownHeight({ height: 10 }, DOWNLOAD_ROW), 0);
});

test("the row's height in the stylesheet matches the chart component's", () => {
  // Plot.jsx draws the chart DOWNLOAD_ROW shorter; index.css gives the row that height.
  const css = readFileSync(fileURLToPath(new URL("./index.css", import.meta.url)), "utf8");
  const rules = css.split("\n").filter((line) => line.includes(".plot-dl-own"));
  assert.ok(rules.length >= 3, "the .plot-dl-own rules are in index.css");
  for (const rule of rules.filter((line) => line.includes("{"))) {
    assert.match(rule, new RegExp(`:\\s*${DOWNLOAD_ROW}px;`), rule);
  }
  // The buttons over the chart are DOWNLOAD_OVER tall.
  assert.match(css, new RegExp(`\\.plot-dl-btn \\{\\s*height: ${DOWNLOAD_OVER}px;`));
});

// A pane squeezed to 20 px for a moment (desktop -> phone width with the RBD
// Calculator open) gave Plotly a 2 px plot area and axis titles at y = -Infinity.
// The chart's least size keeps its margins plus a real plot area.
test("minPlotSize: a squeezed box still leaves the chart a plot area", () => {
  const layout = themedLayout({ height: 440 }, { narrow: true });
  const least = minPlotSize(layout);
  const squeezed = 20;
  const drawn = Math.max(squeezed, least.width);
  const { l, r, t, b } = layout.margin;
  assert.equal(least.width, l + r + MIN_PLOT_AREA);
  assert.equal(least.height, t + b + MIN_PLOT_AREA);
  assert.ok(squeezed - l - r <= 0, "the bad input: no room at all inside the margins");
  assert.ok(drawn - l - r >= MIN_PLOT_AREA);
  // Every number is finite, even for a layout with no or odd margins.
  for (const lay of [undefined, {}, { margin: { l: -5, r: NaN, t: Infinity } }, { margin: { l: 8 } }]) {
    const m = minPlotSize(lay);
    assert.ok(Number.isFinite(m.width) && Number.isFinite(m.height) && m.width >= MIN_PLOT_AREA && m.height >= MIN_PLOT_AREA);
  }
});

test("a log axis labels values under 1 in full: 0.4, not 4", () => {
  // Hazard ratios from 0.44 to 3.0 (North 0.59, dusty 2.28).
  const t = logTicks(0.37, 3.6);
  assert.ok(t.tickvals.length >= 3 && t.tickvals.length <= 9);
  assert.ok(t.ticktext.includes("1"));
  t.tickvals.filter((v) => v < 1).forEach((v, i) => assert.ok(t.ticktext[t.tickvals.indexOf(v)].startsWith("0."), `${v}`));
  assert.ok(!t.ticktext.some((s) => /^[2-9]$/.test(s) && Number(s) < 1));
  // Every label is its own value.
  t.tickvals.forEach((v, i) => assert.equal(Number(t.ticktext[i]), v));
  // Above 1 too: a time ratio of 1.32 sits between labelled ticks.
  assert.deepEqual(logTicks(0.45, 1.7).ticktext, ["0.5", "0.6", "0.7", "0.8", "0.9", "1", "1.2", "1.5"]);
  // A short span: 0.6 to 0.95 gets each tenth.
  assert.deepEqual(logTicks(0.55, 0.97).ticktext, ["0.6", "0.7", "0.8", "0.9"]);
  // A wide span thins to powers of ten (and their 2s and 5s while they fit).
  const wide = logTicks(0.01, 1000);
  assert.ok(wide.tickvals.length <= 9);
  assert.ok(wide.ticktext.includes("0.01") && wide.ticktext.includes("1,000"));
  // A very short span gets evenly spaced ticks.
  const narrow = logTicks(0.97, 1.04);
  assert.ok(narrow.tickvals.length >= 3);
  narrow.tickvals.forEach((v, i) => assert.equal(Number(narrow.ticktext[i]), v));
  assert.equal(logTicks(0, 2), null);
});
