import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay } from "./assetTree.js";
import {
  BLOCK_STATES, MAX_PHASES, answerText, leaveOut, placeholderTitle, placeholderWarning, blockState, fadedIn, withBlockState, changedPhases, cleanPhases, completesText, editablePhase, feedsText, graftMissions, isMissionRow,
  isPhaseRow, latestOnly, lengthText, missionKey, missionParam, missionRowActions, movePhase, newPhase, parseMissionParam, phaseCompletes,
  phaseCovariates, phaseKey, phaseLengthText, phaseLine, phaseNeeds, phaseOfText, phasesText, positionMissionActions, rollupText, typed,
  withBlockValue, withNewPhase, withoutPhase, withValue,
} from "./explorerMissions.js";

const DATA = {
  positions: [
    { id: "drone", name: "Survey drone", parent_id: null },
    { id: "gimbal", name: "Gimbal", parent_id: "drone" },
    { id: "battery", name: "Battery", parent_id: "drone" },
    { id: "arm", name: "Arm", parent_id: "drone" },
    { id: "arm-motor", name: "Arm motor", parent_id: "arm" },
  ],
  locations: [], spares: [], unhomed: [],
};
const RBD = { id: "r1", name: "Drone RBD", unit: "Hours", repairable: false, network: false };
const LINKS = [
  { position_id: "drone", link_id: "l1", in_use: true, rbd: RBD, missions: [
    { id: "m1", name: "Corridor inspection", phases: 3, phase_names: ["Take-off", "Transit", "Landing"], phase_durations: [0.25, 1, 0.25], duration: 1.5, unit: "Hours",
      result: { reliability: 0.9821, method: "exact" } },
    { id: "m2", name: "Survey grid", phases: 0, phase_names: [], duration: 0, unit: "Hours" },
  ] },
  { position_id: "gimbal", link_id: "l2", in_use: true, rbd: { ...RBD, id: "r2", name: "Gimbal RBD" }, missions: [] },
];

test("missions hang under their own position, never a parent's", () => {
  const d = graftMissions(buildDisplay(DATA, "positions"), LINKS);
  const drone = d.rows.get("drone");
  assert.deepEqual(drone.kids.slice(0, 2), [missionKey("r1", "m1"), missionKey("r1", "m2")]);
  assert.ok(isMissionRow(d.rows.get(missionKey("r1", "m1"))));
  assert.equal(d.rows.get(missionKey("r1", "m1")).ref.position_id, "drone");
  assert.equal(rollupText(drone, true), "2 missions");
  assert.equal(rollupText(d.rows.get("gimbal"), true), "No missions yet · Add a mission");
  assert.equal(rollupText(d.rows.get("battery"), true), "No missions yet · needs a life model or positions inside");
  assert.equal(rollupText(d.rows.get("arm"), true), "No missions yet · Add a mission");
  assert.equal(rollupText(d.rows.get("battery"), false), "No missions yet · needs a life model or positions inside");
  // Closed, a parent with no RBD still says a mission can be added (it's built from what's inside).
  assert.equal(rollupText(d.rows.get("arm"), false), "No missions yet · Add a mission");
  // A leaf with a model in use can have one too (one block).
  const withModel = graftMissions(buildDisplay(DATA, "positions"), LINKS, ["battery"]);
  assert.equal(rollupText(withModel.rows.get("battery"), false), "No missions yet · Add a mission");
  assert.ok(!d.rows.get("gimbal").kids.some((k) => k.startsWith("MS:")));
});

test("the pane's address names the RBD and the mission", () => {
  assert.equal(missionParam("abc", "m1"), "abc:m1");
  assert.deepEqual(parseMissionParam("abc:m1"), { rbdId: "abc", missionId: "m1" });
  assert.equal(parseMissionParam("abc"), null);
  assert.equal(parseMissionParam(":m1"), null);
});

test("a mission row's cells in words", () => {
  const [m1, m2] = LINKS[0].missions;
  assert.equal(phasesText(m1), "3 phases: Take-off, Transit, Landing");
  assert.equal(phasesText(m2), "No phases yet");
  assert.equal(lengthText(1.5, "Hours"), "1.5 hours");
  assert.equal(lengthText(1, "Hours"), "1 hour");
  assert.equal(completesText(m1), "98.2%");
  assert.equal(completesText(m2), "—");
  assert.equal(completesText({ result: { reliability: null, through: { phase: "Take-off", reliability: 0.999 } } }),
    "Waiting · 99.90% to Take-off");
});

