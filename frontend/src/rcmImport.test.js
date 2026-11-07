import { test } from "node:test";
import assert from "node:assert/strict";
import { EXPORT_HEADER, FMEA_HEADER, causedBy, exportFilename, importSummary, isCsvFile, positionRcmCsv, positionRcmRows } from "./rcmImport.js";

const F = FMEA_HEADER.length;
// A row's cells by column name.
const cells = (row, ...names) => names.map((h) => row[EXPORT_HEADER.indexOf(h)]);
const HEAD = ["Position", "Function", "Performance standard", "Standard working", "Functional failure", "Caused by (below)", "Failure mode", "Effects", "Consequence"];
const TAIL = ["Decision", "Run-to-failure basis", "Task", "Interval", "Interval unit", "Evidence check", "Failure mode notes"];

test("the preview's counts in words: what it adds, and what's there already", () => {
  assert.deepEqual(importSummary({ functions: 2, failures: 3, modes: 4, tasks: 1, functions_existing: 0 }), {
    adds: ["2 functions", "3 functional failures", "4 failure modes", "1 task"], there: [], nothing: false,
  });
  const again = importSummary({ functions: 0, failures: 0, modes: 0, tasks: 0, functions_existing: 2,
    failures_existing: 3, modes_existing: 1 });
  assert.deepEqual(again, { adds: [], there: ["2 functions", "3 functional failures", "1 failure mode"], nothing: true });
  assert.equal(importSummary(null).nothing, true);
  assert.equal(importSummary({ modes: 1200 }).adds[0], "1,200 failure modes");
});

test("CSV files skip the sheet step", () => {
  assert.equal(isCsvFile({ name: "fmea.CSV" }), true);
  assert.equal(isCsvFile({ name: "fmea", type: "text/csv" }), true);
  assert.equal(isCsvFile({ name: "fmea.xlsx" }), false);
  assert.equal(isCsvFile(null), false);
});

const WS = {
  positions: [
    {
      id: "plant", name: "Plant", depth: 0, unassigned: [], functions: [],
    },
    {
      id: "c2", name: "Conveyor C-2", depth: 1,
      unassigned: [{ id: "u", text: "Motor hums", consequence: null, decision: null }],
      functions: [
        {
          id: "f1", text: "Move grain", standard: "40 t/h", standard_basis: "## Rate\n\n40 t/h = 10 t over 15 min",
          failures: [
            {
              id: "x1", text: "Moves no grain",
              causes: [
                { id: "c1", text: "No torque", position: { id: "d", name: "Conveyor drive" }, inside: true },
                { id: "c2", text: "Gone", position: { id: "g", name: "Elsewhere" }, inside: false },
              ],
              modes: [
                { id: "m1", text: "Belt torn", effects: "Line stops", consequence: "operational", notes: "Severity 7",
                  decision: { outcome: "on_condition", task: "Walk the belt", interval: 1, interval_unit: "weeks",
                              status: "unevidenced" } },
                { id: "m2", text: "=Bearing seizes", consequence: "non_operational",
                  decision: { outcome: "rtf", rtf_basis: "random", task: "Replace when it fails", status: "contradicted" } },
              ],
            },
            { id: "x2", text: "Moves too little", modes: [] },
          ],
        },
        { id: "f2", text: "Stop on the lanyard", standard: "", failures: [] },
      ],
    },
  ],
};

