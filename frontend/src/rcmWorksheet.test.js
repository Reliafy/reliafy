import { test } from "node:test";
import assert from "node:assert/strict";
import { flatten, levelSet } from "./outlineTree.js";
import {
  addableOutcomes, cardLineText, decisionCardLines, decisionRows, decisionWithMember, decisionWithoutMember, memberEvidenceText,
  COLUMN, COLUMNS, DEFAULT_COLUMNS, FUNCTION_MAX, NAME_COLUMN, functionCount, buildRcmDisplay, checkValue, chipCounts, computeFilter,
  insideWords, intervalText, loadPrefs, savePrefs, siblingOrder, decisionBody, decisionText, hasTask, isCombination, memberEvidenceLine, memberLine, modeCounts, moreTasks, rowText, tasksOf,
  tasksTip, LEVEL_OF, decisionWithMemberEvidence, taskRowWords, taskKindText } from "./rcmWorksheet.js";

// A house pool pump's RCM, as the server sends it back (decisions resolved).
const RCM = [
  { id: "f1", text: "Circulate the water", standard: "12 m³/h", failures: [
    { id: "x1", text: "No flow", modes: [
      { id: "m1", text: "Bearing seizes", effects: "Pump stops", consequence: "operational",
        decision: { outcome: "fixed_interval", task: "Replace bearings", interval: 3, interval_unit: "years", status: "supported" } },
      { id: "m2", text: "Capacitor fails", consequence: "non_operational",
        decision: { outcome: "rtf", rtf_basis: "random", status: "contradicted" } },
      { id: "m3", text: "Impeller worn", consequence: null, decision: null },
    ] },
  ] },
  { id: "f2", text: "Protect against dry running", failures: [
    { id: "x2", text: "Runs dry without tripping", modes: [
      { id: "m4", text: "Level switch stuck (hidden)", consequence: "hidden",
        decision: { outcome: "failure_finding", task: "Test the switch", interval: 1, interval_unit: "months", status: "unevidenced" } },
      { id: "m5", text: "Earth leakage device fails", consequence: "safety", decision: null },
    ] },
  ] },
];

test("the display: three levels, each row counting the failure modes inside it", () => {
  const d = buildRcmDisplay(RCM);
  assert.deepEqual(d.counts, { fn: 2, fail: 2, mode: 5 });
  assert.deepEqual(d.roots, ["f1", "f2"]);
  const f1 = d.rows.get("f1");
  assert.equal(f1.type, "fn");
  assert.deepEqual(d.rows.get("m3").at, [0, 0, 2]);
  assert.equal(d.rows.get("m3").depth, 2);
  assert.deepEqual(
    { modes: f1.sum.modes, undecided: f1.sum.undecided, tasks: f1.sum.tasks, supported: f1.sum.supported, contradicted: f1.sum.contradicted },
    { modes: 3, undecided: 1, tasks: 1, supported: 1, contradicted: 1 },
  );
  assert.equal(insideWords(f1), "3 failure modes · 1 to decide · 1 with a task");
  assert.equal(insideWords(d.rows.get("x2")), "2 failure modes · 1 to decide · 1 with a task");
  assert.equal(d.rows.get("f2").sum.hidden, 1);
  assert.equal(d.rows.get("f2").sum.safety, 1);
  // Level 1: functions only; level 2: their failures too.
  assert.deepEqual(flatten(d, levelSet(d, 1)).list.map((v) => v.key), ["f1", "f2"]);
  assert.deepEqual(flatten(d, levelSet(d, 2)).list.map((v) => v.key), ["f1", "x1", "f2", "x2"]);
});

test("a repeated id still gets a row of its own", () => {
  const d = buildRcmDisplay([{ id: "same", text: "A", failures: [{ id: "same", text: "B", modes: [] }] }]);
  assert.equal(d.rows.size, 2);
  assert.deepEqual([...d.rows.keys()], ["same", "same~"]);
});

test("the cells, as text: decisions, intervals, roll-ups", () => {
  const d = buildRcmDisplay(RCM);
  const m = (k) => d.rows.get(k);
  assert.equal(COLUMN.decision.text(m("m2")), "Run to failure (random)");
  assert.equal(COLUMN.decision.text(m("m3")), "To decide");
  assert.equal(COLUMN.decision.text(m("f1")), "1 to decide");
  assert.equal(COLUMN.interval.text(m("m1")), "3 years");
  assert.equal(intervalText({ interval: 1, interval_unit: "months" }), "1 month");
  assert.equal(COLUMN.task.text(m("x2")), "1 task");
  assert.equal(COLUMN.check.text(m("f1")), "1 contradicted, 1 supported");
  // Nothing linked is quiet: no "No evidence", no "to check" on the parents.
  assert.equal(COLUMN.check.text(m("m4")), "");
  assert.equal(COLUMN.check.text(m("f2")), "");
  assert.equal(m("f2").sum.unlinked, 1);
  assert.equal(m("f2").sum.unsure, 0);
  assert.equal(COLUMN.consequence.text(m("f2")), "1 safety or env.");
  assert.equal(COLUMN.evident.text(m("m4")), "Hidden");
  // Performance standards are rows of the tree now, not a column.
  assert.equal(COLUMN.standard, undefined);
  assert.equal(COLUMNS.some((c) => c.id === "standard"), false);
  // The default set fits a 1440 px window with the menu open (about 1,140 px for the grid).
  const width = DEFAULT_COLUMNS.reduce((s, id) => s + COLUMN[id].width, NAME_COLUMN.width);
  assert.ok(width <= 1140, `default columns are ${width} px wide`);
});

