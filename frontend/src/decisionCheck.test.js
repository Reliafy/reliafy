import { test } from "node:test";
import assert from "node:assert/strict";
import { analysisKindOf, checkDecision, combinationOk, combineChoices, extraBody, pruneExtras } from "./decisionCheck.js";

// The fields each outcome asks for (as GET /api/maintenance/rcm/options says).
const F = { on_condition: ["task", "interval"], fixed_interval: ["task", "interval"], failure_finding: ["task", "interval"], rtf: ["rtf_basis", "task"], redesign: ["notes"], accept: ["notes"] };
const check = (d, opts) => checkDecision({ fields: F[d.outcome] || [], ...d }, opts);

test("no decision picked: Apply says to choose one", () => {
  assert.deepEqual(check({}).blockers, ["Choose a maintenance decision."]);
});

test("fixed interval and failure finding need an interval, marked and said in plain words", () => {
  for (const outcome of ["fixed_interval", "failure_finding"]) {
    const c = check({ outcome, task: "Replace the bearings" });
    assert.deepEqual(c.blockers, ["Give the task's interval."]);
    assert.match(c.intervalError, /^Give the interval: how often/);
    assert.equal(c.notice, null);
    assert.deepEqual(check({ outcome, interval: "3", intervalUnit: "months" }).blockers, []); // a task's words aren't needed
  }
});

test("an interval given is a number above 0 (as the server checks it)", () => {
  assert.equal(check({ outcome: "fixed_interval", interval: "0" }).intervalError, "The interval must be more than 0.");
  assert.equal(check({ outcome: "on_condition", interval: "-2" }).intervalError, "The interval must be more than 0.");
  assert.equal(check({ outcome: "fixed_interval", interval: "abc" }).intervalError, "The interval must be a number.");
  assert.deepEqual(check({ outcome: "fixed_interval", interval: "0" }).blockers, ["Fix the interval."]);
  assert.deepEqual(check({ outcome: "fixed_interval", interval: "0.5", intervalUnit: "years" }).blockers, []);
});

test("on condition with no interval: Apply stays on, with a quiet notice that no task is made", () => {
  const c = check({ outcome: "on_condition" });
  assert.deepEqual(c.blockers, []);
  assert.equal(c.intervalError, null);
  assert.equal(c.notice, "No task will be created: this decision will show as having no task. Say in the notes what covers it.");
  // Covered by another task, said in the notes: still allowed, still noted.
  assert.deepEqual(check({ outcome: "on_condition", notes: "Covered by the weekly walk-round" }).blockers, []);
  assert.match(check({ outcome: "on_condition", task: "Listen for noise" }).notice, /^No task will be created without an interval/);
  assert.equal(check({ outcome: "on_condition", interval: "1", intervalUnit: "weeks" }).notice, null);
});

test("run to failure needs its reason; nothing else", () => {
  assert.deepEqual(check({ outcome: "rtf" }).blockers, ["Choose why it can run to failure."]);
  assert.deepEqual(check({ outcome: "rtf", rtfBasis: "random" }).blockers, []);
  assert.deepEqual(check({ outcome: "rtf", rtfBasis: "uneconomic", interval: "" }).blockers, []);
  assert.deepEqual(check({ outcome: "redesign" }).blockers, []);
  assert.deepEqual(check({ outcome: "accept" }).blockers, []);
});

test("the Explorer's own limits: at most 100 years, 10 million units of use, notes of 4,000 characters", () => {
  const limits = { limits: true };
  assert.equal(check({ outcome: "fixed_interval", interval: "101", intervalUnit: "years" }, limits).intervalError, "The interval is at most 100 years.");
  assert.equal(check({ outcome: "fixed_interval", interval: "1300", intervalUnit: "months" }, limits).intervalError, "The interval is at most 100 years.");
  assert.equal(check({ outcome: "fixed_interval", interval: "100", intervalUnit: "years" }, limits).intervalError, null);
  assert.match(check({ outcome: "fixed_interval", interval: "20000000", intervalUnit: "hours" }, limits).intervalError, /^The interval is at most 10,000,000 hours/);
  assert.equal(check({ outcome: "fixed_interval", interval: "20000000", intervalUnit: "hours" }).intervalError, null); // no limit without `limits`
  assert.deepEqual(check({ outcome: "accept", notes: "x".repeat(4001) }, limits).blockers, ["Shorten the notes to 4,000 characters or fewer."]);
  assert.deepEqual(check({ outcome: "accept", notes: "x".repeat(4000) }, limits).blockers, []);
});

test("the interval's unit starts at the decision's own, else the one chosen last, else hours", async () => {
  const { rememberUnit, rememberedUnit, startUnit } = await import("./decisionCheck.js");
  const box = () => {
    const m = new Map();
    return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
  };
  const s = box();
  assert.equal(startUnit({}, s), "hours"); // nothing remembered: as before
  assert.equal(startUnit(null, s), "hours");
  rememberUnit("months", s);
  assert.equal(rememberedUnit(s), "months");
  assert.equal(startUnit({}, s), "months");
  assert.equal(startUnit({ interval: 2, interval_unit: "weeks" }, s), "weeks"); // its own unit wins
  rememberUnit("fortnights", s); // not a unit the dialog offers: ignored
  assert.equal(rememberedUnit(s), "months");
  s.setItem("reliafy.rcmIntervalUnit", "parsecs"); // something odd stored
  assert.equal(startUnit({}, s), "hours");
  // Storage that throws (private mode, blocked site data): hours, and no error.
  const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(startUnit({}, broken), "hours");
  assert.doesNotThrow(() => rememberUnit("days", broken));
  assert.equal(startUnit({}, undefined), "hours");
});