test("a position's RCM as rows named as the import reads them", () => {
  const rows = positionRcmRows(WS);
  assert.deepEqual(rows[0], EXPORT_HEADER);
  assert.equal(rows.length, 6);
  assert.deepEqual(cells(rows[1], ...HEAD.slice(0, 7)), ["Plant › Conveyor C-2", "", "", "", "", "", "Motor hums"]);
  // The FME(C)A's columns sit between Consequence and Decision (blank here).
  assert.deepEqual(cells(rows[2], ...HEAD), ["Plant › Conveyor C-2", "Move grain", "40 t/h", "", "Moves no grain", "Conveyor drive › No torque", "Belt torn", "Line stops",
    "Operational"]);
  assert.deepEqual(cells(rows[2], ...TAIL), ["On-condition", "", "Walk the belt", 1, "weeks", "", "Severity 7"]);
  assert.deepEqual(cells(rows[2], ...FMEA_HEADER), FMEA_HEADER.map(() => ""));
  assert.equal(EXPORT_HEADER.indexOf("Decision"), EXPORT_HEADER.indexOf("Consequence") + F + 1);
  assert.deepEqual(cells(rows[3], "Consequence", ...TAIL.slice(0, 6)), ["Non-operational", "Run-to-failure", "random", "Replace when it fails", "", "",
    "Contradicted"]);
  assert.deepEqual(cells(rows[4], ...HEAD.slice(1, 7)), ["Move grain", "40 t/h", "", "Moves too little", "", ""]); // a failure with no modes
  assert.deepEqual(cells(rows[5], ...HEAD.slice(1, 7)), ["Stop on the lanyard", "", "", "", "", ""]); // a function with no failures
  assert.deepEqual(positionRcmRows(null), [EXPORT_HEADER]);
});

test("the causes below go in one cell, on every row of the failure, and a failure with only causes has its own row", () => {
  assert.equal(causedBy(null), "");
  assert.equal(causedBy({ causes: [
    { text: "No output", position: { name: "Salt chlorinator" }, inside: true },
    { text: "Cell worn", position: { name: "Chlorinator cell" }, inside: true },
    { text: "Moved out", position: { name: "Elsewhere" }, inside: false },
  ] }), "Salt chlorinator › No output; Chlorinator cell › Cell worn");
  const rows = positionRcmRows({ positions: [{ id: "p", name: "Pool", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Sanitise", failures: [{ id: "x", text: "Low chlorine", modes: [],
      causes: [{ text: "No output", position: { name: "Salt chlorinator" }, inside: true }] }] }] }] });
  assert.equal(rows.length, 2);
  assert.equal(rows[1][EXPORT_HEADER.indexOf("Caused by (below)")], "Salt chlorinator › No output");
  assert.equal(EXPORT_HEADER.indexOf("Caused by (below)"), EXPORT_HEADER.indexOf("Functional failure notes") + 1);
});

test("links count in the import's words", () => {
  assert.deepEqual(importSummary({ links: 2 }).adds, ["2 links between functional failures"]);
  assert.equal(importSummary({ links: 1 }).nothing, false);
  assert.deepEqual(importSummary({ links_existing: 1 }).there, ["1 link between functional failures"]);
});

test("the CSV keeps a formula-looking cell as text, and the file is named after the position", () => {
  const csv = positionRcmCsv(WS);
  assert.ok(csv.startsWith("Position,Function,Function notes,Performance standard,Standard notes,Standard working,Functional failure,"
    + "Functional failure notes,Caused by (below),Failure mode,"));
  assert.ok(csv.includes(",'=Bearing seizes,"));
  assert.equal(exportFilename("Conveyor C-2"), "Conveyor C-2 RCM.csv");
  assert.equal(exportFilename('Pump "A" / B'), "Pump A B RCM.csv");
  assert.equal(exportFilename(""), "Position RCM.csv");
});

test("the Standard working column stays blank: a function's notes hold the working, quoted with their line breaks", () => {
  const ws = { ...WS, positions: WS.positions.map((p) => ({ ...p, functions: p.functions.map((f) => ({ ...f, notes: f.standard_basis || "" })) })) };
  const rows = positionRcmRows(ws);
  const col = EXPORT_HEADER.indexOf("Standard working");
  assert.equal(col, EXPORT_HEADER.indexOf("Standard notes") + 1);
  assert.deepEqual(rows.map((r) => r[col]), ["Standard working", "", "", "", "", ""]);
  const notes = EXPORT_HEADER.indexOf("Function notes");
  assert.deepEqual(rows.map((r) => r[notes]), ["Function notes", "", "## Rate\n\n40 t/h = 10 t over 15 min", "", "", ""]);
  assert.ok(positionRcmCsv(ws).includes('"## Rate\n\n40 t/h = 10 t over 15 min"'));
});