test("a position's actions: Add a mission (an RBD of its own), wherever one can be built", () => {
  const d = graftMissions(buildDisplay(DATA, "positions"), LINKS);
  assert.deepEqual(positionMissionActions(d.rows.get("drone")).map((a) => a.id), ["mission-new", "mission-open-rbd:r1", "mission-redundancy"]);
  // No RBD yet, but positions inside: Add a mission builds its RBD from them.
  const arm = positionMissionActions(d.rows.get("arm"));
  assert.deepEqual(arm.map((a) => a.id), ["mission-new", "mission-build-rbd", "mission-redundancy"]);
  assert.equal(arm[0].disabled, undefined);
  // A leaf with no RBD: nothing to build from, so it says what to do.
  const [leaf] = positionMissionActions(d.rows.get("battery"));
  assert.equal(leaf.disabled, true);
  assert.match(leaf.reason, /Give it a life model/);
  // With a model in use, a leaf gets Add a mission: one block, its own model.
  const modelled = graftMissions(buildDisplay(DATA, "positions"), LINKS, ["battery"]);
  assert.deepEqual(positionMissionActions(modelled.rows.get("battery")).map((a) => [a.id, !!a.disabled]),
    [["mission-new", false], ["mission-build-rbd", false]]);
  // A leaf with only a repairable RBD can't fly one.
  const rep = graftMissions(buildDisplay(DATA, "positions"), [{ ...LINKS[1], rbd: { ...RBD, repairable: true } }]);
  const [add] = positionMissionActions(rep.rows.get("gimbal"));
  assert.equal(add.disabled, true);
  // A leaf with a non-repairable RBD starts from a copy of it.
  assert.equal(positionMissionActions(d.rows.get("gimbal"))[0].id, "mission-new");
  // View only: greyed with the reason.
  assert.equal(positionMissionActions(d.rows.get("drone"), { viewOnly: "View only." })[0].disabled, true);
});

test("a mission's own RBD hangs its one mission under the position, and isn't offered to open as the position's", () => {
  const own = { position_id: "arm", link_id: null, in_use: false,
    rbd: { ...RBD, id: "r9", name: "Arm — Lift", mission_rbd: true },
    missions: [{ id: "mission", name: "Lift", phases: 0, phase_names: [], duration: 0, unit: "Hours" }] };
  const d = graftMissions(buildDisplay(DATA, "positions"), [...LINKS, own]);
  const arm = d.rows.get("arm");
  assert.equal(arm.kids[0], missionKey("r9", "mission"));
  assert.equal(rollupText(arm, true), "1 mission");
  assert.deepEqual(positionMissionActions(arm).map((a) => a.id), ["mission-new", "mission-build-rbd", "mission-redundancy"]);
  const acts = missionRowActions(d.rows.get(missionKey("r9", "mission")));
  assert.equal(acts.find((a) => a.id === "mission-rbd").label, "Open its RBD");
});

test("each block's state in a phase: working by default, standby or not needed, one at a time", () => {
  let phase = { name: "Cruise", not_needed: ["c"], standby: [] };
  assert.equal(blockState(phase, "a"), "working");
  assert.equal(blockState(phase, "c"), "off");
  phase = { ...phase, ...withBlockState(phase, "c", "standby") };
  assert.deepEqual([phase.standby, phase.not_needed], [["c"], []]);
  assert.equal(blockState(phase, "c"), "standby");
  phase = { ...phase, ...withBlockState(phase, "c", "working") };
  assert.deepEqual([phase.standby, phase.not_needed], [[], []]);
  assert.deepEqual(BLOCK_STATES.map((x) => x.label), ["Working", "Standby", "Not needed"]);
  assert.deepEqual([...fadedIn({ not_needed: ["a"], standby: ["b"] })], ["a", "b"]);
  // Saved: blocks no longer in the RBD dropped; a block in both lists is not needed.
  const { phases } = cleanPhases([editablePhase({ name: "A", duration: 1, standby: ["b", "gone", "c"], not_needed: ["c"] })],
    { blocks: [{ id: "b" }, { id: "c" }] });
  assert.deepEqual(phases[0], { name: "A", duration: 1, not_needed: ["c"], standby: ["b"] });
  assert.equal(phaseLine({ standby: ["b"] }, { blocks: [{ id: "b", label: "Pump B" }] }), "Every block working or standing by · Pump B on standby");
});

