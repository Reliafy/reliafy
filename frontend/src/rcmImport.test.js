import { test } from "node:test";
import assert from "node:assert/strict";
import { EXPORT_HEADER, causedBy, exportFilename, importSummary, isCsvFile, positionRcmCsv, positionRcmRows } from "./rcmImport.js";

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
          id: "f1", text: "Move grain", standard: "40 t/h",
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
  assert.deepEqual(rows[1].slice(0, 6), ["Plant › Conveyor C-2", "", "", "", "", "Motor hums"]);
  assert.deepEqual(rows[2], ["Plant › Conveyor C-2", "Move grain", "40 t/h", "Moves no grain", "Conveyor drive › No torque", "Belt torn", "Line stops",
    "Operational", "On-condition", "", "Walk the belt", 1, "weeks", "", "Severity 7"]);
  assert.deepEqual(rows[3].slice(7, 14), ["Non-operational", "Run-to-failure", "random", "Replace when it fails", "", "",
    "Contradicted"]);
  assert.deepEqual(rows[4].slice(1, 6), ["Move grain", "40 t/h", "Moves too little", "", ""]); // a failure with no modes
  assert.deepEqual(rows[5].slice(1, 6), ["Stop on the lanyard", "", "", "", ""]); // a function with no failures
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
  assert.equal(EXPORT_HEADER.indexOf("Caused by (below)"), EXPORT_HEADER.indexOf("Functional failure") + 1);
});

test("links count in the import's words", () => {
  assert.deepEqual(importSummary({ links: 2 }).adds, ["2 links between functional failures"]);
  assert.equal(importSummary({ links: 1 }).nothing, false);
  assert.deepEqual(importSummary({ links_existing: 1 }).there, ["1 link between functional failures"]);
});

test("the CSV keeps a formula-looking cell as text, and the file is named after the position", () => {
  const csv = positionRcmCsv(WS);
  assert.ok(csv.startsWith("Position,Function,Performance standard,Functional failure,Caused by (below),Failure mode,"));
  assert.ok(csv.includes(",'=Bearing seizes,"));
  assert.equal(exportFilename("Conveyor C-2"), "Conveyor C-2 RCM.csv");
  assert.equal(exportFilename('Pump "A" / B'), "Pump A B RCM.csv");
  assert.equal(exportFilename(""), "Position RCM.csv");
});