// ---- a combination of tasks ------------------------------------------------------

test("which outcomes combine: two or more scheduled, or redesign beside one; rtf and accept stand alone", () => {
  assert.equal(combinationOk(["on_condition", "fixed_interval"]), true);
  assert.equal(combinationOk(["on_condition", "fixed_interval", "failure_finding"]), true);
  assert.equal(combinationOk(["redesign", "on_condition"]), true);
  assert.equal(combinationOk(["redesign", "on_condition", "fixed_interval"]), false);
  assert.equal(combinationOk(["on_condition", "on_condition"]), false);
  assert.equal(combinationOk(["rtf", "on_condition"]), false);
  assert.equal(combinationOk(["accept", "fixed_interval"]), false);
  assert.equal(combinationOk(["rtf"]), true);
  assert.deepEqual(combineChoices("rtf"), []);
  assert.deepEqual(combineChoices("on_condition"), [
    { id: "fixed_interval", allowed: true }, { id: "failure_finding", allowed: true }, { id: "redesign", allowed: true }]);
  // Once a second scheduled task is in, a redesign can't join; once a redesign is in, nothing else can.
  assert.deepEqual(combineChoices("on_condition", ["fixed_interval"]).find((c) => c.id === "redesign").allowed, false);
  assert.deepEqual(combineChoices("on_condition", ["redesign"]).filter((c) => c.allowed).map((c) => c.id), ["redesign"]);
  assert.deepEqual(combineChoices("redesign").map((c) => c.id), ["on_condition", "fixed_interval", "failure_finding"]);
});

test("a changed first outcome keeps only the further tasks that still combine with it", () => {
  const extras = [{ outcome: "fixed_interval" }, { outcome: "redesign" }];
  assert.deepEqual(pruneExtras("on_condition", extras), [{ outcome: "fixed_interval" }]);
  assert.deepEqual(pruneExtras("fixed_interval", extras), [{ outcome: "redesign" }]);
  assert.deepEqual(pruneExtras("rtf", extras), []);
});

test("in a combination every scheduled task needs its interval, the first one too", () => {
  const extra = { outcome: "fixed_interval", interval: "24", intervalUnit: "months" };
  // On its own an on-condition decision may go without an interval; in a combination it may not.
  assert.deepEqual(check({ outcome: "on_condition" }).blockers, []);
  assert.deepEqual(check({ outcome: "on_condition", extras: [extra] }).blockers, ["Give the task's interval."]);
  const ok = check({ outcome: "on_condition", interval: "1", intervalUnit: "months", extras: [extra] });
  assert.deepEqual(ok.blockers, []);
  assert.deepEqual(ok.extraErrors, [null]);
  assert.equal(ok.notice, null);
  const missing = check({ outcome: "on_condition", interval: "1", extras: [{ outcome: "fixed_interval", interval: "" }] });
  assert.deepEqual(missing.extraErrors, ["Give this task's interval."]);
  assert.deepEqual(missing.blockers, ["Give each task of the combination a valid interval."]);
  // A redesign beside it needs no interval.
  assert.deepEqual(check({ outcome: "on_condition", interval: "1", extras: [{ outcome: "redesign" }] }).blockers, []);
  assert.deepEqual(check({ outcome: "rtf", rtfBasis: "random", extras: [extra] }).blockers,
    ["These outcomes can't be combined."]);
});

test("a further task goes back with its own evidence when it fits the task, or was linked before", () => {
  const row = { outcome: "fixed_interval", task: " Replace the bearing ", interval: "24", intervalUnit: "months" };
  assert.deepEqual(extraBody({ ...row, evidence: null }, "strategy_analysis"),
    { outcome: "fixed_interval", task: "Replace the bearing", interval: 24, interval_unit: "months" });
  const sa = { type: "strategy_analysis", id: "sa1", name: "ignored" };
  assert.deepEqual(extraBody({ ...row, evidence: sa }, "strategy_analysis").evidence, { type: "strategy_analysis", id: "sa1" });
  // A report or notes fit any task; another kind only when it was there before (the check then says why).
  assert.deepEqual(extraBody({ ...row, evidence: { type: "working", id: "f1" } }, "strategy_analysis").evidence, { type: "working", id: "f1" });
  const dm = { type: "degradation_model", id: "d1" };
  assert.equal(extraBody({ ...row, evidence: dm }, "strategy_analysis").evidence, undefined);
  assert.deepEqual(extraBody({ ...row, evidence: dm, had: dm }, "strategy_analysis").evidence, { type: "degradation_model", id: "d1" });
  assert.deepEqual(extraBody({ outcome: "redesign", evidence: dm }, null), { outcome: "redesign" });
  assert.equal(analysisKindOf("fixed_interval"), "optimal_replacement");
  assert.equal(analysisKindOf("failure_finding"), "failure_finding");
  assert.equal(analysisKindOf("on_condition"), null);
});