const ROWS = [
  { name: "Radial load", role: "use", unit: "lbf", diagram: null, blocks: [
    { id: "i", label: "Input bearing", key: "F_R", own: null, default: null },
    { id: "o", label: "Output bearing", key: "F_R", own: null, default: null }] },
  { name: "Operating speed", role: "use", unit: "rpm", diagram: 1800, blocks: [
    { id: "i", label: "Input bearing", key: "n", own: null, default: null },
    { id: "o", label: "Output bearing", key: "n", own: 900, default: null }] },
  { name: "Bearing operating temperature", role: "environment", unit: "°C", diagram: null, blocks: [
    { id: "i", label: "Input bearing", key: "T_O", own: null, default: 60 }] },
];

test("a value set once for the phase reaches every block; a block can override it", () => {
  let phase = withValue({ name: "Climb" }, "Radial load", "1000");
  phase = withBlockValue(phase, "o", "F_R", "1500");
  const [radial, speed, temp] = phaseCovariates(ROWS, phase);
  assert.deepEqual(radial.blocks.map((b) => [b.used, b.source]), [["1000", "phase"], ["1500", "override"]]);
  assert.deepEqual(radial.missing, []);
  assert.deepEqual(speed.blocks.map((b) => [b.used, b.source]), [[1800, "diagram"], [900, "own"]]);
  assert.deepEqual(temp.blocks.map((b) => b.source), ["default"]);
  assert.equal(feedsText(radial), "Feeds Input bearing and Output bearing (2 blocks)");
});

test("a missing value says which blocks need it", () => {
  const rows = phaseCovariates(ROWS, { name: "Cruise" });
  assert.deepEqual(rows[0].missing, ["Input bearing", "Output bearing"]);
  assert.deepEqual(phaseNeeds(rows), ["Input bearing", "Output bearing"]);
  // Blank takes a value off again.
  const back = withBlockValue(withBlockValue({}, "o", "F_R", "5"), "o", "F_R", "");
  assert.deepEqual(back.block_values, {});
  assert.deepEqual(withValue({ values: { a: 1 } }, "a", " ").values, {});
});

test("phases are cleaned for saving, and moved", () => {
  const rows = [editablePhase({ name: " Take-off ", duration: "0.1", votes: { k1: "4" }, values: { "Air temp": "35", Site: "north" },
    block_values: { m3: { temp_C: "50" }, gone: { x: 1 } }, not_needed: ["cam", "gone"] }), editablePhase({ name: "", duration: "" })];
  const { phases, errors } = cleanPhases(rows, { blocks: [{ id: "cam" }, { id: "m3" }], votes: [{ id: "k1" }] });
  assert.deepEqual(phases[0], { name: "Take-off", duration: 0.1, not_needed: ["cam"], votes: { k1: 4 },
    values: { "Air temp": 35, Site: "north" }, block_values: { m3: { temp_C: 50 } } });
  assert.deepEqual(errors, ["Phase 2 needs a name.", "Phase 2 needs a duration of 0 or more."]);
  assert.deepEqual(movePhase(["a", "b", "c"], 0, 1), ["b", "a", "c"]);
  assert.deepEqual(movePhase(["a", "b"], 0, -1), ["a", "b"]);
  assert.equal(typed(" 12 "), 12);
  assert.equal(typed(""), null);
});

test("a phase's line and the answer in words", () => {
  const blocks = [{ id: "cam", label: "Camera" }];
  const votes = [{ id: "k1", label: "Motors", inputs: 6 }];
  assert.equal(phaseLine({ not_needed: ["cam"], votes: { k1: 4 }, values: { a: 1 } }, { blocks, votes }),
    "Doesn't need Camera · Motors: 4 of 6 · 1 value set");
  assert.equal(answerText({ reliability: 0.95, riskiest: { name: "Survey" }, phases: [{}, {}] }),
    "The mission completes with probability 95.0%. Survey is the riskiest phase.");
  assert.equal(answerText({ reliability: null, through: { phase: "Take-off", reliability: 0.999 },
    phases: [{ name: "Take-off" }, { name: "Cruise", waiting: true }] }),
  "Worked out to the end of Take-off (99.90% still going); Cruise needs values first.");
  assert.equal(phaseCompletes({ conditional_failure: 0.25 }), 0.75);
  assert.equal(phaseCompletes({ waiting: true }), null);
});