test("a failure mode with several tasks is one row per task, the first carrying everything", () => {
  const rows = positionRcmRows({ positions: [{ id: "p", name: "Pool", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Keep the water balanced", standard: "pH 7.2-7.8", failures: [
      { id: "x", text: "pH above 7.8", modes: [
        { id: "m", text: "Acid under-dosed", effects: "pH climbs", consequence: "operational", notes: "",
          decision: { outcome: "on_condition", task: "Weekly pH check", interval: 1, interval_unit: "weeks", status: "unevidenced", task_id: "t1",
            tasks: [{ id: "t1", name: "Weekly pH check", text: "Weekly pH check", interval: 1, unit: "weeks", outcome: "on_condition", shared_with: 0 },
              { id: "t2", name: "Replace the acid pump", text: "Replace the acid pump", interval: 24, unit: "months", outcome: "fixed_interval", shared_with: 0 }] } },
      ] },
    ] },
  ] }] });
  assert.equal(rows.length, 3);
  assert.deepEqual(cells(rows[1], ...HEAD.slice(6), ...TAIL.slice(0, 5)), ["Acid under-dosed", "pH climbs", "Operational", "On-condition", "", "Weekly pH check", 1, "weeks"]);
  assert.deepEqual(cells(rows[2], ...HEAD, ...TAIL), ["Pool", "Keep the water balanced", "pH 7.2-7.8", "", "pH above 7.8", "", "Acid under-dosed", "",
    "", "Fixed-interval", "", "Replace the acid pump", 24, "months", "", ""]);
  assert.equal(rows[2].length, EXPORT_HEADER.length);
});

test("a combination of tasks is one row per member in its order, a redesign too, then tasks outside the decision", () => {
  const t = (id, name, interval, unit, outcome) => ({ id, name, text: name, interval, unit, outcome, shared_with: 0 });
  const rows = positionRcmRows({ positions: [{ id: "p", name: "Pump", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Pump water", failures: [{ id: "x", text: "No flow", modes: [
      { id: "m", text: "Bearing worn", consequence: "safety", notes: "",
        decision: { outcome: "on_condition", task: "Vibration check", interval: 1, interval_unit: "months", task_id: "t1", status: "partly",
          // The read lists tasks own first, then others in no member order: the export follows the members.
          tasks: [t("t1", "Vibration check", 1, "months", "on_condition"), t("t3", "Oil sample", 3, "months", "on_condition"),
            t("t2", "Replace the bearing", 24, "months", "fixed_interval")],
          outcomes: [
            { outcome: "on_condition", task: "Vibration check", interval: 1, interval_unit: "months", task_id: "t1" },
            { outcome: "fixed_interval", task: "Replace the bearing", interval: 24, interval_unit: "months", task_id: "t2" },
            { outcome: "redesign", task_id: null },
          ] } },
    ] }] },
  ] }] });
  // These rows are what backend/tests/test_maintenance_rcm_combination.py imports back.
  assert.deepEqual(rows.slice(1).map((r) => cells(r, "Failure mode", "Consequence", "Decision", "Task", "Interval", "Interval unit")), [
    ["Bearing worn", "Safety", "On-condition", "Vibration check", 1, "months"],
    ["Bearing worn", "", "Fixed-interval", "Replace the bearing", 24, "months"],
    ["Bearing worn", "", "Redesign", "", "", ""],
    ["Bearing worn", "", "On-condition", "Oil sample", 3, "months"],
  ]);
  assert.deepEqual(cells(rows[1], "Evidence check"), ["Partly evidenced"]);
  assert.deepEqual(importSummary({ modes: 1, tasks: 3, combinations: 1 }).adds,
    ["1 failure mode", "3 tasks", "1 combination of tasks"]);
});

