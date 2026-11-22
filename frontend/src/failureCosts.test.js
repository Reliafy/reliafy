import { test } from "node:test";
import assert from "node:assert/strict";
import { checkFigure, costFields, figureText, placeholderFor, plannedTitle, promptGroups, usedText } from "./failureCosts.js";

test("the three figures carry their units", () => {
  assert.deepEqual(costFields("$").map((f) => [f.key, f.suffix]), [["failure_cost", "$"], ["downtime_hours", "h"], ["downtime_rate", "$/h"]]);
});

test("a figure typed is a number 0 or more; empty clears it", () => {
  assert.deepEqual(checkFigure("failure_cost", "$1,200"), { value: 1200 });
  assert.deepEqual(checkFigure("failure_cost", ""), { value: null });
  assert.ok(checkFigure("downtime_hours", "-2").error.includes("hours"));
  assert.ok(checkFigure("failure_cost", "lots").error);
});

test("the class's figure shows while the mode has none", () => {
  const costs = { class: "Pumps", class_figures: { failure_cost: 4800, downtime_hours: 8, downtime_rate: null } };
  assert.equal(placeholderFor("failure_cost", costs), "From its class (Pumps): $4,800");
  assert.equal(placeholderFor("downtime_hours", costs), "From its class (Pumps): 8 h");
  assert.equal(placeholderFor("downtime_rate", costs), "Not set");
  assert.equal(figureText("downtime_rate", 50), "$50 an hour");
});

test("one failure all in, or what's missing", () => {
  assert.match(usedText({ per_failure: null }), /No failure cost yet/);
  assert.equal(usedText({ per_failure: 1100, text: "$900 (the failure mode's) + 2 h down at $100 an hour (the Pumps class's)" }),
    "One failure, all in: $1,100. $900 (the failure mode's) + 2 h down at $100 an hour (the Pumps class's).");
});

test("the forecast's prompts: costs first, then P-F intervals, then tasks with no effect, each with its link", () => {
  const groups = promptGroups({
    no_effect: [{ task: { id: "t1", name: "Grease deck spindles" }, position: { id: "p", name: "Mower" }, reason: "it restores none of the item's age", link: "/asset-register/explorer?tab=maintenance&mtask=t1" }],
    no_failure_cost: [
      { mode: { id: "m1", text: "Spark plug electrode worn" }, position: { id: "p", name: "Mower" }, counted: true, link: "/asset-register/explorer?tab=rcm&sel=m1" },
      { mode: null, life: "Spindle life", position: { id: "s", name: "Spindle 2" }, counted: true, reason: "a life for every failure here", link: "/x" },
    ],
    no_pf: [{ task: { id: "t2", name: "Inspect spark plug" }, mode: { id: "m1", text: "Spark plug electrode worn" }, position: { id: "p", name: "Mower" }, link: "/y" }],
  });
  assert.deepEqual(groups.map((g) => g.id), ["cost", "pf", "effect"]);
  assert.equal(groups[0].title, "Failure modes with no failure cost (2)");
  assert.equal(groups[0].items[0].link, "/asset-register/explorer?tab=rcm&sel=m1");
  assert.equal(groups[0].items[1].name, "Spindle life");
  assert.equal(groups[2].items[0].why, "It restores none of the item's age.");
  assert.deepEqual(promptGroups({}), []);
});

test("the planned cost's title says what it holds", () => {
  assert.equal(plannedTitle({ labour_cost: 27, materials_cost: 22, other_planned_cost: 0 }), "Planned: labour $27, parts and consumables $22");
  assert.equal(plannedTitle({}), "");
});