test("a result resting on placeholders says so first, with the figure without them", () => {
  const result = { reliability: 0.7366, blocks: 5, riskiest: { name: "Run" }, phases: [{}, {}],
    placeholders: [{ id: "b", label: "Battery" }, { id: "c", label: "Control panel" }, { id: "f", label: "Fuel system" }],
    without_placeholders: { reliability: 0.99431 } };
  const ph = placeholderWarning(result);
  assert.equal(ph.count, "3 of 5 blocks have no model");
  assert.equal(ph.list, "Battery, Control panel and Fuel system");
  assert.equal(ph.without, 0.99431);
  assert.equal(answerText(result),
    "Not a real figure yet: 3 of 5 blocks have no model. With a placeholder standing in for each, the mission completes with probability 73.7%.");
  // A list row's kept result: labels and the number.
  const kept = { reliability: 0.7366, placeholders: ["Battery"], without_placeholders: 0.99431 };
  assert.equal(placeholderWarning(kept).count, "1 block has no model");
  assert.equal(placeholderTitle(kept), "Not a real figure: Battery has no model, so a placeholder stands in. Without it: 99.43%.");
  // Nothing to say with a model on every block, or once they're all left out.
  assert.equal(placeholderWarning({ reliability: 0.95, placeholders: [], blocks: 2 }), null);
  assert.equal(placeholderTitle({ reliability: 0.95 }), "");
  // No block with a model: no figure without them.
  const none = placeholderWarning({ reliability: 0.8, blocks: 2, placeholders: [{ id: "a", label: "A" }, { id: "b", label: "B" }], without_placeholders: null });
  assert.equal(none.count, "none of the 2 blocks has a model");
  assert.equal(none.without, null);
});

test("leaving placeholders out marks them Not needed in every phase, whatever they were", () => {
  const rows = [{ key: "1", name: "Start", standby: ["b"], not_needed: [] }, { key: "2", name: "Run", standby: [], not_needed: ["c"] }];
  const out = leaveOut(rows, ["b", "c"]);
  assert.deepEqual(out.map((r) => [r.standby, r.not_needed]), [[[], ["b", "c"]], [[], ["b", "c"]]]);
  assert.equal(out[0].name, "Start");
  assert.deepEqual(rows[0].standby, ["b"]); // the rows given are left as they were
});

test("a mission's phases hang under it in the tree, in order", () => {
  const d = graftMissions(buildDisplay(DATA, "positions"), LINKS);
  const m1 = d.rows.get(missionKey("r1", "m1"));
  assert.deepEqual(m1.kids, [phaseKey("r1", "m1", 0), phaseKey("r1", "m1", 1), phaseKey("r1", "m1", 2)]);
  const p2 = d.rows.get(phaseKey("r1", "m1", 1));
  assert.equal(p2.ref.name, "Transit");
  assert.equal(p2.parent, m1.key);
  assert.equal(p2.depth, m1.depth + 1);
  assert.equal(p2.ref.position_id, "drone");
  assert.ok(isPhaseRow(p2) && isMissionRow(p2) && !isPhaseRow(m1));
  assert.equal(phaseOfText(p2.ref.phase), "Phase 2 of 3");
  // Each phase's own length, in its mission's unit; together they're the mission's.
  const lengths = m1.kids.map((k) => phaseLengthText(d.rows.get(k).ref.phase, m1.ref.mission.unit));
  assert.deepEqual(lengths, ["0.25 hours", "1 hour", "0.25 hours"]);
  assert.equal(m1.kids.reduce((n, k) => n + d.rows.get(k).ref.phase.duration, 0), m1.ref.mission.duration);
  // A read with no lengths (an older server): the cell is left blank, never a made-up 0.
  const old = graftMissions(buildDisplay(DATA, "positions"), [{ ...LINKS[0], missions: [{ ...LINKS[0].missions[0], phase_durations: undefined }] }]);
  assert.equal(old.rows.get(phaseKey("r1", "m1", 0)).ref.phase.duration, null);
  assert.equal(phaseLengthText(old.rows.get(phaseKey("r1", "m1", 0)).ref.phase, "Hours"), "");
  assert.deepEqual(d.rows.get(missionKey("r1", "m2")).kids, []); // no phases yet
  // The position's counts are its missions', not their phases.
  assert.equal(rollupText(d.rows.get("drone"), true), "2 missions");
});

