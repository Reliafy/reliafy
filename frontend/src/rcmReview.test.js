// The RCM review's fixes on the Explorer (Nov 2026): a closed position row says what's inside
// it, a decision against the rules reads "Needs review" (and its parents "N to review"), the
// tree column fits its rows until it's dragged, a failure mode's reports link, and the
// calculators' units of use.
import { test } from "node:test";
import assert from "node:assert/strict";
import { PANE, TREE_FIT, buildDisplay, fitTreeWidth, loadTreeState, saveTreeState } from "./assetTree.js";
import { cellRow, failureSummary, graftRcm, modeReportsLink } from "./explorerRcm.js";
import { COLUMN, decidedWords, insideWords, modeCounts, phoneLine } from "./rcmWorksheet.js";
import { answerUnitWords, isUseUnit, pfUnits } from "./rcmIntervals.js";

const DATA = {
  positions: [
    { id: "uav", name: "UAV", parent_id: null },
    { id: "prop", name: "Propulsion", parent_id: "uav" },
    { id: "m1", name: "Motor 1", parent_id: "prop" },
    { id: "m2", name: "Motor 2", parent_id: "prop" },
    { id: "air", name: "Airframe", parent_id: "uav" },
    { id: "gear", name: "Landing gear", parent_id: "air" },
  ],
  locations: [], spares: [], unhomed: [],
};
const bearing = (id) => ({ id, text: "Bearing wears", consequence: "operational",
  decision: { outcome: "on_condition", status: "contradicted" } });
const rcmOn = (id, modes) => ({ id, functions: [{ id: `f-${id}`, text: "Turn", failures: [{ id: `x-${id}`, text: "Stops", modes }] }], unassigned: [] });
const RCM = {
  positions: [
    rcmOn("m1", [bearing("b1"), bearing("b2")]),
    rcmOn("m2", [bearing("b3"), bearing("b4")]),
    rcmOn("gear", [{ id: "g1", text: "Strut cracks", consequence: "safety", decision: null }]),
  ],
};

test("a closed position row counts every position inside it", () => {
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM);
  const prop = cellRow(d.rows.get("prop"));
  assert.equal(prop.sum.modes, 4);
  assert.equal(prop.sum.contradicted, 4);
  assert.equal(d.rows.get("prop").ownSum.modes, 0);
  assert.equal(COLUMN.check.text(prop), "4 contradicted");
  const air = cellRow(d.rows.get("air"));
  assert.equal(COLUMN.decision.text(air), "1 to decide");
  const uav = cellRow(d.rows.get("uav"));
  assert.equal(uav.sum.modes, 5);
  assert.ok(insideWords(uav).startsWith("5 failure modes · 1 to decide"));
  // A motor is its own: nothing inside it.
  assert.equal(cellRow(d.rows.get("m1")).sum.modes, 2);
});

test("a decision against the rules needs review: the mode says so and its parents count it", () => {
  const review = { id: "r1", text: "Freeboard low", consequence: "operational", needs_review: true,
    advice: "Accept stands alone, yet 1 task serves this failure mode.", decision: { outcome: "accept" } };
  assert.equal(modeCounts(review).review, 1);
  assert.equal(modeCounts({ ...review, needs_review: false }).review, 0);
  const d = graftRcm(buildDisplay(DATA, "positions"), { positions: [rcmOn("gear", [review])] });
  const gear = cellRow(d.rows.get("gear"));
  assert.equal(COLUMN.decision.text(gear), "1 to review");
  assert.equal(COLUMN.decision.text(cellRow(d.rows.get("uav"))), "1 to review");
  assert.equal(COLUMN.decision.text(cellRow(d.rows.get("r1"))), "Accept · Needs review");
  assert.match(phoneLine(cellRow(d.rows.get("gear"))), /1 to review/);
  // Words: undecided first, then to review, then all decided.
  assert.equal(decidedWords({ undecided: 2, review: 1 }), "2 to decide");
  assert.equal(decidedWords({ undecided: 0, review: 1 }), "1 to review");
  assert.equal(decidedWords({ undecided: 0, review: 0 }, { cap: true }), "All decided");
  assert.equal(failureSummary({ rsum: { modes: 3, undecided: 0, review: 2 }, ref: {} }), "3 failure modes · 2 to review");
});

