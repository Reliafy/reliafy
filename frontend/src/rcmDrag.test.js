import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay } from "./assetTree.js";
import { graftRcm } from "./explorerRcm.js";
import {
  answerNotes, dragBlock, dragSource, dropZones, moveChoices, moveItems, place, planDrop, positionWithin, refusalText,
  sourceWords, stepTarget, undoBatch, zoneAt,
} from "./rcmDrag.js";

const DATA = {
  positions: [
    { id: "plant", name: "Plant", parent_id: null },
    { id: "pump", name: "Pump A", parent_id: "plant" },
    { id: "pumpb", name: "Pump B", parent_id: "plant" },
    { id: "motor", name: "Motor", parent_id: "pump" },
  ],
  locations: [], spares: [], unhomed: [],
};
const mode = (id, text, tasks = []) => ({ id, text, consequence: "operational", decision: null, tasks });
const RCM = {
  positions: [
    {
      id: "pump",
      functions: [
        { id: "f1", text: "Pump water", standards: [{ id: "s1", text: "50 L/s" }, { id: "s2", text: "4 bar" }], failures: [
          { id: "x1", text: "No flow", standard: { id: "s1", text: "50 L/s" }, modes: [
            mode("m1", "Bearing seizes", [{ id: "t1", name: "Grease bearings", position_id: "pump" }]), mode("m2", "Seal leaks")] },
          { id: "x2", text: "Low pressure", standard: { id: "s2", text: "4 bar" }, modes: [mode("m3", "Impeller worn")] },
          { id: "x3", text: "Noisy", standard: null, modes: [] },
        ] },
        { id: "f2", text: "Contain the water", standard: "No leaks", failures: [{ id: "x4", text: "Leaks", modes: [] }] },
      ],
      unassigned: [mode("m4", "Coupling fails")],
    },
    { id: "pumpb", functions: [{ id: "g1", text: "Pump more water", standards: [{ id: "s9", text: "20 L/s" }], failures: [
      { id: "y1", text: "No flow", standard: { id: "s9", text: "20 L/s" }, modes: [mode("n1", "Shaft breaks")] }] }], unassigned: [] },
    { id: "motor", functions: [], unassigned: [mode("k1", "Winding burns")] },
  ],
};
const whole = () => graftRcm(buildDisplay(DATA, "positions"), RCM);
const src = (d, key, opts) => dragSource(d, key, opts);

test("what can be dragged: functions, standards of a list, failures, modes (one or the picked ones), a mode's task", () => {
  const d = whole();
  assert.deepEqual(src(d, "f1"), { kind: "fn", keys: ["f1"] });
  assert.deepEqual(src(d, "s1"), { kind: "std", keys: ["s1"] });
  assert.equal(src(d, "S:f2"), null); // the one text's row
  assert.match(dragBlock(d.rows.get("S:f2")), /one standard text/);
  assert.equal(src(d, "pump"), null);
  assert.equal(src(d, "U:pump"), null);
  assert.deepEqual(src(d, "m1", { picked: new Set(["m1", "m3"]) }), { kind: "modes", keys: ["m1", "m3"] });
  assert.deepEqual(src(d, "m2", { picked: new Set(["m1", "m3"]) }), { kind: "modes", keys: ["m2"] });
  assert.deepEqual(src(d, "m1", { task: { id: "t1", name: "Grease bearings", position_id: "pump" } }).task.id, "t1");
});

test("the zones: into, before or after, as what's dragged and the row allow", () => {
  const d = whole();
  const zones = (s, key) => dropZones(d, s, key);
  assert.deepEqual(zones(src(d, "f1"), "pumpb").zones, ["into"]);
  assert.deepEqual(zones(src(d, "f1"), "f2").zones, ["before", "after"]);
  assert.deepEqual(zones(src(d, "f1"), "x1"), { zones: [] }); // inside itself: nothing shows
  assert.match(zones(src(d, "f2"), "m1").reason, /goes on a position/);
  assert.deepEqual(zones(src(d, "x1"), "s2").zones, ["into"]);
  assert.deepEqual(zones(src(d, "x1"), "x2").zones, ["before", "after"]);
  assert.deepEqual(zones(src(d, "m1"), "m3").zones, ["before", "after"]);
  assert.deepEqual(zones(src(d, "m1"), "m4").zones, ["into"]); // a mode under none: its group
  assert.match(zones(src(d, "s1"), "m3").reason, /belongs to a function/);
  assert.equal(zoneAt(["before", "into", "after"], 0.1), "before");
  assert.equal(zoneAt(["before", "into", "after"], 0.5), "into");
  assert.equal(zoneAt(["before", "into", "after"], 0.9), "after");
  assert.equal(zoneAt(["before", "after"], 0.6), "after");
  assert.equal(zoneAt(["into"], 0.95), "into");
  assert.equal(zoneAt([], 0.5), null);
});