test("chips and text filter failure modes, keeping the path to each", () => {
  const d = buildRcmDisplay(RCM);
  // Evidence to look at: linked evidence only (m2 contradicted), not m4 with nothing linked.
  assert.deepEqual(chipCounts(d), { undecided: 2, hidden: 1, safety: 1, task: 2, notask: 3, check: 1 });
  const f = computeFilter(d, { chips: ["undecided"] });
  assert.deepEqual([...f.match].sort(), ["m3", "m5"]);
  assert.deepEqual([...f.keep].sort(), ["f1", "f2", "m3", "m5", "x1", "x2"]);
  assert.deepEqual([...computeFilter(d, { query: "replace bear" }).match], ["m1"]);
  assert.deepEqual([...computeFilter(d, { chips: ["undecided", "safety"] }).match], ["m5"]);
  assert.equal(computeFilter(d, { query: "  " }), null);
  assert.equal(computeFilter(d, { query: "nothing like it" }).match.size, 0);
});

test("sorting keeps the tree: siblings in order, blanks last", () => {
  const d = buildRcmDisplay(RCM);
  const byInterval = siblingOrder(d, { col: "interval", dir: -1 });
  assert.deepEqual(byInterval(["m1", "m2", "m3"]), ["m1", "m2", "m3"]);
  const byName = siblingOrder(d, { col: "name", dir: 1 });
  assert.deepEqual(byName(["m1", "m2", "m3"]), ["m1", "m2", "m3"]);
  assert.deepEqual(siblingOrder(d, { col: "name", dir: -1 })(["m1", "m2", "m3"]), ["m3", "m2", "m1"]);
  // Decision: undecided first going up; a parent sorts by how many are left to decide.
  assert.deepEqual(siblingOrder(d, { col: "decision", dir: 1 })(["m1", "m2", "m3"]), ["m3", "m1", "m2"]);
  assert.deepEqual(siblingOrder(d, { col: "check", dir: 1 })(["m1", "m2", "m3"]), ["m2", "m1", "m3"]);
  const all = flatten(d, levelSet(d, Infinity), null, siblingOrder(d, { col: "name", dir: -1 })).list.map((v) => v.key);
  assert.deepEqual(all, ["f2", "x2", "m4", "m5", "f1", "x1", "m3", "m2", "m1"]);
  assert.equal(siblingOrder(d, null), null);
});

test("cells checked as the server checks them; only the columns that allow it are edited in place", () => {
  const d = buildRcmDisplay(RCM);
  const m1 = d.rows.get("m1");
  assert.deepEqual(checkValue("name", m1, "  "), { error: "Every failure mode needs a description." });
  assert.deepEqual(checkValue("interval", m1, "-2"), { error: "The task interval must be positive." });
  assert.deepEqual(checkValue("interval", m1, "abc"), { error: "The task interval must be a number." });
  assert.deepEqual(checkValue("interval", m1, ""), { value: null });
  assert.deepEqual(checkValue("consequence", m1, "nonsense"), { value: null });
  assert.deepEqual(checkValue("effects", m1, " Leaks "), { value: "Leaks" });
  assert.equal(COLUMN.task.can(d.rows.get("m2")), true); // run-to-failure: the action on failure
  assert.equal(COLUMN.interval.can(d.rows.get("m2")), false);
  assert.equal(COLUMN.task.can(d.rows.get("m3")), false);
  assert.equal(COLUMN.effects.can(d.rows.get("f1")), false);
});

test("remembered on this device: columns, widths and row height; an earlier version's open rows dropped", () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.deepEqual(loadPrefs(storage).cols, DEFAULT_COLUMNS);
  savePrefs({ cols: ["task", "nope"], widths: { task: 300, bogus: 4 }, density: "compact", open: { s1: ["f1"] } }, storage);
  const p = loadPrefs(storage);
  assert.deepEqual(p.cols, ["task"]);
  assert.deepEqual(p.widths, { task: 300 });
  assert.equal(p.density, "compact");
  assert.equal(p.open, undefined);
  assert.ok(!JSON.parse(store.get("reliafy.rcmWorksheet")).open);
  // Storage that throws: the defaults, and saving quietly does nothing.
  const broken = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(loadPrefs(broken).density, "comfortable");
  assert.doesNotThrow(() => savePrefs(p, broken));
});

