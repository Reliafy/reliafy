import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CHIPS, COLUMN, COLUMNS, DEFAULT_COLUMNS, FIELDS, SCORE_ERROR, addSums, apSummary, blankSums, checkValue, fmeaCounts, loadPrefs, modeSums,
  nextSort, phoneLine, savePrefs, scoredWords, siblingOrder, tableCols, usualCols, withTableCols,
} from "./fmeaWorksheet.js";
import { buildDisplay, flatten } from "./assetTree.js";
import { graftFmea } from "./explorerFmea.js";

const mode = (id, extra = {}) => ({ type: "mode", key: id, ref: { id, text: id, ...extra }, sum: blankSums() });
const SCORED = { severity: 9, occurrence: 4, detection: 6, rpn: 216, ap: "H", action: "Seal it", action_status: "open",
  failure_rate: 8e-5, mode_ratio: 0.5, loss_probability: 1, operating_time: 100, cm: 0.004, severity_class: "I" };

test("the FMEA preset: the worksheet's columns in order, the criticality and RCM ones off; every column id is a field the API takes", () => {
  assert.deepEqual(DEFAULT_COLUMNS, ["failure", "cause", "effect_local", "effect_next", "effects", "detection_method", "severity", "occurrence", "detection",
    "rpn", "ap", "action", "action_owner", "action_due", "action_status"]);
  for (const c of COLUMNS) {
    if (c.edit && !c.rcm && c.id !== "name") assert.ok(FIELDS.has(c.field), `${c.id} writes a field the API takes`);
    assert.ok(c.label && c.width >= c.min, c.id);
  }
  assert.ok(COLUMN.consequence.rcm && COLUMN.decision.rcm && COLUMN.task.rcm);
  assert.equal(COLUMN.failure.edit, undefined); // read-only: from the RCM tab
  assert.ok(COLUMN.failure.title.includes("RCM tab"));
  // A narrow window drops the two middle effects and the owner.
  assert.ok(!usualCols({ narrow: true }).includes("effect_local") && usualCols({ narrow: true }).includes("action"));
  assert.deepEqual(usualCols(), DEFAULT_COLUMNS);
});

test("the cells, as text: scores, RPN, AP, the action's status, criticality to three figures; a parent row's roll-ups", () => {
  const m = mode("m", SCORED);
  const t = (id, r = m) => COLUMN[id].text(r);
  assert.equal(t("severity"), "9");
  assert.equal(t("rpn"), "216");
  assert.equal(t("ap"), "High");
  assert.equal(t("action_status"), "Open");
  assert.equal(t("cm"), "0.004");
  assert.equal(t("failure_rate"), "0.00008");
  assert.equal(t("severity_class"), "I Catastrophic");
  // A mode the server didn't score: RPN from its scores; AP only from the server.
  const half = mode("h", { severity: 9, occurrence: 4, detection: 6 });
  assert.equal(t("rpn", half), "216");
  assert.equal(t("ap", half), "");
  assert.equal(t("rpn", mode("u", { severity: 9 })), "");
  // A function row: the counts inside it.
  const fn = { type: "fn", key: "f", ref: { id: "f", text: "Fly" }, sum: addSums(addSums(addSums(blankSums(), modeSums(SCORED)), modeSums({ severity: 5, occurrence: 6, detection: 1, rpn: 30, ap: "M" })), modeSums({ text: "x" })) };
  assert.equal(t("cause", fn), "2 of 3 scored");
  assert.equal(t("rpn", fn), "216");
  assert.equal(t("ap", fn), "1 high · 1 medium");
  assert.equal(t("cm", fn), "0.004");
  assert.equal(t("action_status", fn), "1 open");
  assert.equal(t("severity", fn), "");
  assert.equal(scoredWords(fn.sum), "2 of 3 scored");
  assert.equal(apSummary({ low: 2 }), "2 low");
  assert.equal(apSummary({}), "");
});