test("a function: to another position, or placed among the functions", () => {
  const d = whole();
  const moved = planDrop(d, src(d, "f1"), "pumpb", "into");
  assert.deepEqual(moved.ops, [{ do: "failure_modes.move_function", args: { function_id: "f1", position_id: "pumpb" } }]);
  assert.deepEqual(moved.extraUndo, [{ do: "failure_modes.reorder", args: { parent_id: "pump", ids: ["f1", "f2"] } }]);
  assert.match(moved.text, /to “Pump B”, with everything under it/);
  assert.match(planDrop(d, src(d, "f1"), "pump", "into").refuse, /on this position already/);
  assert.deepEqual(planDrop(d, src(d, "f1"), "f2", "after").ops,
    [{ do: "failure_modes.reorder", args: { parent_id: "pump", ids: ["f2", "f1"] } }]);
  assert.deepEqual(planDrop(d, src(d, "f1"), "f2", "before"), { none: true }); // where it is
  assert.deepEqual(planDrop(d, src(d, "f2"), "g1", "before").ops, [
    { do: "failure_modes.move_function", args: { function_id: "f2", position_id: "pumpb" } },
    { do: "failure_modes.reorder", args: { parent_id: "pumpb", ids: ["f2", "g1"] } },
  ]);
});

test("a functional failure: to a function, onto a standard, under No standard, or placed among its siblings", () => {
  const d = whole();
  const x1 = src(d, "x1");
  assert.deepEqual(planDrop(d, x1, "s2", "into").ops,
    [{ do: "failure_modes.update_functional_failure", args: { functional_failure_id: "x1", standard_id: "s2" } }]);
  assert.match(planDrop(d, x1, "s1", "into").refuse, /breaches this standard already/);
  assert.deepEqual(planDrop(d, x1, "N:f1", "into").ops,
    [{ do: "failure_modes.update_functional_failure", args: { functional_failure_id: "x1", standard_id: "none" } }]);
  assert.match(planDrop(d, x1, "f1", "into").refuse, /under this function already/);
  // To another function: its standard there, or none.
  const there = planDrop(d, x1, "s9", "into");
  assert.deepEqual(there.ops, [{ do: "failure_modes.move_functional_failure", args: { functional_failure_id: "x1", function_id: "g1", standard_id: "s9" } }]);
  assert.deepEqual(there.extraUndo, [{ do: "failure_modes.reorder", args: { parent_id: "f1", ids: ["x1", "x2", "x3"] } }]);
  assert.deepEqual(planDrop(d, x1, "f2", "into").ops, [{ do: "failure_modes.move_functional_failure", args: { functional_failure_id: "x1", function_id: "f2" } }]);
  assert.deepEqual(planDrop(d, x1, "S:f2", "into").ops, planDrop(d, x1, "f2", "into").ops); // the one text's row: the function
  // Before a sibling under another standard: it takes that one's standard, and its place.
  assert.deepEqual(planDrop(d, x1, "x2", "after").ops, [
    { do: "failure_modes.update_functional_failure", args: { functional_failure_id: "x1", standard_id: "s2" } },
    { do: "failure_modes.reorder", args: { parent_id: "f1", ids: ["x2", "x1", "x3"] } },
  ]);
  assert.deepEqual(planDrop(d, src(d, "x3"), "x2", "before").ops, [
    { do: "failure_modes.update_functional_failure", args: { functional_failure_id: "x3", standard_id: "s2" } },
    { do: "failure_modes.reorder", args: { parent_id: "f1", ids: ["x1", "x3", "x2"] } },
  ]);
  assert.deepEqual(planDrop(d, x1, "y1", "before").ops, [
    { do: "failure_modes.move_functional_failure", args: { functional_failure_id: "x1", function_id: "g1", standard_id: "s9" } },
    { do: "failure_modes.reorder", args: { parent_id: "g1", ids: ["x1", "y1"] } },
  ]);
  assert.match(planDrop(d, x1, "m3", "into").refuse, /goes under a function or a standard/);
});

