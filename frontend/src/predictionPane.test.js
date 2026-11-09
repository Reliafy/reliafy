import { test } from "node:test";
import assert from "node:assert/strict";
import {
  branchPositions, leftOutKeys, lineChange, lineKey, lineMenu, lineMode, mergeLines, missionHours, noPartsText,
  predictionKey, predictionResult, predictionTitle, quantityTyped, removeQuestion, resultLines,
} from "./predictionPane.js";

test("the heading: add, or refresh the one there", () => {
  assert.equal(predictionTitle(), "Add a prediction");
  assert.equal(predictionTitle({ id: "l1" }), "Refresh the prediction");
});

test("the mission time typed", () => {
  assert.equal(missionHours(""), null);
  assert.equal(missionHours("0"), null);
  assert.equal(missionHours("abc"), null);
  assert.equal(missionHours(" 500 "), 500);
  assert.equal(missionHours(12.5), 12.5);
});

test("a change is a change of what's sent; a blank typed and cleared is none", () => {
  const lines = [{ reference: "C-1", record: { id: "r1" }, quality_factor: "" }, { reference: "AF", excluded: true }];
  const opened = predictionKey({ environment: "GB", mission: "", lines });
  assert.equal(predictionKey({ environment: "GB", mission: " ", lines: lines.map((l) => ({ ...l })) }), opened);
  assert.notEqual(predictionKey({ environment: "GF", mission: "", lines }), opened);
  assert.notEqual(predictionKey({ environment: "GB", mission: "100", lines }), opened);
  assert.notEqual(predictionKey({ environment: "GB", lines: [{ ...lines[0], record: null }, lines[1]] }), opened);
  assert.notEqual(predictionKey({ environment: "GB", lines: [lines[0], { reference: "AF", excluded: false }] }), opened);
});

test("what a line uses", () => {
  assert.equal(lineMode({ excluded: true, record: { id: "r" } }), "excluded");
  assert.equal(lineMode({ record: { id: "r" }, rate_per_million_hours: "3" }), "type");
  assert.equal(lineMode({ rate_per_million_hours: "3" }), "rate");
  assert.equal(lineMode({ rate_mode: true, rate_per_million_hours: "" }), "rate");
  assert.equal(lineMode({}), "type");
});

test("the result in the panel's words", () => {
  assert.equal(predictionResult(null), null);
  const r = {
    failure_rate_per_million_hours: 12.345, mtbf_hours: 81004.5, mission_time_hours: 500, reliability_at_mission: 0.99385,
    environment: { code: "GB", name: "Ground, benign" }, counts: { lines: 4, assigned: 2 },
    excluded: [{ name: "Airframe", quantity: 1 }], unassigned: [{ name: "Propeller", quantity: 4 }],
  };
  const out = predictionResult(r, "500");
  assert.equal(out.rate, "12.3");
  assert.equal(out.mtbf, "81,000");
  assert.equal(out.reliability, "99.39%");
  assert.equal(out.mission, "500");
  assert.equal(out.counted, "2 of 4 lines counted");
  assert.equal(out.environment, "Ground, benign (GB)");
  assert.deepEqual(out.notElectronic, ["Airframe"]);
  assert.deepEqual(out.noType, ["Propeller ×4"]);
  // No mission typed: no reliability (the server's default mission isn't the user's).
  assert.equal(predictionResult(r, "").reliability, null);
  // A mission typed but the result still for the last one: not shown until it catches up.
  assert.equal(predictionResult(r, "800").reliability, null);
  // Nothing counted yet: no rate, no MTBF.
  const none = predictionResult({ failure_rate_per_million_hours: 0, mtbf_hours: null, counts: { lines: 1, assigned: 0 } });
  assert.equal(none.rate, null);
  assert.equal(none.mtbf, null);
  assert.equal(none.counted, "0 of 1 line counted");
});

test("a change from the shared part-type controls as the line's fields", () => {
  assert.deepEqual(lineChange({ record: { id: "r1", name: "Cap" } }), { record: { id: "r1", name: "Cap" }, record_id: "r1" });
  assert.deepEqual(lineChange({ record: null, rateMode: true }), { record: null, record_id: null, rate_mode: true });
  assert.deepEqual(lineChange({ rate: "0.5", rateMode: true }), { rate_per_million_hours: "0.5", rate_mode: true });
  assert.deepEqual(lineChange({ excluded: true, record: null, rate: "", rateMode: false }),
    { excluded: true, record: null, record_id: null, rate_per_million_hours: "", rate_mode: false });
  assert.deepEqual(lineChange({}), {});
});