test("a mode's counts, and how they add up (max_rpn the greatest, cr the sum)", () => {
  const c = fmeaCounts(SCORED);
  assert.deepEqual(c, { scored: 1, high: 1, medium: 0, low: 0, max_rpn: 216, cr: 0.004, with_cm: 1, action_open: 1 });
  assert.equal(fmeaCounts({ action: "Do it", action_status: "done" }).action_open, 0);
  assert.equal(fmeaCounts({ action: "  ", action_status: "open" }).action_open, 0);
  assert.equal(fmeaCounts({}).max_rpn, null);
  const s = addSums(addSums(blankSums(), fmeaCounts(SCORED)), fmeaCounts({ severity: 1, occurrence: 1, detection: 1, cm: 0.001 }));
  assert.equal(s.max_rpn, 216);
  assert.equal(s.scored, 2);
  assert.ok(Math.abs(s.cr - 0.005) < 1e-12);
  assert.ok("modes" in modeSums(SCORED) && "undecided" in modeSums(SCORED)); // the RCM's counts come along
});

test("cells checked as the server checks them: scores 1–10, shares 0–1, a rate ≥ 0, a time > 0, a date, a choice; blank clears", () => {
  const row = mode("m");
  assert.deepEqual(checkValue("severity", row, "9"), { value: 9 });
  assert.deepEqual(checkValue("severity", row, "0"), { error: SCORE_ERROR.severity });
  assert.deepEqual(checkValue("occurrence", row, "4.5"), { error: SCORE_ERROR.occurrence });
  assert.deepEqual(checkValue("detection", row, "11"), { error: SCORE_ERROR.detection });
  assert.deepEqual(checkValue("detection", row, ""), { value: null });
  assert.deepEqual(checkValue("mode_ratio", row, "0.5"), { value: 0.5 });
  assert.ok(checkValue("mode_ratio", row, "1.5").error.includes("between 0 and 1"));
  assert.ok(checkValue("loss_probability", row, "-1").error);
  assert.deepEqual(checkValue("failure_rate", row, "2e-5"), { value: 2e-5 });
  assert.ok(checkValue("failure_rate", row, "-2").error);
  assert.ok(checkValue("failure_rate", row, "abc").error.includes("must be a number"));
  assert.deepEqual(checkValue("operating_time", row, "100"), { value: 100 });
  assert.ok(checkValue("operating_time", row, "0").error.includes("more than 0"));
  assert.deepEqual(checkValue("action_due", row, "2026-12-01"), { value: "2026-12-01" });
  assert.deepEqual(checkValue("action_due", row, "1/12/2026"), { error: "The due date is a date (YYYY-MM-DD)." });
  assert.deepEqual(checkValue("action_due", row, "2026-02-30"), { error: "The due date is a date (YYYY-MM-DD)." });
  assert.deepEqual(checkValue("action_status", row, "done"), { value: "done" });
  assert.ok(checkValue("action_status", row, "closed").error);
  assert.deepEqual(checkValue("rate_source", row, ""), { value: null });
  assert.deepEqual(checkValue("severity_class", row, "II"), { value: "II" });
  assert.deepEqual(checkValue("cause", row, "  Dust  "), { value: "Dust" });
  assert.deepEqual(checkValue("cause", row, ""), { value: null });
  // The RCM's own columns and the name go through the RCM's checks.
  assert.deepEqual(checkValue("consequence", row, "safety"), { value: "safety" });
  assert.ok(checkValue("name", row, "").error.includes("needs a description"));
});

test("the chips: High priority, Medium priority, Not scored, Has an action open; on the FME(C)A tab only", () => {
  assert.deepEqual(CHIPS.map((c) => c.label), ["High priority", "Medium priority", "Not scored", "Has an action open"]);
  assert.ok(CHIPS.every((c) => c.rcmOnly && c.tab === "fmea"));
  const by = Object.fromEntries(CHIPS.map((c) => [c.id, c.test]));
  const hi = mode("h", SCORED);
  assert.ok(by["ap-high"](hi) && !by["ap-medium"](hi) && !by.unscored(hi) && by["action-open"](hi));
  const none = mode("n", {});
  assert.ok(by.unscored(none) && !by["action-open"](none));
  assert.ok(by["ap-medium"](mode("m", { ap: "M" })));
  assert.ok(!by.unscored({ type: "fn", ref: {}, sum: blankSums() }));
});

test("the phone's second line: the scores, RPN, AP and status; a parent's roll-up", () => {
  assert.equal(phoneLine(mode("m", SCORED)), "S 9 · O 4 · D 6 · RPN 216 · High · Open");
  assert.equal(phoneLine(mode("p", { severity: 9 })), "S 9 · not fully scored");
  assert.equal(phoneLine(mode("n", {})), "Not scored");
  const fn = { type: "fn", ref: {}, sum: addSums(addSums(blankSums(), modeSums(SCORED)), modeSums({})) };
  assert.equal(phoneLine(fn), "1 of 2 scored · 1 high");
});