test("columns saved with the old Performance standard column load without it", () => {
  const store = new Map([["reliafy.rcmWorksheet", JSON.stringify({ cols: ["standard", "effects", "task"], widths: { standard: 220, task: 300 } })]]);
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  const p = loadPrefs(storage);
  assert.deepEqual(p.cols, ["effects", "task"]);
  assert.deepEqual(p.widths, { task: 300 });
  assert.equal(p.colsChosen, true); // still the user's own choice
  // Only the old column chosen: nothing left, the chooser still shows the name column (always on).
  store.set("reliafy.rcmWorksheet", JSON.stringify({ cols: ["standard"] }));
  assert.deepEqual(loadPrefs(storage).cols, []);
});

// ---- the RCM in the Explorer's tree -----------------------------------------

test("a decision goes back without the evidence check, a change applied", () => {
  const d = { outcome: "fixed_interval", task: "Replace", interval: 6, interval_unit: "months", status: "supported",
    summary: "ok", artifact_name: "A", evidence: { type: "strategy_analysis", id: "a" }, task_id: "t1" };
  assert.deepEqual(decisionBody(d), { outcome: "fixed_interval", task: "Replace", interval: 6, interval_unit: "months",
    evidence: { type: "strategy_analysis", id: "a" } });
  assert.deepEqual(decisionBody(d, { interval: null }), { outcome: "fixed_interval", task: "Replace",
    evidence: { type: "strategy_analysis", id: "a" } });
  assert.equal(decisionBody({ outcome: "fixed_interval" }, { interval: 3 }).interval_unit, "hours");
  assert.equal(decisionBody(null), null);
});

// A combination of tasks: an inspection plus a fixed-time replacement.
const COMBO = {
  outcome: "on_condition", task: "Vibration check", interval: 1, interval_unit: "months", task_id: "t1",
  notes: "Neither alone is enough", status: "unevidenced", evidence: null,
  outcomes: [
    { outcome: "on_condition", task: "Vibration check", interval: 1, interval_unit: "months", task_id: "t1" },
    { outcome: "fixed_interval", task: "Replace the bearing", interval: 24, interval_unit: "months", task_id: "t2" },
  ],
};

test("a combination reads as its outcomes joined, one outcome as before", () => {
  assert.equal(decisionText(COMBO), "On condition + Fixed interval");
  assert.equal(decisionText({ outcome: "fixed_interval" }), "Fixed interval");
  assert.equal(decisionText({ outcome: "rtf", rtf_basis: "random" }), "Run to failure (random)");
  assert.equal(decisionText({ outcome: "on_condition", outcomes: [{ outcome: "on_condition" }] }), "On condition");
  assert.equal(isCombination(COMBO), true);
  assert.equal(isCombination({ outcome: "on_condition" }), false);
  assert.equal(memberLine(COMBO.outcomes[1]), "Fixed interval: Replace the bearing · every 24 months");
  assert.equal(memberLine({ outcome: "redesign", task_id: null }), "Redesign (until the change is made)");
  assert.equal(memberLine({ outcome: "fixed_interval", task_id: null }), "Fixed interval: no task now");
});

test("a combination goes back whole, a cell's change on its first task", () => {
  // Each member by its task (task_id): two of one kind are told apart by their task.
  assert.deepEqual(decisionBody(COMBO), {
    outcomes: [
      { outcome: "on_condition", task_id: "t1", task: "Vibration check", interval: 1, interval_unit: "months" },
      { outcome: "fixed_interval", task_id: "t2", task: "Replace the bearing", interval: 24, interval_unit: "months" },
    ],
  });
  // The notes are the failure mode's (one place since Nov 2026): never sent with a decision.
  assert.equal(decisionBody({ outcome: "accept", notes: "Why" }).notes, undefined);
  const changed = decisionBody(COMBO, { interval: 2 });
  assert.equal(changed.outcomes[0].interval, 2);
  assert.equal(changed.outcomes[1].interval, 24);
  // What's done when a check finds it goes back with its member, or the decision.
  assert.equal(decisionBody({ ...COMBO, outcomes: [{ ...COMBO.outcomes[0], on_found: "Replace it" }, COMBO.outcomes[1]] }).outcomes[0].on_found, "Replace it");
  assert.equal(decisionBody({ outcome: "on_condition", interval: 1, interval_unit: "weeks", on_found: "Replace it" }).on_found, "Replace it");
  assert.equal(decisionBody(COMBO, { task: "Ultrasound check" }).outcomes[0].task, "Ultrasound check");
});