test("lines left out of this prediction: by parts-list entry, else part number; a change", () => {
  const lines = [{ listing_id: "e1", reference: "C-1" }, { listing_id: "e2", reference: "U-7", left_out: true },
    { reference: "BOM-3", left_out: true }];
  assert.deepEqual(leftOutKeys(lines), ["e2", "BOM-3"]);
  assert.equal(lineKey({ part_id: "p" }), "p");
  const opened = predictionKey({ lines });
  assert.notEqual(predictionKey({ lines: [lines[0], { ...lines[1], left_out: false }, lines[2]] }), opened);
});

test("the result's lines skip the ones left out", () => {
  const lines = [{ name: "A" }, { name: "B", left_out: true }, { name: "C" }];
  const got = resultLines(lines, { lines: [{ name: "A" }, { name: "C" }] });
  assert.deepEqual(got.map((r) => r && r.name), ["A", null, "C"]);
  assert.deepEqual(resultLines(lines, null), [null, null, null]);
});

test("the parts lists read again keep each line's choices; a new line is named", () => {
  const old = [{ listing_id: "e1", name: "Cap", quantity: 2, record: { id: "r1", name: "Capacitor" }, left_out: true }];
  const fresh = [
    { listing_id: "e1", name: "Cap", quantity: 5, record_id: "r1", position: { id: "p1", name: "Power" }, left_out: true },
    { listing_id: "e9", name: "Opto", quantity: 1, record_id: "r2", position: { id: "p2", name: "Board" } },
  ];
  const { lines, added } = mergeLines(old, fresh, { lines: [{ part_type: "Opto-isolator" }] });
  assert.deepEqual(added, ["e9"]);
  assert.equal(lines[0].quantity, 5);
  assert.equal(lines[0].record.name, "Capacitor");
  assert.equal(lines[0].left_out, true);
  assert.deepEqual(lines[1].record, { id: "r2", name: "Opto-isolator" });
  // A line taken off its list goes.
  assert.equal(mergeLines(old, []).lines.length, 0);
});

test("where a part can go: the branch, each with what's on its list", () => {
  const branch = [{ id: "p1", name: "Power", depth: 0 }, { id: "p2", name: "Board", depth: 1 }];
  const lines = [{ part_id: "a", role: "replacement", position: { id: "p2" } }];
  const got = branchPositions(branch, lines);
  assert.deepEqual(got[0].parts_list, []);
  assert.deepEqual(got[1].parts_list, [{ part: { id: "a" }, role: "replacement" }]);
});

test("the words: empty state and the removal question", () => {
  assert.equal(noPartsText("Power"), "No parts listed on Power or inside it.");
  assert.equal(removeQuestion({ name: "Battery pack 6S 10 Ah", position: { name: "Power" } }),
    "Remove Battery pack 6S 10 Ah from Power’s parts list? It also leaves the BOM and the LSA. The part itself stays in your parts.");
});

test("a line's menu: leave out or put back; a bill of materials line can't be changed on a list", () => {
  const ids = (items) => items.filter((it) => !it.separator).map((it) => `${it.id}${it.disabled ? "!" : ""}`);
  assert.deepEqual(ids(lineMenu({ listing_id: "e1" })), ["quantity", "out", "remove"]);
  assert.deepEqual(ids(lineMenu({ listing_id: "e1", left_out: true })), ["quantity", "back", "remove"]);
  assert.deepEqual(ids(lineMenu({ reference: "BOM-1" })), ["quantity!", "out", "remove!"]);
  assert.equal(lineMenu({}).find((it) => it.id === "remove").danger, true);
});

test("a quantity typed: more than 0 and changed, else nothing", () => {
  assert.equal(quantityTyped("3", 2), 3);
  assert.equal(quantityTyped(" 2.5 ", 1), 2.5);
  assert.equal(quantityTyped("2", 2), null);
  assert.equal(quantityTyped("0", 2), null);
  assert.equal(quantityTyped("", 2), null);
  assert.equal(quantityTyped("abc", 2), null);
});

test("the result names what was left out of this prediction", () => {
  const out = predictionResult({ failure_rate_per_million_hours: 2, left_out: [{ name: "Battery", quantity: 2 }] });
  assert.deepEqual(out.leftOut, ["Battery ×2"]);
});
