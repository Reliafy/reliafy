import { test } from "node:test";
import assert from "node:assert/strict";
import { buildDisplay } from "./assetTree.js";
import {
  answerText, cleanPhases, completesText, editablePhase, feedsText, graftMissions, isMissionRow, lengthText, missionKey,
  missionParam, movePhase, parseMissionParam, phaseCompletes, phaseCovariates, phaseLine, phaseNeeds, phasesText,
  positionMissionActions, rollupText, typed, withBlockValue, withValue,
} from "./explorerMissions.js";

const DATA = {
  positions: [
    { id: "drone", name: "Survey drone", parent_id: null },
    { id: "gimbal", name: "Gimbal", parent_id: "drone" },
    { id: "battery", name: "Battery", parent_id: "drone" },
  ],
  locations: [], spares: [], unhomed: [],
};
const RBD = { id: "r1", name: "Drone RBD", unit: "Hours", repairable: false, network: false };
const LINKS = [
  { position_id: "drone", link_id: "l1", in_use: true, rbd: RBD, missions: [
    { id: "m1", name: "Corridor inspection", phases: 3, phase_names: ["Take-off", "Transit", "Landing"], duration: 1.5, unit: "Hours",
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
  assert.equal(rollupText(d.rows.get("battery"), true), "No RBD yet · Build from what's inside…");
  assert.equal(rollupText(d.rows.get("battery"), false), "No RBD yet");
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
  assert.equal(completesText(m1), "98.2%");
  assert.equal(completesText(m2), "—");
  assert.equal(completesText({ result: { reliability: null, through: { phase: "Take-off", reliability: 0.999 } } }),
    "Waiting · 99.90% to Take-off");
});

test("a position's actions: add a mission to its RBD, or build one", () => {
  const d = graftMissions(buildDisplay(DATA, "positions"), LINKS);
  assert.deepEqual(positionMissionActions(d.rows.get("drone")).map((a) => a.id), ["mission-add:r1", "mission-open-rbd:r1"]);
  assert.deepEqual(positionMissionActions(d.rows.get("battery")).map((a) => a.id), ["mission-build-rbd"]);
  const rep = graftMissions(buildDisplay(DATA, "positions"), [{ ...LINKS[1], rbd: { ...RBD, repairable: true } }]);
  const [add] = positionMissionActions(rep.rows.get("gimbal"));
  assert.equal(add.disabled, true);
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
