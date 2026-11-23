import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { costWords, labourWords, partWords, taskExtras } from "./taskExtras.js";
import { EXTRA_TYPE, TASK_TYPE, extraKey, graftTasks, isExtraRow, rollupText, taskKey } from "./explorerTasks.js";
import { moreScheduleSummary, taskUnitChoices, withUnit, formFromTask, changeType } from "./howOften.js";
import { RESPONSE_KIND, responseKindOf, responseLine, responseTrigger } from "./failureCosts.js";
import { fromText, kindText } from "./lsaTab.js";

// A task's Cost, Labour and Parts (Derryn, 23 Nov 2026): one line each, the same words in the
// task panel's fold-outs and in the tree's rows under the task.

test("labour, parts and a typed cost in a few words", () => {
  assert.equal(labourWords([{ trade: "mechanic", people: 1, hours: 1.5 }]), "1.5 h mechanic");
  assert.equal(labourWords([{ trade: "fitter", people: "2", hours: "3" }, { trade: "", people: 1, hours: "" }]), "2 × 3 h fitter");
  assert.equal(labourWords([]), "");
  assert.equal(partWords([{ name: "Spindle kit", qty: 1 }, { name: " ", qty: 4 }]), "Spindle kit × 1");
  assert.match(costWords("40"), /^\$40 each time$/);
  assert.match(costWords("40", "25"), /^\$40 each time · call-out \$25$/);
  assert.equal(costWords("", null), "");
});

test("a task's extras: only the ones set, a part each; a cost from its LSA isn't one", () => {
  const t = { resources: { labour: [{ trade: "mechanic", people: 1, hours: 1.5 }], spares: [{ name: "Spindle kit", qty: 1 }, { name: "Belt", qty: 2 }] },
    cost: { amount: 40, typed: 40 } };
  assert.deepEqual(taskExtras(t).map((x) => x.text), ["Labour · 1.5 h mechanic", "Part · Spindle kit × 1", "Part · Belt × 2", "Cost · $40 each time"]);
  assert.deepEqual(taskExtras({ resources: {}, cost: { amount: 120, typed: null } }), []);
});

test("the tree: a task's extras are rows under it, not tasks (no roll-up counts them)", () => {
  const display = { rows: new Map([["p", { key: "p", type: "pos", parent: null, kids: [], depth: 0, ref: { name: "Mower" } }]]), roots: ["p"] };
  const t = { id: "t1", name: "Check belt", subject: { id: "p" }, resources: { labour: [{ trade: "mechanic", people: 1, hours: 1.5 }] }, cost: { typed: 40 } };
  const out = graftTasks(display, [t, { id: "t2", name: "Sharpen", subject: { id: "p" } }]);
  const task = out.rows.get(taskKey("t1"));
  assert.equal(task.type, TASK_TYPE);
  assert.deepEqual(task.kids, [extraKey("t1", "labour", 0), extraKey("t1", "cost", 1)]);
  const lab = out.rows.get(extraKey("t1", "labour", 0));
  assert.equal(lab.type, EXTRA_TYPE);
  assert.ok(isExtraRow(lab));
  assert.equal(lab.ref.name, "Labour · 1.5 h mechanic");
  assert.equal(lab.ref.section, "labour");
  assert.equal(lab.ref.task_key, taskKey("t1"));
  assert.equal(out.rows.get(taskKey("t2")).kids.length, 0);
  assert.equal(rollupText(out.rows.get("p")), "2 tasks here");
});

test("How often: one Every [N] [unit]; the unit decides running hours or the calendar", () => {
  const f = formFromTask({ interval: 50, unit: "hours" });
  assert.equal(f.type, "hours");
  assert.equal(withUnit(f, "months").type, "interval");
  assert.equal(withUnit(withUnit(f, "months"), "km").type, "hours");
  // A rule keeps its own line: a unit picked doesn't turn it back.
  assert.equal(withUnit(changeType(withUnit(f, "months"), "rule", ["months"]), "weeks").type, "rule");
});

test("the units offered: hours and the calendar; cycles, starts or km only where a counter counts them", () => {
  assert.deepEqual(taskUnitChoices({}), ["hours", "days", "weeks", "months", "years"]);
  assert.deepEqual(taskUnitChoices({ counters: ["km", "h", "Starts"] }), ["hours", "starts", "km", "days", "weeks", "months", "years"]);
  assert.deepEqual(taskUnitChoices({ form: { unit: "cycles", alsoUnit: "months" } }), ["hours", "cycles", "days", "weeks", "months", "years"]);
  assert.deepEqual(taskUnitChoices({ place: true }), ["days", "weeks", "months", "years"]);
});