test("menus: a mission's starts with Add a phase; a phase's opens, moves and deletes it", () => {
  const d = graftMissions(buildDisplay(DATA, "positions"), LINKS);
  const ids = (k, o) => missionRowActions(d.rows.get(k), o).map((a) => a.id || "—");
  assert.deepEqual(ids(missionKey("r1", "m1")), ["mission-phase-add", "—", "mission-open", "mission-rbd", "mission-delete"]);
  const full = { ...d.rows.get(missionKey("r1", "m1")), ref: { ...d.rows.get(missionKey("r1", "m1")).ref, mission: { phases: MAX_PHASES } } };
  assert.equal(missionRowActions(full)[0].disabled, true);
  assert.deepEqual(ids(phaseKey("r1", "m1", 1)), ["mission-phase-open", "mission-phase-earlier", "mission-phase-later", "mission-phase-delete"]);
  const first = missionRowActions(d.rows.get(phaseKey("r1", "m1", 0)));
  const last = missionRowActions(d.rows.get(phaseKey("r1", "m1", 2)));
  assert.deepEqual(first.map((a) => a.label), ["Open…", "Move earlier", "Move later", "Delete…"]);
  assert.equal(first[1].disabled, true);
  assert.equal(first[2].disabled, undefined);
  assert.equal(last[2].disabled, true);
  assert.equal(last.at(-1).danger, true);
  // View only: the changes greyed with the reason; Open… stays.
  const vo = missionRowActions(d.rows.get(phaseKey("r1", "m1", 1)), { viewOnly: "View only." });
  assert.deepEqual(vo.map((a) => !!a.disabled), [false, true, true, true]);
  assert.equal(missionRowActions(d.rows.get(missionKey("r1", "m1")), { viewOnly: "View only." })[0].reason, "View only.");
  // A position's menu starts with Add a mission.
  assert.equal(positionMissionActions(d.rows.get("drone"))[0].label, "Add a mission");
});

test("phases changed from the tree: added at the end, moved, taken out, saved as the pane saves them", () => {
  const detail = {
    mission: { phases: [{ name: "Take-off", duration: 0.1 }, { name: "Phase 2", duration: 1 }, { name: "Landing", duration: 0.2, not_needed: ["b1"] }] },
    blocks: [{ id: "b1", label: "Camera" }], votes: [],
  };
  const added = changedPhases(detail, withNewPhase);
  assert.deepEqual(added.errors, []);
  // "Phase 4", the next free name; a duration of 0 until it's given one.
  assert.deepEqual(added.phases.at(-1), { name: "Phase 4", duration: 0 });
  assert.equal(added.phases.length, 4);
  assert.deepEqual(changedPhases(detail, (rows) => movePhase(rows, 2, -1)).phases.map((p) => p.name), ["Take-off", "Landing", "Phase 2"]);
  const gone = changedPhases(detail, (rows) => withoutPhase(rows, 0)).phases;
  assert.deepEqual(gone.map((p) => p.name), ["Phase 2", "Landing"]);
  assert.deepEqual(gone[1].not_needed, ["b1"]); // what else a phase has is kept
  // A new phase's name skips one already taken.
  assert.equal(newPhase(1, [{ name: "phase 2" }]).name, "Phase 3");
  assert.equal(newPhase(0).name, "Phase 1");
});

test("of two reads out at once, only the one asked for last is used", () => {
  const asked = latestOnly();
  const first = asked();
  assert.equal(first(), true); // alone, its answer is used
  // A mission is saved (one read), then its result is worked out (another): the first read's
  // answer, whenever it comes, is dropped; the second's is the table's.
  const second = asked();
  assert.equal(first(), false);
  assert.equal(second(), true);
  // Each table has its own count.
  assert.equal(latestOnly()()(), true);
  assert.equal(second(), true);
});

test("a leaf whose model can't be a block says so; a chance past 99.99% isn't a string of nines", async () => {
  const { graftMissions: graft, rollupText: roll, pct: p, phaseLine: line, positionMissionActions: acts } = await import("./explorerMissions.js");
  const display = { rows: new Map([["a", { key: "a", type: "pos", parent: null, kids: [], depth: 0, ref: { name: "Pump 1" } }]]) };
  const d = graft(display, [], [], ["a"]);
  assert.equal(roll(d.rows.get("a"), true), "No missions yet · its model can't be a block");
  assert.match(acts(d.rows.get("a"))[0].reason, /can't be a block/);
  assert.equal(p(0.99999985), "> 99.99%");
  assert.equal(p(1.5e-7), "< 0.01%");
  assert.equal(p(1), "100%");
  assert.equal(p(0.9), "90.0%");
  assert.equal(line({}, { blocks: [] }), "Every block in use, wired as in the RBD");
});
