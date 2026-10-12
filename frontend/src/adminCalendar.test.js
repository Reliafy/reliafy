import assert from "node:assert/strict";
import { test } from "node:test";
import {
  byDate,
  chipText,
  dayLabel,
  firstLines,
  kindOf,
  listDays,
  monthGrid,
  shiftMonth,
} from "./adminCalendar.js";

test("months shift across years", () => {
  assert.equal(shiftMonth("2026-12", 1), "2027-01");
  assert.equal(shiftMonth("2026-01", -1), "2025-12");
  assert.equal(shiftMonth("2026-10", 0), "2026-10");
});

test("the grid runs Monday to Sunday and covers the month", () => {
  const weeks = monthGrid("2026-10"); // 1 Oct 2026 is a Thursday
  assert.equal(weeks.length, 5);
  assert.deepEqual(weeks[0].slice(0, 4).map((d) => d.date), ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]);
  assert.equal(weeks[0][0].inMonth, false);
  assert.equal(weeks[0][3].inMonth, true);
  assert.equal(weeks[4][6].date, "2026-11-01");
  assert.ok(weeks.every((w) => w.length === 7 && w[0].weekday === 0));
  // A month starting on a Monday has no leading days; February 2027 is 4 weeks.
  assert.equal(monthGrid("2027-02")[0][0].date, "2027-02-01");
  assert.equal(monthGrid("2027-02").length, 4);
  assert.equal(monthGrid("2026-11").length, 6); // Sun 1 Nov ... Mon 30 Nov
});

test("kinds and labels", () => {
  assert.equal(kindOf({ kind: "blog", type: "tutorial" }).key, "blog-tutorial");
  assert.equal(kindOf({ kind: "blog", type: null }).label, "Blog");
  assert.equal(kindOf({ kind: "whatsnew" }).label, "What's new");
  assert.equal(kindOf({ kind: "announcement" }).long, "LinkedIn announcement");
  assert.equal(kindOf({ kind: "linkedin" }).long, "LinkedIn short post");
  assert.equal(chipText({ title: "Import your RBDs from BlockSim, Open-PSA" }), "Import your RBDs from Blo…");
  assert.equal(chipText({ kind: "linkedin", title: "" }), "LinkedIn");
});

test("days for the phone list, and text excerpts", () => {
  const view = {
    items: [
      { date: "2026-10-12", title: "a" },
      { date: "2026-10-12", title: "b" },
      { date: "2026-10-20", title: "c" },
    ],
    gaps: ["2026-10-13", "2026-10-20"],
  };
  assert.deepEqual(Object.keys(byDate(view.items)), ["2026-10-12", "2026-10-20"]);
  const days = listDays(view);
  assert.deepEqual(days.map((d) => [d.date, d.items.length, d.gap]), [
    ["2026-10-12", 2, false],
    ["2026-10-13", 0, true],
    ["2026-10-20", 1, true],
  ]);
  assert.match(dayLabel("2026-10-12"), /Mon.*12.*Oct/);
  assert.equal(firstLines("one\n\ntwo\nthree\nfour\nfive"), "one\ntwo\nthree\nfour");
});
