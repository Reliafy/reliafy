import { test } from "node:test";
import assert from "node:assert/strict";
import { EXPORT_HEADER, exportFilename, importSummary, isCsvFile, positionRcmCsv, positionRcmRows } from "./rcmImport.js";

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
  assert.deepEqual(rows[1].slice(0, 6), ["Plant › Conveyor C-2", "", "", "", "", "Motor hums"]);
  assert.deepEqual(rows[2], ["Plant › Conveyor C-2", "Move grain", "40 t/h", "## Rate\n\n40 t/h = 10 t over 15 min", "Moves no grain", "Belt torn", "Line stops",
    "Operational", "On-condition", "", "Walk the belt", 1, "weeks", "", "Severity 7"]);
  assert.deepEqual(rows[3].slice(7, 14), ["Non-operational", "Run-to-failure", "random", "Replace when it fails", "", "",
    "Contradicted"]);
  assert.deepEqual(rows[4].slice(1, 6), ["Move grain", "40 t/h", "", "Moves too little", ""]); // a failure with no modes
  assert.deepEqual(rows[5].slice(1, 6), ["Stop on the lanyard", "", "", "", ""]); // a function with no failures
  assert.deepEqual(positionRcmRows(null), [EXPORT_HEADER]);
});

test("the CSV keeps a formula-looking cell as text, and the file is named after the position", () => {
  const csv = positionRcmCsv(WS);
  assert.ok(csv.startsWith("Position,Function,Performance standard,Standard working,Functional failure,Failure mode,"));
  assert.ok(csv.includes(",'=Bearing seizes,"));
  assert.equal(exportFilename("Conveyor C-2"), "Conveyor C-2 RCM.csv");
  assert.equal(exportFilename('Pump "A" / B'), "Pump A B RCM.csv");
  assert.equal(exportFilename(""), "Position RCM.csv");
});

test("the working is written on a function's first row only, and quoted with its line breaks", () => {
  const rows = positionRcmRows(WS);
  const col = EXPORT_HEADER.indexOf("Standard working");
  assert.equal(col, EXPORT_HEADER.indexOf("Performance standard") + 1);
  assert.deepEqual(rows.map((r) => r[col]), ["Standard working", "", "## Rate\n\n40 t/h = 10 t over 15 min", "", "", ""]);
  assert.ok(positionRcmCsv(WS).includes('"## Rate\n\n40 t/h = 10 t over 15 min"'));
});
