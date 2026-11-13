// Run with: node --test src/
// The shared Data step (ColumnMapper) in the other fit flows: repairable,
// accelerated life, condition and life (both tables) and degradation. Each
// shows only the selectors its fit takes, and the same mapping sends the same
// fit request as the flow's own mapper did before.
import { test } from "node:test";
import assert from "node:assert/strict";
import { FAMILY_SHEETS as S } from "./dataStepFamilySheets.js";
import { columnFacts } from "./lifeData.js";
import {
  RECURRENT_KEYS, RECURRENT_ROWS, guessRecurrentMapping, recurrentFields, recurrentIssues,
} from "./recurrentMapping.js";
import { ALT_ROWS, altDataIssues, altFields, altMapping, altStressIssues, guessAltColumns } from "./altGuess.js";
import {
  JOINT_LIFE_KEYS, JOINT_LIFE_ROWS, JOINT_READ_KEYS, JOINT_READ_ROWS, guessLifetimeColumns, guessReadingColumns,
  jointIssues, jointLifeMapping,
} from "./joint.js";
import {
  DEGRADATION_KEYS, DEGRADATION_ROWS, degradationIssues, guessDegradationColumns, guessDirection, thresholdProblem,
} from "./degradation.js";

// What picking each shown selector by hand builds: the shared component sets
// mapping[key] for each row's key (ColumnMapper with a flow's ``keys``).
const byHand = (empty, from, rows, keys, extra = []) => {
  const m = { ...empty };
  const ks = rows.flatMap((r) => (r === "x" && extra.includes("range") ? ["x", "xl", "xr"] : [keys[r] || r]));
  for (const k of ks) if (from[k]) m[k] = from[k];
  return m;
};
const described = (sheet) => {
  const facts = columnFacts(sheet);
  return sheet.columns.map((name) => ({ name, ...facts[name] }));
};

test("repairable: i first, no range, the failure mode sent as mode; same request as before", () => {
  assert.deepEqual(RECURRENT_ROWS, ["i", "x", "c", "n", "tl", "tr", "e"]);
  const before = {
    w15: [["i", "truck"], ["x", "pump_failure_hours"], ["tr", "observed_to_hours"]],
    w16: [["i", "compressor"], ["x", "failure_hours"], ["tr", "records_end_hours"]],
    w17: [["i", "unit"], ["x", "failure_hours"], ["tr", "trial_end_hours"], ["mode", "failure_mode"]],
  };
  for (const [name, fields] of Object.entries(before)) {
    const sheet = S[name];
    const g = guessRecurrentMapping(sheet.columns, { dtypes: sheet.dtypes, preview: sheet.preview });
    assert.deepEqual(recurrentFields(g), fields, name);
    const m = byHand({ i: "", x: "", c: "", n: "", tl: "", tr: "", mode: "" }, g, RECURRENT_ROWS, RECURRENT_KEYS);
    assert.deepEqual(recurrentFields(m), fields, `${name} by hand`);
    assert.deepEqual(recurrentIssues(g), [], name);
  }
  // No end of record: said beside tr, without stopping Next.
  const g = guessRecurrentMapping(S.w16.columns, { dtypes: S.w16.dtypes });
  const open = recurrentIssues({ ...g, tr: "" });
  assert.equal(open.length, 1);
  assert.equal(open[0].row, "tr");
  assert.equal(open[0].note, true);
  assert.deepEqual(recurrentIssues({ ...g, x: g.i }).map((i) => i.row), ["x"]);
});