test("More scheduling options, folded, says what's set in it; nothing set, nothing said", () => {
  const f = formFromTask({ interval: 50, unit: "hours" });
  assert.equal(moreScheduleSummary(f), "");
  assert.equal(moreScheduleSummary({ ...f, also: "6", alsoUnit: "months" }), "Also every 6 months, whichever first");
  assert.equal(moreScheduleSummary({ ...f, also: "6", alsoUnit: "months" }, { replace: "keep" }),
    "Also every 6 months, whichever first · keeps its schedule when the item is replaced");
  assert.equal(moreScheduleSummary(formFromTask({ interval: 1, unit: "months", rule: { kind: "monthly", every: 1, weekday: "saturday", nth: 1 } })),
    "On set calendar dates");
  assert.equal(moreScheduleSummary(formFromTask({ interval: 12, unit: "months", rule: { kind: "shutdowns", every: 12, unit: "months" } })),
    "At planned shutdowns");
});

test("a failure mode's responses are tasks: their kind, where from, and the RCM's one line", () => {
  const corrective = { on_event: true, trigger: { kind: "failure", failure_mode_id: "m", failure_mode: { id: "m", text: "Belt breaks" } }, source: "manual" };
  assert.equal(kindText(corrective), "Corrective: on failure");
  assert.equal(kindText({ ...corrective, trigger: { ...corrective.trigger, kind: "found" } }), "Follow-on: when found");
  assert.equal(fromText(corrective), "Failure mode: Belt breaks");
  assert.equal(responseKindOf(corrective), "failure");
  assert.equal(responseKindOf({ trigger: { kind: "reading" } }), null);
  assert.equal(RESPONSE_KIND.found, "Follow-on: when found");
  assert.equal(responseTrigger("failure", "Belt breaks"), "Raised when Belt breaks fails");
  const none = responseLine("failure", null);
  assert.deepEqual([none.text, none.action, none.gap], ["No response if it fails", "Add in Maintenance", true]);
  const set = responseLine("failure", { name: "Replace drive belt", hours_each: 1.5, cost_each: 85 }, { per_failure: 85 });
  assert.equal(set.text, "If it fails: Replace drive belt (1.5 h, $85)");
  assert.equal(set.action, "Edit in Maintenance");
  assert.match(responseLine("failure", { name: "Replace", cost_each: 85 }, { per_failure: 285 }).text, /a failure costs \$285 all in$/);
});

// What an RCM decision owns is edited on the RCM tab only (Derryn, 23 Nov 2026): in the Maintenance
// task panel an RCM task's kind, failure modes and why it's done are one read-only line.
test("an RCM task's kind, failure modes and reason aren't editable in the Maintenance task panel", () => {
  const src = readFileSync(new URL("./components/MaintenanceTask.jsx", import.meta.url), "utf8");
  // The kind picker only for a task added directly; never sent for an RCM task.
  assert.match(src, /\) : !rcm && \(\n\s*<Field label="Kind of task">/);
  assert.match(src, /\.\.\.\(rcm \|\| resp \? \{\} : \{ outcome: f\.outcome \|\| null \}\)/);
  // Why it's done (reason, reference, the failure modes it prevents) only for a task added directly.
  assert.match(src, /\{!rcm && !resp && \(\n\s*<Section title="Why it's done"/);
  assert.match(src, /\.\.\.\(rcm \|\| resp \? \{\} : \{ source: f\.source, reference: f\.docRef \}\)/);
  assert.match(src, /if \(!rcm\) \{\n\s*const had = new Set/);
  // The quiet line: From RCM, its failure modes, its kind, Open in RCM.
  assert.match(src, /From RCM: \{\(task\.failure_modes/);
  assert.match(src, /Open in RCM ›/);
  // The order: kind, what's done, how often.
  const kind = src.indexOf('label="Kind of task"');
  const what = src.indexOf('label="What\'s done"');
  const how = src.indexOf('title="How often"');
  assert.ok(kind > 0 && kind < what && what < how);
  // No four-chip type switch: the one line (TaskSchedule).
  assert.doesNotMatch(src, /<HowOften /);
  assert.doesNotMatch(readFileSync(new URL("./components/TaskSchedule.jsx", import.meta.url), "utf8"), /ChoiceChips/);
});

test("one compact title line for a task on the RCM and Maintenance tabs (PanelKind)", () => {
  const rcm = readFileSync(new URL("./components/RcmWorksheet.jsx", import.meta.url), "utf8");
  const side = readFileSync(new URL("./components/TaskTreeTable.jsx", import.meta.url), "utf8");
  assert.match(rcm, /<PanelKind type=\{r\.type\}>/);
  assert.match(side, /<PanelKind type="task"/);
});

// A task's own reference (a manual's section) and a supporting task's reference interval were one
// field of the form, so saving a task added directly cleared its reference: now two.
test("saving a task keeps its reference (not the supporting task's reference interval)", () => {
  const src = readFileSync(new URL("./components/MaintenanceTask.jsx", import.meta.url), "utf8");
  assert.match(src, /docRef: task\?\.reference \|\| ""/);
  assert.match(src, /source: f\.source, reference: f\.docRef/);
  assert.doesNotMatch(src, /source: f\.source, reference: f\.reference/);
});