test("a function's text is kept to 200 characters where it's typed; one saved longer before stays editable", () => {
  const fn = { type: "fn", ref: { text: "Pump water" } };
  assert.deepEqual(checkValue("name", fn, "a".repeat(200)), { value: "a".repeat(200) });
  assert.deepEqual(checkValue("name", fn, "a".repeat(201)),
    { error: "Shorten it to 200 characters or fewer to save the change (it's 201)." });
  // Saved longer before: a change must bring it within the limit.
  const long = { type: "fn", ref: { text: "b".repeat(1200) } };
  assert.ok(checkValue("name", long, "b".repeat(1100)).error);
  assert.deepEqual(checkValue("name", long, "Pump water"), { value: "Pump water" });
  // Other rows have no such limit here (the server's own applies).
  assert.deepEqual(checkValue("name", { type: "mode", ref: { text: "" } }, "c".repeat(300)), { value: "c".repeat(300) });
  const c = functionCount("d".repeat(190));
  assert.equal(c.tone, "near");
  assert.equal(c.text, "190 / 200");
  assert.equal(FUNCTION_MAX, 200);
});


test("a decision's tasks: its own first, how many more, the tooltip, and an older read with one", () => {
  const d = { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks", task_id: "t1",
    tasks: [{ id: "t1", name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", shared_with: 1 },
      { id: "t2", name: "Replace the acid pump", text: "Replace the acid pump", interval: 24, unit: "months", shared_with: 0 }] };
  assert.equal(tasksOf(d).length, 2);
  assert.equal(moreTasks(d), "+1 task");
  assert.equal(moreTasks({ ...d, tasks: [...d.tasks, { id: "t3", name: "Look", interval: 1, unit: "months" }] }), "+2 tasks");
  assert.equal(tasksTip(d), "Weekly pH check · every 1 week (shared with 1 other failure mode)\nReplace the acid pump · every 24 months");
  const old = { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks" };
  assert.deepEqual(tasksOf(old), [{ id: null, name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", shared_with: 0 }]);
  assert.equal(moreTasks(old), "");
  assert.deepEqual(tasksOf(null), []);
  assert.deepEqual(tasksOf({ outcome: "rtf", rtf_basis: "random" }), []);
  assert.equal(hasTask({ decision: { outcome: "on_condition", tasks: d.tasks } }), true);
  assert.equal(hasTask({ decision: { outcome: "on_condition" } }), false);
  // The search reaches the other tasks' names too.
  assert.match(rowText({ ref: { text: "Acid", decision: d } }), /replace the acid pump/);
});

test("a combination's evidence: each member's own goes back with it, and each reads as a line", () => {
  const withOwn = { ...COMBO, outcomes: [COMBO.outcomes[0], { ...COMBO.outcomes[1], evidence: { type: "strategy_analysis", id: "sa1" }, status: "supported" }] };
  assert.deepEqual(decisionBody(withOwn).outcomes[1].evidence, { type: "strategy_analysis", id: "sa1" });
  assert.equal(decisionBody(withOwn).outcomes[0].evidence, undefined);
  assert.equal(memberEvidenceLine({ outcome: "fixed_interval", status: "supported", artifact_name: "Bearing replacement", evidence_from: "own" }),
    "Fixed interval: Supported · Bearing replacement");
  assert.equal(memberEvidenceLine({ outcome: "on_condition", status: "linked", evidence_kind: "working", artifact_name: "Pump water", evidence_from: "decision" }),
    "On condition: Notes linked · Pump water (the decision's)");
  assert.equal(memberEvidenceLine({ outcome: "fixed_interval", status: "unevidenced" }), "Fixed interval: none linked");
  assert.equal(memberEvidenceLine({ outcome: "redesign", status: null }), "Redesign: needs no evidence");
  // Partly evidenced counts with the decisions that still want evidence.
  assert.equal(modeCounts({ decision: { ...COMBO, status: "partly" } }).unlinked, 1);
});

test("a decision's rows: one per member task, then any other linked task; tasks before a decision", () => {
  const tasks = [{ id: "t1", name: "Vibration check" }, { id: "t2", name: "Replace the bearing" }, { id: "t3", name: "Grease" }];
  const rows = decisionRows(COMBO, tasks);
  assert.deepEqual(rows.map((r) => [r.key, r.outcome, r.task?.name ?? null]),
    [["t1", "on_condition", "Vibration check"], ["t2", "fixed_interval", "Replace the bearing"], ["t3", null, "Grease"]]);
  // A member whose task has gone, and a redesign: rows with no task.
  const gone = { ...COMBO, outcomes: [COMBO.outcomes[0], { outcome: "redesign", task_id: null }] };
  assert.deepEqual(decisionRows(gone, tasks.slice(0, 1)).map((r) => [r.outcome, r.task?.id ?? null]), [["on_condition", "t1"], ["redesign", null]]);
  // A plain decision: its tasks, the first with the decision's outcome when the task has none.
  const plain = { outcome: "on_condition", task_id: "t1" };
  assert.deepEqual(decisionRows(plain, [tasks[0], { ...tasks[1], outcome: "fixed_interval" }]).map((r) => r.outcome), ["on_condition", "fixed_interval"]);
  assert.deepEqual(decisionRows(null, tasks.slice(0, 1)).map((r) => r.outcome), [null]);
  // Tasks without an id (the worksheet outside the Explorer) aren't rows.
  assert.deepEqual(decisionRows(plain, [{ id: null, name: "x" }]), []);
});

test("the decision card's lines: the decision in words with its task, one line per task", () => {
  const text = (d, tasks) => decisionCardLines(d, tasks).map(cardLineText);
  // One task (the Explorer's, with an id): its kind, name and how often.
  assert.deepEqual(text({ outcome: "on_condition", task_id: "t1" }, [{ id: "t1", name: "Weekly level check", interval: 1, unit: "weeks" }]),
    ["On condition · Weekly level check · every 1 week"]);
  // A combination: one line per member, a member with no task now said so, then any other task.
  const tasks = [{ id: "t1", name: "Vibration check", interval: 1, unit: "months" }, { id: "t3", name: "Grease", interval: 3, unit: "months" }];
  const combo = { outcomes: [{ outcome: "on_condition", task_id: "t1" }, { outcome: "fixed_interval", task_id: "gone" }, { outcome: "redesign" }] };
  assert.deepEqual(text(combo, tasks),
    ["On condition · Vibration check · every 1 month", "Fixed interval · no task now", "Redesign · until the change is made", "Grease · every 3 months"]);
  // Run to failure: the decision and its action on failure.
  assert.deepEqual(text({ outcome: "rtf", task: "Replace on failure" }, []), ["Run to failure · Replace on failure"]);
  assert.deepEqual(text({ outcome: "accept" }, []), ["Accept"]);
  // No task ids (outside the Explorer): read from the decision itself.
  assert.deepEqual(text({ outcome: "fixed_interval", task: "Replace the seal", interval: 2, interval_unit: "years" }, tasksOf({ outcome: "fixed_interval", task: "Replace the seal", interval: 2 })),
    ["Fixed interval · Replace the seal · every 2 years"]);
  assert.deepEqual(text({ outcomes: [{ outcome: "on_condition", task: "Listen", interval: 1, interval_unit: "weeks" }, { outcome: "redesign" }] }, []),
    ["On condition · Listen · every 1 week", "Redesign · until the change is made"]);
  // A scheduled decision with no task yet: the decision alone.
  assert.deepEqual(text({ outcome: "failure_finding" }, []), ["Failure finding"]);
  assert.deepEqual(decisionCardLines(null, tasks), []);
});

test("the tasks that can join a decision follow the combination rules", () => {
  assert.deepEqual(addableOutcomes({ outcome: "on_condition", task_id: "t1" }), ["on_condition", "fixed_interval", "failure_finding", "redesign"]);
  // Each kind is offered again (one kind may come more than once); a redesign once.
  assert.deepEqual(addableOutcomes(COMBO), ["on_condition", "fixed_interval", "failure_finding", "redesign"]);
  assert.deepEqual(addableOutcomes({ ...COMBO, outcomes: [...COMBO.outcomes, { outcome: "redesign", task_id: null }] }),
    ["on_condition", "fixed_interval", "failure_finding"]);
  assert.deepEqual(addableOutcomes({ outcome: "fixed_interval", task_id: "t1" }, { hidden: false, consequence: "operational" }),
    ["on_condition", "fixed_interval", "redesign"]);
  assert.deepEqual(addableOutcomes({ outcome: "redesign" }), ["on_condition", "fixed_interval", "failure_finding"]);
  assert.deepEqual(addableOutcomes({ outcome: "rtf" }), []);
  assert.deepEqual(addableOutcomes({ outcome: "accept" }), []);
  assert.deepEqual(addableOutcomes({ outcome: "on_condition" }), []); // no task yet: decide it first
  assert.deepEqual(addableOutcomes(null), []);
});

test("a decision with one more member goes back with each member by its task", () => {
  const plain = { outcome: "on_condition", task: "Check", interval: 1, interval_unit: "weeks", task_id: "t1", notes: "Why", evidence: { type: "report", id: "r1", name: "x" } };
  assert.deepEqual(decisionWithMember(plain, { outcome: "fixed_interval", task: "Replace", interval: 24, interval_unit: "months" }), {
    outcomes: [{ outcome: "on_condition", task_id: "t1" }, { outcome: "fixed_interval", task: "Replace", interval: 24, interval_unit: "months" }],
    evidence: { type: "report", id: "r1" },
  });
  assert.deepEqual(decisionWithMember({ ...plain, on_found: "Replace it" }, { outcome: "fixed_interval", task_id: "t2" }).outcomes[0],
    { outcome: "on_condition", task_id: "t1", on_found: "Replace it" });
  const combo = { ...COMBO, outcomes: [{ ...COMBO.outcomes[0], evidence: { type: "model", id: "m1" } }, COMBO.outcomes[1]] };
  assert.deepEqual(decisionWithMember(combo, { outcome: "failure_finding", task_id: "t9" }), {
    outcomes: [{ outcome: "on_condition", task_id: "t1", evidence: { type: "model", id: "m1" } }, { outcome: "fixed_interval", task_id: "t2" },
      { outcome: "failure_finding", task_id: "t9" }],
  });
  assert.deepEqual(decisionWithMember({ outcome: "redesign" }, { outcome: "on_condition", task: "Watch", interval: 1, interval_unit: "weeks" }).outcomes,
    [{ outcome: "redesign" }, { outcome: "on_condition", task: "Watch", interval: 1, interval_unit: "weeks" }]);
  assert.equal(memberEvidenceText({ outcome: "fixed_interval", status: "unevidenced" }), "none linked");
});

test("step 3 in place: one tap sends the whole decision, keeping its task and fitting evidence (never the notes)", async () => {
  const { decisionWithOutcome, tasksDropped, keptTask, decisionWithFirstTask } = await import("./rcmWorksheet.js");
  const t1 = { id: "t1", name: "Weekly check" };
  const t2 = { id: "t2", name: "Replace", shared_with: 1 };
  const plain = { outcome: "on_condition", task_id: "t1", notes: "Why", evidence: { type: "degradation_model", id: "m1", extra: 1 } };
  // Another kind of task: the task it has, by id; a model linked for the old outcome goes.
  assert.deepEqual(decisionWithOutcome(plain, [t1], "fixed_interval"), { outcomes: [{ outcome: "fixed_interval", task_id: "t1" }] });
  assert.deepEqual(tasksDropped(plain, [t1], "fixed_interval"), []);
  // The same outcome again keeps its model; a report goes with any outcome.
  assert.deepEqual(decisionWithOutcome(plain, [t1], "on_condition").evidence, { type: "degradation_model", id: "m1" });
  assert.deepEqual(decisionWithOutcome({ ...plain, evidence: { type: "report", id: "r1" } }, [t1], "redesign"),
    { outcome: "redesign", evidence: { type: "report", id: "r1" } });
  // Nothing scheduled: every task comes off; run to failure takes its reason and keeps what's done on failure.
  assert.deepEqual(tasksDropped(plain, [t1], "rtf"), [t1]);
  assert.deepEqual(tasksDropped(plain, [t1], null), [t1]);
  assert.deepEqual(decisionWithOutcome({ outcome: "rtf", rtf_basis: "random", task: "Swap it" }, [], "rtf", "uneconomic"),
    { outcome: "rtf", rtf_basis: "uneconomic", task: "Swap it" });
  // No decision, a task linked before: a scheduled outcome adopts it.
  assert.equal(keptTask(null, [t2], "on_condition"), "t2");
  assert.deepEqual(decisionWithOutcome(null, [t2], "on_condition"), { outcomes: [{ outcome: "on_condition", task_id: "t2" }] });
  assert.deepEqual(decisionWithOutcome(null, [], "on_condition"), { outcome: "on_condition" });
  // A combination to one kind: the member of that kind keeps its task, the others come off.
  const combo = { outcome: "on_condition", task_id: "t1", outcomes: [{ outcome: "on_condition", task_id: "t1" }, { outcome: "fixed_interval", task_id: "t2" }] };
  assert.equal(keptTask(combo, [t1, t2], "fixed_interval"), "t2");
  assert.deepEqual(tasksDropped(combo, [t1, t2], "fixed_interval"), [t1]);
  // The first task for a scheduled decision with none: new, or an existing one by id.
  assert.deepEqual(decisionWithFirstTask({ outcome: "failure_finding", notes: "N" }, { task: "Test the trip", interval: 6, interval_unit: "months" }),
    { outcome: "failure_finding", task: "Test the trip", interval: 6, interval_unit: "months" });
  assert.deepEqual(decisionWithFirstTask({ outcome: "failure_finding" }, { outcome: "failure_finding", task_id: "t9" }),
    { outcomes: [{ outcome: "failure_finding", task_id: "t9" }] });
  assert.deepEqual(decisionWithFirstTask({ outcome: "on_condition" }, { task: "Look", interval: 1, interval_unit: "weeks", on_found: "Fix it" }),
    { outcome: "on_condition", task: "Look", interval: 1, interval_unit: "weeks", on_found: "Fix it" });
});

test("each task card leads with what it's for, and a check says what's done when it finds it", async () => {
  const { decisionCardLines, roleLine, roleLineText, decisionWithOnFound, firstLine, findsSomething, ROLE } = await import("./rcmWorksheet.js");
  const t1 = { id: "t1", name: "Vibration check", text: "Vibration check", interval: 1, unit: "months", outcome: "on_condition" };
  const t2 = { id: "t2", name: "Replace the bearing", text: "Replace the bearing", interval: 24, unit: "months", outcome: "fixed_interval" };
  const t3 = { id: "t3", name: "Trip test", text: "Trip test", interval: 6, unit: "months", outcome: "failure_finding" };
  // On condition: "Check:" the task, and its on_found as "Then, if found:".
  const single = { outcome: "on_condition", task_id: "t1", on_found: "Replace within 2 weeks", evidence: { type: "report", id: "r1", name: "x" } };
  const [one] = decisionCardLines(single, [t1]);
  assert.equal(roleLineText(one), "Check: Vibration check · every 1 month");
  assert.deepEqual(one.found, { at: 0, text: "Replace within 2 weeks" });
  assert.equal(ROLE.on_condition.then, "Then, if found:");
  assert.equal(ROLE.failure_finding.then, "Then, if failed:");
  // Empty: the line is still there (greyed in the card), with "" as its text.
  assert.deepEqual(decisionCardLines({ outcome: "on_condition", task_id: "t1" }, [t1])[0].found, { at: 0, text: "" });
  // Failure finding and fixed interval.
  assert.equal(roleLineText(decisionCardLines({ outcome: "failure_finding", task_id: "t3" }, [t3])[0]), "Check it still works: Trip test · every 6 months");
  const fixed = decisionCardLines({ outcome: "fixed_interval", task_id: "t2" }, [t2])[0];
  assert.equal(roleLineText(fixed), "Do: Replace the bearing · every 24 months");
  assert.equal(fixed.found, null);
  // A combination: each member's own on_found; a task outside the decision has none.
  const combo = { outcome: "on_condition", task_id: "t1", outcomes: [
    { outcome: "on_condition", task_id: "t1", on_found: "Plan the change" }, { outcome: "fixed_interval", task_id: "t2" }] };
  const lines = decisionCardLines(combo, [t1, t2, { ...t3, outcome: "failure_finding" }]);
  assert.deepEqual(lines.map((l) => l.found), [{ at: 0, text: "Plan the change" }, null, null]);
  // Run to failure: its action; accept and redesign: the first line of the mode's notes.
  const rtf = decisionCardLines({ outcome: "rtf", rtf_basis: "random", task: "Replace it" }, [])[0];
  assert.equal(roleLineText(rtf), "When it fails: Replace it");
  const accept = decisionCardLines({ outcome: "accept" }, [])[0];
  assert.equal(roleLineText(accept, "\n  Rare and cheap to fix.\nMore."), "Accepted: Rare and cheap to fix.");
  assert.deepEqual(roleLine(accept, ""), { lead: "Accepted:", name: null, every: null });
  assert.equal(roleLineText(decisionCardLines({ outcome: "redesign" }, [])[0], "Fit a guard"), "Change: Fit a guard");
  const withRedesign = { outcome: "on_condition", task_id: "t1", outcomes: [{ outcome: "on_condition", task_id: "t1" }, { outcome: "redesign", task_id: null }] };
  assert.equal(roleLineText(decisionCardLines(withRedesign, [t1])[1], "Fit a guard"), "Change: Fit a guard · until the change is made");
  // An event-triggered task says "on event: …" where the interval would be.
  const event = { ...t1, trigger: { kind: "event", text: "Lightning strike", with_interval: false } };
  assert.equal(roleLineText(decisionCardLines({ outcome: "on_condition", task_id: "t1" }, [event])[0]), "Check: Vibration check · on event: Lightning strike");
  assert.equal(firstLine(""), "");
  assert.ok(findsSomething("failure_finding") && !findsSomething("fixed_interval"));
  // Saving one: every member by its task, the one asked for with its new on_found.
  assert.deepEqual(decisionWithOnFound(single, 0, "Replace now"),
    { outcomes: [{ outcome: "on_condition", task_id: "t1", on_found: "Replace now" }], evidence: { type: "report", id: "r1" } });
  assert.deepEqual(decisionWithOnFound(combo, 0, ""), { outcomes: [
    { outcome: "on_condition", task_id: "t1", on_found: "" }, { outcome: "fixed_interval", task_id: "t2" }] });
  assert.deepEqual(decisionWithOnFound({ outcome: "on_condition", task: "Look", interval: 1, interval_unit: "weeks" }, 0, "Fix"),
    { outcome: "on_condition", task: "Look", interval: 1, interval_unit: "weeks", on_found: "Fix" });
});

// Several tasks of one kind (Derryn, 9 Nov 2026): a weekly acid top-up and an annual deep clean,
// both fixed interval, beside an on-condition shop test.
const POOL = {
  outcome: "fixed_interval", task: "Acid top-up", interval: 1, interval_unit: "weeks", task_id: "w",
  outcomes: [
    { outcome: "fixed_interval", task: "Acid top-up", interval: 1, interval_unit: "weeks", task_id: "w" },
    { outcome: "fixed_interval", task: "Deep clean", interval: 12, interval_unit: "months", task_id: "a" },
    { outcome: "on_condition", task: "Shop water test", interval: 1, interval_unit: "months", task_id: "s", on_found: "Adjust the dosing" },
  ],
};

test("two members of one kind: counted in the chip, a line and a row each, told apart by their task", () => {
  assert.equal(decisionText(POOL), "2 fixed interval + On condition");
  assert.equal(decisionText({ ...POOL, outcomes: [POOL.outcomes[2], POOL.outcomes[0], POOL.outcomes[1]] }), "On condition + 2 fixed interval");
  const tasks = [{ id: "w", name: "Acid top-up" }, { id: "a", name: "Deep clean" }, { id: "s", name: "Shop water test" }];
  const rows = decisionRows(POOL, tasks);
  assert.deepEqual(rows.map((r) => [r.key, r.outcome]), [["w", "fixed_interval"], ["a", "fixed_interval"], ["s", "on_condition"]]);
  assert.deepEqual(decisionCardLines(POOL, tasks).map((l) => l.name), ["Acid top-up", "Deep clean", "Shop water test"]);
  assert.deepEqual(decisionBody(POOL).outcomes.map((o) => o.task_id), ["w", "a", "s"]);
});

test("removing a member sends the others back by their task; one left is a plain decision", () => {
  assert.deepEqual(decisionWithoutMember(POOL, "w"), {
    outcomes: [{ outcome: "fixed_interval", task_id: "a" }, { outcome: "on_condition", task_id: "s", on_found: "Adjust the dosing" }],
  });
  const two = { ...POOL, outcomes: POOL.outcomes.slice(0, 2) };
  assert.deepEqual(decisionWithoutMember(two, "a"), { outcomes: [{ outcome: "fixed_interval", task_id: "w" }] });
  assert.equal(decisionWithoutMember(POOL, "elsewhere"), null);
  assert.equal(decisionWithoutMember({ outcome: "fixed_interval", task_id: "w" }, "w"), null);
});

// ---- a task row (the Explorer tree's fifth level) -------------------------------------

test("a task is a level of its own, named in the tree's first column", () => {
  assert.equal(LEVEL_OF.task.label, "Task");
  assert.equal(LEVEL_OF.task.child, null);
  assert.equal(NAME_COLUMN.label, "Function, performance standard, failure, mode or task");
});

test("a task row's words: its kind, how often, its chips, and what's done when found", () => {
  const r = { type: "task", ref: { outcome: "failure_finding", on_found: "Repair the trip",
    task: { id: "t", name: "Test the trip", interval: 6, unit: "months", shared_with: 2, package: { id: "k", name: "Half-yearly" } } } };
  assert.equal(taskKindText(r), "Failure finding");
  assert.equal(taskRowWords(r), "every 6 months · Shared with 2 · In: Half-yearly");
  assert.equal(taskRowWords(r, { found: true }), "Failure finding · every 6 months · Shared with 2 · In: Half-yearly · Then, if failed: Repair the trip");
  const ev = { type: "task", ref: { outcome: "on_condition", task: { id: "e", name: "Re-dose", interval: 1, unit: "weeks", trigger: { text: "120 mm on POOL-RAIN" } } } };
  assert.equal(taskRowWords(ev), "on event: 120 mm on POOL-RAIN");
});

test("a combination's member gets its own evidence; the others and the decision's are kept", () => {
  const d = {
    outcome: "on_condition", evidence: { type: "report", id: "r1", name: "x" },
    outcomes: [
      { outcome: "on_condition", task_id: "t1", task: "Look", interval: 1, interval_unit: "weeks", on_found: "Fix" },
      { outcome: "fixed_interval", task_id: "t2", task: "Swap", interval: 2, interval_unit: "years", evidence: { type: "model", id: "m0", status: "x" } },
    ],
  };
  const set = decisionWithMemberEvidence(d, 0, { type: "model", id: "m1" });
  assert.deepEqual(set.outcomes[0].evidence, { type: "model", id: "m1" });
  assert.equal(set.outcomes[0].on_found, "Fix");
  assert.deepEqual(set.outcomes[1].evidence, { type: "model", id: "m0" });
  assert.deepEqual(set.evidence, { type: "report", id: "r1", name: "x" });
  const cleared = decisionWithMemberEvidence(d, 1, null);
  assert.equal("evidence" in cleared.outcomes[1], false);
  assert.equal(cleared.outcomes[1].task_id, "t2");
});
