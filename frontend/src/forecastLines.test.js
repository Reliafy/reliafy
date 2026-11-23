import { test } from "node:test";
import assert from "node:assert/strict";
import { cells, headline, metaLine, tableRows } from "./forecastLines.js";

// The mower deck of the forecast plan (3.4), as the server answers it before a follow-on is recorded.
const OUT = {
  of: { kind: "position", months: 12 }, hours_basis: "Hours from the operating plan (About 12 hours a week)",
  lines: {
    lines: [
      { id: "task:g", kind: "planned", owner: "Grease deck spindles", number: "certain", how_often: "Every 50 hours",
        times: { expected: 12, interval: null }, hours: { expected: 2.4 }, cost: { expected: 216 }, spares: [], gaps: [],
        does: { kind: "supports", text: "Keeps it on its life: its whole life · failure rate × 3 if not done (Assumed)",
          marker: { assumed: true, title: "x" } } },
      { id: "task:i", kind: "planned", owner: "Inspect bearings for play", number: "certain", times: { expected: 6 },
        hours: { expected: 1.8 }, cost: { expected: 135 }, spares: [], gaps: [] },
      { id: "mode:0", kind: "failures", owner: "Spindle bearing worn out", number: "worked out", on: "3 positions",
        life: "Spindle bearing life", ages: [900, 900, 900], unit: "hours", found_share: 0.918,
        times: { expected: 1.65, interval: [0, 3] }, lines: ["mode:0:corrective", "mode:0:follow_on"], gaps: [] },
      { id: "mode:0:corrective", kind: "corrective", owner: "Spindle bearing worn out", number: "worked out",
        times: { expected: 0.135, interval: [0, 1] }, hours: null, cost: { expected: 121.7 },
        spares: [{ name: "a like item", expected: 0.135 }], gaps: [{ view: "hours", text: "no corrective response recorded" }] },
      { id: "mode:0:follow_on", kind: "follow_on", owner: "Spindle bearing worn out", number: "worked out",
        times: { expected: 1.51, interval: [0, 3] }, hours: null, cost: null, spares: [],
        gaps: [{ view: "cost", text: "nothing recorded for when an inspection finds it" }] },
    ],
    totals: {
      hours: { expected: 4.2, interval: [4.2, 4.2], known: false, leaves_out: ["hours to put failures right"] },
      cost: { expected: 472.7, interval: [351, 1251], known: false, leaves_out: ["found at an inspection"],
        by_kind: { planned: 351, follow_on: 0, corrective: 121.7 } },
      spares: { items: [], like_items: { expected: 1.65, interval: [0, 3] }, known: true, leaves_out: [] },
    },
  },
};
const money = (v) => `$${Math.round(v).toLocaleString("en-GB")}`;

test("rows: tasks first, then each failure mode with its follow-on and corrective lines under it", () => {
  const rows = tableRows(OUT.lines);
  assert.deepEqual(rows.map((r) => [r.owner, r.depth]), [
    ["Grease deck spindles", 0], ["Inspect bearings for play", 0], ["Spindle bearing worn out", 0],
    ["Corrective: after a failure", 1], ["Follow-on: found at an inspection", 1]]);
  assert.match(rows[0].meta, /Keeps it on its life/);
  assert.doesNotMatch(rows[0].meta, /restores/);
  assert.equal(rows[2].meta, "3 positions · Spindle bearing life · finds 92% in time");
});

test("cells: certain counts have no range; a gap is said, never filled", () => {
  const [g, , mode, corr, follow] = tableRows(OUT.lines).map((r) => cells(r.line, money));
  assert.equal(g.times, "12");
  assert.equal(g.number, "Certain");
  assert.equal(mode.times, "1.65 (0 to 3)");
  assert.equal(corr.cost.text, "$122");
  assert.equal(corr.hours.text, null);
  assert.equal(corr.hours.gap, "no corrective response recorded");
  assert.equal(follow.cost.gap, "nothing recorded for when an inspection finds it");
});

test("the headline: known costs with the 90% two-sided range, and the split by kind", () => {
  const h = headline(OUT, "costs", money);
  assert.equal(h.lead, "$473 known costs expected in the next 12 months (90% two-sided: $351 to $1,251).");
  assert.deepEqual(h.tiles, [{ label: "Planned", value: "$351" }, { label: "Follow-on", value: "not known" },
    { label: "Corrective", value: "$122" }]);
  assert.equal(headline(OUT, "hours", money).lead, "4.2 h known hours expected in the next 12 months.");
  assert.match(headline(OUT, "spares", money).lead, /^1\.65 like items to replace failures \(0 to 3, 90% two-sided\)/);
  assert.equal(metaLine(OUT), "3 lives (each 900 h) · Hours from the operating plan (About 12 hours a week)");
});