test("failure modes, one or several: under a functional failure (assigned here, moved from elsewhere), placed, or under none", () => {
  const d = whole();
  const two = src(d, "m1", { picked: new Set(["m1", "k1"]) });
  const under = planDrop(d, two, "x2", "into");
  assert.deepEqual(under.ops, [
    { do: "failure_modes.assign", args: { failure_mode_id: "m1", functional_failure_id: "x2" } },
    { do: "failure_modes.move", args: { failure_mode_id: "k1", position_id: "pump", functional_failure_id: "x2" } },
  ]);
  assert.deepEqual(under.extraUndo, [{ do: "failure_modes.reorder", args: { parent_id: "x1", ids: ["m1", "m2"] } }]);
  assert.match(under.text, /2 failure modes/);
  // Placed among the target's modes in one batch.
  assert.deepEqual(planDrop(d, two, "m3", "before").ops, [
    { do: "failure_modes.assign", args: { failure_mode_id: "m1", functional_failure_id: "x2" } },
    { do: "failure_modes.move", args: { failure_mode_id: "k1", position_id: "pump", functional_failure_id: "x2" } },
    { do: "failure_modes.reorder", args: { parent_id: "x2", ids: ["m1", "k1", "m3"] } },
  ]);
  assert.deepEqual(planDrop(d, src(d, "m1"), "m2", "after").ops, [{ do: "failure_modes.reorder", args: { parent_id: "x1", ids: ["m2", "m1"] } }]);
  assert.deepEqual(planDrop(d, src(d, "m1"), "m2", "before"), { none: true });
  assert.match(planDrop(d, src(d, "m1"), "x1", "into").refuse, /under this functional failure already/);
  // Under none: on its position, unassigned; on another, moved there.
  assert.deepEqual(planDrop(d, src(d, "m1"), "U:pump", "into").ops, [{ do: "failure_modes.assign", args: { failure_mode_id: "m1" } }]);
  assert.deepEqual(planDrop(d, src(d, "m1"), "pumpb", "into").ops, [{ do: "failure_modes.move", args: { failure_mode_id: "m1", position_id: "pumpb" } }]);
  assert.match(planDrop(d, src(d, "m1"), "pump", "into").refuse, /on this position already/);
  assert.deepEqual(planDrop(d, src(d, "m4"), "m3", "after").ops.map((o) => o.do), ["failure_modes.assign", "failure_modes.reorder"]);
  assert.match(planDrop(d, src(d, "m1"), "f1", "into").refuse, /under a functional failure/);
});

test("a standard: placed among its function's, or to another function with everything under it", () => {
  const d = whole();
  assert.deepEqual(planDrop(d, src(d, "s1"), "s2", "after").ops,
    [{ do: "failure_modes.reorder_standards", args: { function_id: "f1", standard_ids: ["s2", "s1"] } }]);
  // To another function, on another position: the standard, then its functional failure
  // (with its modes and tasks), breaching it again there. One batch.
  const away = planDrop(d, src(d, "s1"), "g1", "into");
  assert.deepEqual(away.ops, [
    { do: "failure_modes.move_standard", args: { standard_id: "s1", function_id: "g1" } },
    { do: "failure_modes.move_functional_failure", args: { functional_failure_id: "x1", function_id: "g1", standard_id: "s1" } },
  ]);
  assert.equal(away.text, "Move the standard “50 L/s” and its functional failure to “Pump more water”, with its failure modes and tasks");
  assert.equal(away.done, "Moved the standard “50 L/s” and its functional failure to “Pump more water”.");
  // Undo: the server's list, then the old order of the standards and of the failures.
  assert.deepEqual(away.extraUndo, [
    { do: "failure_modes.reorder_standards", args: { function_id: "f1", standard_ids: ["s1", "s2"] } },
    { do: "failure_modes.reorder", args: { parent_id: "f1", ids: ["x1", "x2", "x3"] } },
  ]);
  // Before a standard of another function: moved, its failure with it, and placed.
  assert.deepEqual(planDrop(d, src(d, "s2"), "s9", "before").ops, [
    { do: "failure_modes.move_standard", args: { standard_id: "s2", function_id: "g1" } },
    { do: "failure_modes.move_functional_failure", args: { functional_failure_id: "x2", function_id: "g1", standard_id: "s2" } },
    { do: "failure_modes.reorder_standards", args: { function_id: "g1", standard_ids: ["s2", "s9"] } },
  ]);
  // Onto a function with its one text, on the same position: the standard and its failure.
  assert.deepEqual(planDrop(d, src(d, "s1"), "S:f2", "into").ops.map((o) => [o.do, o.args.function_id]), [
    ["failure_modes.move_standard", "f2"], ["failure_modes.move_functional_failure", "f2"]]);
  assert.match(planDrop(d, src(d, "s1"), "f1", "into").refuse, /standard of this function already/);
  // Not into a row under itself.
  assert.deepEqual(dropZones(d, src(d, "s1"), "x1").zones, []);
});