test("the tree column fits the longest name on show, within its bounds", () => {
  const short = fitTreeWidth([{ depth: 0, text: "Pool" }], 1600);
  assert.equal(short, PANE.initial);
  const long = fitTreeWidth([{ depth: 5, text: "Mechanical seal leaks at the pump" }], 1600);
  assert.equal(long, 5 * 14 + 33 * TREE_FIT.charPx + TREE_FIT.extraPx);
  assert.ok(long > PANE.initial);
  // Capped: never more than a share of the window, nor TREE_FIT.cap.
  const huge = fitTreeWidth([{ depth: 9, text: "x".repeat(200) }], 1600);
  assert.equal(huge, Math.min(TREE_FIT.cap, Math.round(1600 * TREE_FIT.share)));
  assert.equal(fitTreeWidth([{ depth: 9, text: "x".repeat(200) }], 800), PANE.initial);
  assert.equal(fitTreeWidth([], 1600), PANE.initial);
});

test("a dragged width is remembered as chosen; an untouched one isn't", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  saveTreeState("w", { mode: "positions", open: {}, selected: {}, width: 480, widthSet: true }, storage);
  assert.deepEqual([loadTreeState("w", storage).width, loadTreeState("w", storage).widthSet], [480, true]);
  saveTreeState("w", { mode: "positions", open: {}, selected: {}, width: PANE.initial, widthSet: false }, storage);
  assert.equal(loadTreeState("w", storage).widthSet, false);
  // Saved before the flag: a width other than the usual one was dragged to.
  store.set("reliafy.assetTree.old", JSON.stringify({ width: 410 }));
  store.set("reliafy.assetTree.plain", JSON.stringify({ width: PANE.initial }));
  assert.equal(loadTreeState("old", storage).widthSet, true);
  assert.equal(loadTreeState("plain", storage).widthSet, false);
});

test("a failure mode's reports: one opens itself, several open the tab, none shows nothing", () => {
  assert.equal(modeReportsLink(null, "p"), null);
  assert.equal(modeReportsLink({ total: 0 }, "p"), null);
  const one = modeReportsLink({ total: 1, first: { id: "fr7", position: { id: "p2" } } }, "p");
  assert.equal(one.words, "1 failure report");
  assert.deepEqual(one.query, { sel: "p2", tab: "reports", report: "fr7" });
  const many = modeReportsLink({ total: 3, first: { id: "fr9" } }, "p");
  assert.equal(many.words, "3 failure reports");
  assert.deepEqual(many.query, { sel: "p", tab: "reports" });
});

test("the calculators take a unit of use and say which unit the answer is in", () => {
  assert.equal(isUseUnit("cycles"), true);
  assert.equal(isUseUnit("Hours"), false);
  assert.equal(isUseUnit(""), false);
  assert.deepEqual(pfUnits({ unit: "flight hours" }).slice(-1), ["flight hours"]);
  assert.equal(pfUnits({ unit: "months" }).length, 5);
  assert.match(answerUnitWords("pf", { pf_unit: "cycles" }), /in cycles, the P-F interval's unit/);
  assert.match(answerUnitWords("pf", { pf_unit: "weeks" }), /calendar time/);
  assert.match(answerUnitWords("ff", { device: "model", model: { unit: "flight hours" } }), /in flight hours, the model's unit/);
  assert.match(answerUnitWords("ff", { device: "rate" }), /calendar time/);
  assert.equal(answerUnitWords("fixed", {}), null);
});