test("the FME(C)A's columns: scores, effects, the action, the criticality figures; a mode directly under a function has no functional failure", () => {
  const m = { id: "m", text: "Bearing seizes", effects: "Motor stops", consequence: "operational", cause: "Dust", effect_local: "Shaft locks",
    effect_next: "Thrust lost", detection_method: "Vibration", severity: 9, occurrence: 4, detection: 6, rpn: 216, ap: "H",
    action: "Seal the bearing", action_owner: "Design", action_due: "2026-12-01", action_status: "in_progress",
    failure_rate: 8e-5, time_unit: "hours", rate_source: "data", mode_ratio: 0.5, loss_probability: 1, operating_time: 100, cm: 0.004, severity_class: "I" };
  const rows = positionRcmRows({ positions: [{ id: "p", name: "UAV", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Provide thrust", modes: [m], failures: [{ id: "x", text: "No thrust", modes: [{ ...m, id: "m2", text: "Prop breaks", rpn: null, ap: null, cm: null, severity: null, mode_ratio: null }] }] },
  ] }] });
  assert.equal(rows.length, 3);
  const at = (row, h) => row[EXPORT_HEADER.indexOf(h)];
  assert.equal(EXPORT_HEADER.indexOf("Cause"), EXPORT_HEADER.indexOf("Consequence") + 1);
  assert.equal(EXPORT_HEADER.indexOf("Decision"), EXPORT_HEADER.indexOf("Severity class") + 1);
  // The direct mode first, its Functional failure cell blank; the other under its failure.
  assert.deepEqual([at(rows[1], "Function"), at(rows[1], "Functional failure"), at(rows[1], "Failure mode")], ["Provide thrust", "", "Bearing seizes"]);
  assert.deepEqual([at(rows[2], "Functional failure"), at(rows[2], "Failure mode")], ["No thrust", "Prop breaks"]);
  assert.deepEqual(FMEA_HEADER.map((h) => at(rows[1], h)), ["Dust", "Shaft locks", "Thrust lost", "Vibration", 9, 4, 6, 216, "High", "Seal the bearing", "Design",
    "2026-12-01", "In progress", 8e-5, "hours", "From own data", 0.5, 1, 100, 0.004, "I"]);
  // Not scored: RPN, AP and Cm blank, never 0 or NaN.
  assert.deepEqual(["Severity", "RPN", "Action priority", "Mode criticality"].map((h) => at(rows[2], h)), ["", "", "", ""]);
  assert.equal(exportFilename("UAV", { what: "FMECA", ext: "xlsx" }), "UAV FMECA.xlsx");
});

test("every row kind's notes have a column: the function's and the failure's on their first row, a standard's on its own row", () => {
  const rows = positionRcmRows({ positions: [{ id: "p", name: "Pool", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Keep the water balanced", notes: "Bathers' comfort\nand the plaster's life", standard: "pH 7.2-7.8",
      standards: [{ id: "s1", text: "pH 7.2-7.8", notes: "AS 3633 range" }, { id: "s2", text: "TA 80-120 ppm", notes: "" }],
      failures: [
        { id: "x", text: "pH above 7.8", standard: { id: "s1", text: "pH 7.2-7.8" }, notes: "Scale forms above 7.8", modes: [
          { id: "m1", text: "Acid under-dosed", notes: "Seen twice in summer", decision: null },
          { id: "m2", text: "Acid tank empty", notes: "", decision: null },
        ] },
      ] },
  ] }] });
  for (const row of rows) assert.equal(row.length, EXPORT_HEADER.length);
  const notes = ["Function notes", "Performance standard", "Standard notes", "Functional failure notes", "Failure mode notes"];
  assert.deepEqual(rows.slice(1).map((r) => cells(r, ...notes)), [
    ["Bathers' comfort\nand the plaster's life", "pH 7.2-7.8", "AS 3633 range", "", ""],
    ["", "TA 80-120 ppm", "", "", ""],
    ["", "pH 7.2-7.8", "", "Scale forms above 7.8", "Seen twice in summer"],
    ["", "pH 7.2-7.8", "", "", ""],
  ]);
  assert.ok(positionRcmCsv({ positions: [{ id: "p", name: "Pool", depth: 0, unassigned: [], functions: [
    { id: "f", text: "Dose", notes: "Line one\nLine two", failures: [] }] }] }).includes('"Line one\nLine two"'));
});