test("a standard with nothing under it moves alone; the label says what moves", () => {
  const RCM2 = structuredClone(RCM);
  RCM2.positions[0].functions[0].standards.push({ id: "s3", text: "Quiet" });
  RCM2.positions[0].functions[0].failures.push({ id: "x5", text: "Rattles", standard: { id: "s2", text: "4 bar" }, modes: [] });
  const d = graftRcm(buildDisplay(DATA, "positions"), RCM2);
  const lone = planDrop(d, src(d, "s3"), "g1", "into");
  assert.deepEqual(lone.ops, [{ do: "failure_modes.move_standard", args: { standard_id: "s3", function_id: "g1" } }]);
  assert.deepEqual(lone.extraUndo, [{ do: "failure_modes.reorder_standards", args: { function_id: "f1", standard_ids: ["s1", "s2", "s3"] } }]);
  assert.equal(lone.text, "Move the standard “Quiet” to “Pump more water”");
  assert.equal(sourceWords(d, src(d, "s3")), "the standard “Quiet”");
  assert.equal(sourceWords(d, src(d, "s2")), "the standard “4 bar” and its 2 functional failures");
  assert.deepEqual(planDrop(d, src(d, "s2"), "g1", "into").ops.slice(1).map((o) => o.args.functional_failure_id), ["x2", "x5"]);
  assert.match(planDrop(d, src(d, "s2"), "g1", "into").text, /with their failure modes and tasks$/);
});

test("everything under a standard row stays draggable: its failures, their modes (one or picked), their tasks", () => {
  const d = whole();
  assert.equal(d.rows.get("x1").parent, "s1"); // the failure sits under its standard's row
  assert.deepEqual(src(d, "x1"), { kind: "fail", keys: ["x1"] });
  assert.deepEqual(src(d, "m2"), { kind: "modes", keys: ["m2"] });
  assert.deepEqual(src(d, "m1", { picked: new Set(["m1", "m2", "m3"]) }).keys, ["m1", "m2", "m3"]);
  assert.equal(src(d, "m1", { task: { id: "t1", name: "Grease bearings", position_id: "pump" } }).kind, "task");
  assert.deepEqual(planDrop(d, src(d, "x1"), "g1", "into").ops.map((o) => o.do), ["failure_modes.move_functional_failure"]);
  assert.deepEqual(planDrop(d, src(d, "m2"), "y1", "into").ops.map((o) => o.do), ["failure_modes.move"]);
  assert.equal(dragBlock(d.rows.get("x1")), null);
});

test("a standard's note that its failures stay isn't said when the batch moves them too", () => {
  const moved = { results: [
    { do: "failure_modes.move_standard", result: { unlinked_functional_failure_ids: ["x1"], note: "1 functional failure that breached it stays with the old function, under no standard." } },
    { do: "failure_modes.move_functional_failure", result: { moved: "x1", note: "1 link went." } },
  ] };
  assert.deepEqual(answerNotes(moved), ["1 link went."]);
  const alone = { results: [moved.results[0]] };
  assert.equal(answerNotes(alone).length, 1);
});

test("a task moves from its failure mode to another (moved to that position when it can't reach), or to a position", () => {
  const d = whole();
  const t = src(d, "m1", { task: { id: "t1", name: "Grease bearings", position_id: "pump" } });
  assert.deepEqual(planDrop(d, t, "m3", "into").ops, [
    { do: "tasks.unlink", args: { task_id: "t1", failure_mode_id: "m1" } },
    { do: "tasks.link", args: { task_id: "t1", failure_mode_id: "m3" } },
  ]);
  // Motor is inside Pump A: the task reaches it from where it is.
  assert.equal(planDrop(d, t, "k1", "into").ops.length, 2);
  assert.deepEqual(planDrop(d, t, "n1", "into").ops, [
    { do: "tasks.unlink", args: { task_id: "t1", failure_mode_id: "m1" } },
    { do: "tasks.move", args: { task_id: "t1", position_id: "pumpb" } },
    { do: "tasks.link", args: { task_id: "t1", failure_mode_id: "n1" } },
  ]);
  assert.match(planDrop(d, t, "n1", "into").text, /stops preventing “Bearing seizes”/);
  assert.deepEqual(planDrop(d, t, "pumpb", "into").ops, [{ do: "tasks.move", args: { task_id: "t1", position_id: "pumpb" } }]);
  assert.match(planDrop(d, t, "pump", "into").refuse, /on this position already/);
  assert.deepEqual(planDrop(d, t, "m1", "into"), { none: true });
  assert.match(planDrop(d, t, "x1", "into").refuse, /goes on a failure mode/);
  assert.ok(positionWithin(d, "motor", "plant") && !positionWithin(d, "plant", "motor"));
});