test("accelerated life: the life selectors only, stresses on the Model step; same request as before", () => {
  assert.deepEqual(ALT_ROWS, ["x", "c", "n", "tl", "tr"]);
  const g = guessAltColumns(S.w18, { nStress: 1, lifeModel: "arrhenius" });
  const map = { x: g.x, xl: "", xr: "", c: g.c, n: "", tl: "", tr: "" };
  // The old flow posted { x, c, n } and s1 with its unit.
  const before = [["x", "hours"], ["c", "censored"], ["s1", "temp_K"], ["s1_unit", "K"]];
  assert.deepEqual(altFields(altMapping(map), g.stress), before);
  assert.deepEqual(altFields(altMapping(byHand({}, map, ALT_ROWS, {}, ["range"])), g.stress), before);
  assert.deepEqual(altDataIssues(map), []);
  assert.deepEqual(altStressIssues(g.stress, 1, "arrhenius", map), []);
  // A stress column already given a role in the reading, or a temperature with no unit, is said beside the stress.
  assert.match(altStressIssues([{ col: "hours", unit: "K" }], 1, "arrhenius", map)[0].text, /has a role in the dataset.s reading/);
  assert.match(altStressIssues([{ col: "temp_C", unit: "" }], 1, "arrhenius", map)[0].text, /temperature's unit/);
  // The range comes with x on the same screen.
  assert.deepEqual(altMapping({ ...map, x: "", xl: "a", xr: "b" }), { xl: "a", xr: "b", c: "censored" });
});

test("condition and life: i, x (with its range), c, tl for the lifetimes; i, x, m for the readings; same request", () => {
  assert.deepEqual(JOINT_LIFE_ROWS, ["i", "x", "c", "tl"]);
  assert.deepEqual(JOINT_READ_ROWS, ["i", "x", "m"]);
  const before = {
    w03life: { id: "pump", x: "age_days", c: "running" },
    w24life: { id: "bearing", x: "age_days", c: "running" },
  };
  for (const [name, mapping] of Object.entries(before)) {
    const g = guessLifetimeColumns(described(S[name]));
    const map = { id: g.id, x: g.x, xl: "", xr: "", c: g.c, tl: "" };
    assert.deepEqual(jointLifeMapping(map), mapping, name);
    assert.deepEqual(jointLifeMapping(byHand({}, map, JOINT_LIFE_ROWS, JOINT_LIFE_KEYS, ["range"])), mapping, name);
  }
  for (const name of ["w03reads", "w24reads"]) {
    const r = guessReadingColumns(described(S[name]));
    assert.deepEqual(r, { id: name.startsWith("w03") ? "pump" : "bearing", age: "age_days", value: "vibration_mm_s" }, name);
    assert.deepEqual(byHand({ id: "", age: "", value: "" }, r, JOINT_READ_ROWS, JOINT_READ_KEYS), r, name);
  }
  // A range in place of x, as the old "failures found at inspections" box sent it; never both.
  assert.deepEqual(jointLifeMapping({ id: "u", x: "", xl: "a", xr: "b", c: "c", tl: "" }), { id: "u", xl: "a", xr: "b", c: "c" });
  const both = jointIssues({ id: "u", x: "t", xl: "a", xr: "b", c: "c" }, { id: "u", age: "t", value: "v" });
  assert.deepEqual(both.map((i) => [i.table, i.row]), [["life", "x"]]);
  assert.deepEqual(jointIssues({ id: "", x: "", c: "" }, { id: "", age: "", value: "" }).map((i) => `${i.table}:${i.row}`),
    ["life:i", "life:x", "life:c", "reads:i", "reads:x", "reads:m"]);
});

test("degradation: i, x and m only, m sent as y; the threshold is the Model step's", () => {
  assert.deepEqual(DEGRADATION_ROWS, ["i", "x", "m"]);
  const g = guessDegradationColumns(S.w19.columns);
  assert.deepEqual(g, { i: "pad", x: "km", y: "thickness_mm" });
  assert.deepEqual(byHand({ i: "", x: "", y: "" }, g, DEGRADATION_ROWS, DEGRADATION_KEYS), g);
  assert.deepEqual(degradationIssues(S.w19, g), []);
  // Pads wear thinner: m falls to the threshold.
  assert.equal(guessDirection(S.w19, g), "falls");
  assert.equal(thresholdProblem(S.w19, g, "3", "falls", "mm"), null);
  assert.match(thresholdProblem(S.w19, g, "3", "rises", "mm"), /already at or above 3 mm/);
  assert.match(thresholdProblem(S.w19, g, "", "falls"), /Enter the value/);
  assert.deepEqual(degradationIssues(S.w19, { ...g, i: "km" }).map((i) => i.row), ["m"]);
});