test("remembered on this device under its own key, columns and widths; unknown columns dropped; broken storage is harmless", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(loadPrefs(storage).cols, DEFAULT_COLUMNS);
  savePrefs({ cols: ["severity", "nope", "cm"], widths: { cause: 300, bogus: 4, name: 200 }, colsChosen: true }, storage);
  assert.ok([...store.keys()][0] === "reliafy.fmeaWorksheet");
  const p = loadPrefs(storage);
  assert.deepEqual(p.cols, ["severity", "cm"]);
  assert.deepEqual(p.widths, { cause: 300, name: 200 });
  assert.equal(p.colsChosen, true);
  const broken = { getItem: () => { throw new Error("no"); }, setItem: () => { throw new Error("no"); } };
  assert.deepEqual(loadPrefs(broken).cols, DEFAULT_COLUMNS);
  assert.doesNotThrow(() => savePrefs(p, broken));
  // The table's columns: the usual ones until chosen; then in the preset's order.
  assert.deepEqual(tableCols({ cols: DEFAULT_COLUMNS }), DEFAULT_COLUMNS);
  const chosen = withTableCols({ cols: DEFAULT_COLUMNS }, ["cm", "severity", "cause"]);
  assert.deepEqual(chosen.cols, ["cause", "severity", "cm"]);
  assert.deepEqual(tableCols(chosen), ["cause", "severity", "cm"]);
  assert.deepEqual(tableCols(withTableCols(chosen, [], { reset: true }), { narrow: true }), usualCols({ narrow: true }));
});

const DATA = { positions: [{ id: "uav", name: "UAV", parent_id: null }, { id: "motor", name: "Motor", parent_id: "uav" }], locations: [], spares: [], unhomed: [] };
const RCM = { positions: [{ id: "motor", functions: [{ id: "f1", text: "Spin", modes: [
  { id: "a", text: "A", severity: 3, occurrence: 3, detection: 3, rpn: 27, ap: "L", cm: 0.5 },
  { id: "b", text: "B" },
  { id: "c", text: "C", severity: 9, occurrence: 4, detection: 6, rpn: 216, ap: "H", action_due: "2026-01-01" },
  { id: "d", text: "D", severity: 5, occurrence: 5, detection: 5, rpn: 125, ap: "M", cm: 0.1, action_due: "2025-06-01" },
] }] }] };

test("a column header sorts the failure modes under each function, blanks last, the tree kept; then the other way; then off", () => {
  const d = graftFmea(buildDisplay(DATA, "positions"), RCM);
  const open = new Set(["uav", "motor", "f1"]);
  const keys = (sort) => flatten(d, open, null, siblingOrder(d, sort)).list.map((v) => v.key);
  assert.deepEqual(keys(null), ["uav", "motor", "f1", "a", "b", "c", "d"]);
  assert.deepEqual(keys({ col: "rpn", dir: -1 }), ["uav", "motor", "f1", "c", "d", "a", "b"]);
  assert.deepEqual(keys({ col: "rpn", dir: 1 }), ["uav", "motor", "f1", "a", "d", "c", "b"]);
  assert.deepEqual(keys({ col: "ap", dir: -1 }), ["uav", "motor", "f1", "c", "d", "a", "b"]);
  assert.deepEqual(keys({ col: "cm", dir: -1 }), ["uav", "motor", "f1", "a", "d", "b", "c"]);
  assert.deepEqual(keys({ col: "action_due", dir: 1 }), ["uav", "motor", "f1", "d", "c", "a", "b"]);
  assert.deepEqual(keys({ col: "failure", dir: 1 }), ["uav", "motor", "f1", "a", "b", "c", "d"]); // all blank: the worksheet's order
  assert.equal(siblingOrder(d, { col: "nope", dir: 1 }), null);
  assert.deepEqual(nextSort(null, "rpn"), { col: "rpn", dir: -1 });
  assert.deepEqual(nextSort({ col: "rpn", dir: -1 }, "rpn"), { col: "rpn", dir: 1 });
  assert.equal(nextSort({ col: "rpn", dir: 1 }, "rpn"), null);
  assert.deepEqual(nextSort({ col: "rpn", dir: 1 }, "ap"), { col: "ap", dir: -1 });
});
