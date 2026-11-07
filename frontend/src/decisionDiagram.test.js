import { test } from "node:test";
import assert from "node:assert/strict";
import {
  checkDecision, combineChoices, defaultAction, doctrineRefusal, modeAnswers, worthLine,
} from "./decisionCheck.js";
import { checkValue, consequenceText, modeCounts, COLUMN } from "./rcmWorksheet.js";
import { itemWrites } from "./explorerRcm.js";

// The RCM decision diagram (SAE JA1011, RCM II), as the server's
// backend/maintenance/rcm_decisions.py: the same refusals and default actions.

test("a mode's two answers, however it was saved", () => {
  assert.deepEqual(modeAnswers({ consequence: "hidden" }), { hidden: true, consequence: null });
  assert.deepEqual(modeAnswers({ consequence: "safety" }), { hidden: false, consequence: "safety" });
  assert.deepEqual(modeAnswers({ consequence: "safety", hidden: true }), { hidden: true, consequence: "safety" });
  assert.deepEqual(modeAnswers({}), { hidden: null, consequence: null });
});

test("the diagram refuses run to failure on safety, failure finding on an evident failure, a combination on a cost", () => {
  assert.match(doctrineRefusal(false, "safety", ["rtf"]), /^A safety consequence can't be run to failure/);
  assert.match(doctrineRefusal(true, "environmental", ["accept"]), /risk of the multiple failure tolerable/);
  assert.match(doctrineRefusal(false, "operational", ["failure_finding"]), /^Failure finding is for hidden failures only/);
  assert.match(doctrineRefusal(true, "operational", ["on_condition", "fixed_interval"]), /only for safety or environmental/);
  assert.equal(doctrineRefusal(true, "operational", ["rtf"]), null);
  assert.equal(doctrineRefusal(true, "safety", ["failure_finding"]), null);
  assert.equal(doctrineRefusal(false, "safety", ["on_condition", "fixed_interval"]), null);
  assert.equal(doctrineRefusal(false, "operational", ["fixed_interval", "redesign"]), null); // a redesign beside one task
  assert.equal(doctrineRefusal(null, null, ["rtf"]), null); // not answered yet
});

test("each default action", () => {
  const d = (h, c) => { const a = defaultAction(h, c); return [a.outcome, a.then, a.redesign]; };
  assert.deepEqual(d(false, "safety"), ["redesign", null, "compulsory"]);
  assert.deepEqual(d(false, "environmental"), ["redesign", null, "compulsory"]);
  assert.deepEqual(d(false, "operational"), ["rtf", null, "desirable"]);
  assert.deepEqual(d(false, "non_operational"), ["rtf", null, "desirable"]);
  assert.deepEqual(d(true, "safety"), ["failure_finding", "redesign", "compulsory"]);
  assert.deepEqual(d(true, "non_operational"), ["failure_finding", "rtf", "desirable"]);
  assert.equal(defaultAction(null, null), null);
  assert.match(defaultAction(true, null).text, /multiple failure would do/);
});

test("the worth-doing line follows the category", () => {
  assert.match(worthLine("on_condition", false, "safety"), /^First choice: .* makes the risk tolerable \(cost isn't the test\)\.$/);
  assert.match(worthLine("failure_finding", true, "operational"), /costs less over time than the multiple failures it prevents/);
  assert.match(worthLine("fixed_interval", null, null), /^Next: .*reach\.$/);
});

test("Apply says why the diagram forbids a decision, and combinations are greyed out with why", () => {
  const blocked = checkDecision({ outcome: "accept", fields: ["notes"], hidden: false, consequence: "safety" });
  assert.match(blocked.blockers[0], /can't be run to failure or accepted/);
  const choices = combineChoices("on_condition", [], { hidden: false, consequence: "operational" });
  const fi = choices.find((c) => c.id === "fixed_interval");
  assert.equal(fi.allowed, false);
  assert.match(fi.why, /only for safety or environmental/);
  assert.equal(choices.find((c) => c.id === "redesign").allowed, true);
});

test("the worksheet writes both answers and counts hidden ones", () => {
  assert.equal(consequenceText({ hidden: true, consequence: "safety" }), "Hidden · Safety");
  assert.equal(consequenceText({ consequence: "operational" }), "Operational");
  assert.equal(consequenceText({ consequence: "hidden" }), "Hidden");
  assert.equal(consequenceText({ hidden: false }), "Evident");
  assert.equal(COLUMN.consequence.text({ type: "mode", ref: { hidden: true, consequence: "non_operational" } }), "Hidden · Non-operational");
  assert.deepEqual([modeCounts({ consequence: "hidden" }).hidden, modeCounts({ hidden: true, consequence: "safety" }).safety], [1, 1]);
  assert.deepEqual(checkValue("hidden", { type: "mode", ref: {} }, "hidden"), { value: true });
  assert.deepEqual(checkValue("hidden", { type: "mode", ref: {} }, ""), { value: null });
  assert.deepEqual(checkValue("consequence", { type: "mode", ref: {} }, "hidden"), { value: null }); // a category only
  const mode = { type: "mode", key: "m", ref: { id: "m" } };
  assert.deepEqual(itemWrites(mode, { hidden: "hidden", consequence: "safety" }),
    [{ api: "decide", body: { hidden: true, consequence: "safety" } }]);
});