test("Move to…: the places each kind can go, by position, never where it is", () => {
  const d = whole();
  const keys = (s) => moveChoices(d, s).flatMap((g) => g.items.map((i) => i.key));
  assert.deepEqual(keys(src(d, "f1")), ["plant", "motor", "pumpb"]);
  assert.deepEqual(keys(src(d, "s1")), ["f2", "g1"]);
  assert.ok(keys(src(d, "x1")).includes("s2") && keys(src(d, "x1")).includes("N:f1") && !keys(src(d, "x1")).includes("s1"));
  assert.deepEqual(keys(src(d, "m1")), ["plant", "x2", "x3", "x4", "U:pump", "U:motor", "y1", "pumpb"]);
  assert.ok(!keys(src(d, "m1")).includes("x1") && keys(src(d, "m1")).includes("y1") && keys(src(d, "m1")).includes("U:motor"));
  const task = keys(src(d, "m1", { task: { id: "t1", name: "Grease", position_id: "pump" } }));
  assert.ok(task.includes("m3") && task.includes("n1") && task.includes("pumpb") && !task.includes("m1") && !task.includes("pump"));
  const g = moveChoices(d, src(d, "f1"));
  assert.deepEqual(g.map((x) => [x.name, x.depth]), [["Plant", 0], ["Motor", 2], ["Pump B", 1]]);
});

test("the row menus' moves: Move to…, and Move up / down among siblings", () => {
  const d = whole();
  const ids = (key, picked) => moveItems(d, d.rows.get(key), { picked }).map((i) => [i.id, !!i.disabled]);
  assert.deepEqual(ids("f1"), [["move-to", false], ["step-up", true], ["step-down", false]]);
  assert.deepEqual(ids("s1"), [["move-to", false]]); // its Move up / down are the standard's own
  assert.deepEqual(ids("x1"), [["move-to", false], ["step-up", true], ["step-down", true]]); // alone under its standard
  assert.deepEqual(ids("m1"), [["move-to", false], ["step-up", true], ["step-down", false], ["move-task", false]]);
  assert.deepEqual(ids("m4"), [["move-to", false]]); // under none: no order to change, no task
  assert.equal(moveItems(d, d.rows.get("m1"), { picked: new Set(["m1", "m2"]) })[0].label, "Move 2 failure modes to…");
  assert.deepEqual(moveItems(d, d.rows.get("S:f2")), []);
  assert.deepEqual(stepTarget(d, "f1", 1), { key: "f2", zone: "after" });
  assert.deepEqual(stepTarget(d, "m2", -1), { key: "m1", zone: "before" });
  assert.equal(stepTarget(d, "m4", 1), null);
});

test("helpers: place, the undo batch, the server's notes and refusals in plain words", () => {
  assert.deepEqual(place(["a", "b", "c"], ["c"], "a", "before"), ["c", "a", "b"]);
  assert.deepEqual(place(["a", "b", "c"], ["a", "b"], "c", "after"), ["c", "a", "b"]);
  assert.deepEqual(place(["a"], ["z"], null, "after"), ["a", "z"]);
  assert.deepEqual(undoBatch({ undo: [{ do: "x" }] }, [{ do: "y" }]), [{ do: "x" }, { do: "y" }]);
  assert.deepEqual(answerNotes({ results: [{ result: { note: "1 link went." } }, { result: { note: "1 link went." } }, {}] }), ["1 link went."]);
  const err = { data: { failed: { error: "op 1 (failure_modes.move): It's already on Pump A: pick another position." } } };
  assert.equal(refusalText(err), "It's already on Pump A: pick another position.");
  assert.equal(refusalText({ message: "Nothing was changed: op 0 (tasks.move): Grease has an open work order (#4)." }), "Grease has an open work order (#4).");
});
