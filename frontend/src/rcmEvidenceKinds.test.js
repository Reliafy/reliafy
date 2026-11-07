// A decision's evidence can be a model or saved analysis (checked: supported,
// contradicted...), a report or a function's notes and rationale (linked, not checked).
import { test } from "node:test";
import assert from "node:assert/strict";
import { RCM_CHIPS, hasLinkedEvidence, workingsFor } from "./explorerRcm.js";
import { COLUMN, checkLabel, evidenceKinds, startKind } from "./rcmWorksheet.js";

const mode = (id, decision) => ({ id, text: id, decision });
const report = { outcome: "redesign", evidence: { type: "report", id: "r1" }, status: "linked", evidence_kind: "report",
  artifact_name: "Seal case", artifact_link_path: "/reports?open=r1" };
const working = { outcome: "accept", evidence: { type: "working", id: "f1" }, status: "linked", evidence_kind: "working",
  artifact_name: "Pump water", working: { id: "f1", text: "Pump water" } };
const model = { outcome: "rtf", rtf_basis: "random", evidence: { type: "model", id: "m" }, status: "contradicted",
  evidence_kind: "model" };

test("the Evidence check names what's linked and never calls a report or working supported", () => {
  assert.equal(checkLabel(report), "Report linked");
  assert.equal(checkLabel(working), "Notes linked");
  assert.equal(checkLabel({ status: "linked" }), "Linked");
  assert.equal(checkLabel(model), "Contradicted");
  assert.equal(checkLabel({ status: "stale", evidence_kind: "report" }), "Stale link");
  assert.equal(checkLabel({ status: "unevidenced" }), "");
  assert.equal(checkLabel(null), "");
  const row = (d) => ({ type: "mode", ref: mode("x", d), sum: {} });
  assert.equal(COLUMN.check.text(row(report)), "Report linked");
  assert.equal(COLUMN.evidence.text(row(working)), "Pump water");
  // Sorted after every computed verdict.
  assert.ok(COLUMN.check.sort(row(report)) > COLUMN.check.sort(row({ status: "supported" })));
});

test("Evidence to look at ignores what's only linked", () => {
  const chip = RCM_CHIPS.find((c) => c.id === "check");
  const row = (d) => ({ type: "mode", ref: mode("x", d) });
  assert.equal(chip.test(row(report)), false);
  assert.equal(chip.test(row(working)), false);
  assert.equal(chip.test(row(model)), true);
  assert.equal(chip.test(row({ ...report, status: "stale" })), true); // a report that's gone is
});

test("a linked report or working shows the Evidence check column, under a function directly too", () => {
  const rcm = { positions: [{ id: "p", functions: [{ id: "f1", failures: [], modes: [mode("a", report)] }], unassigned: [] }] };
  assert.equal(hasLinkedEvidence(rcm), true);
});

test("the dialog offers models only when the decision expects one, and opens on what's linked", () => {
  assert.deepEqual(evidenceKinds("strategy_analysis"), ["model", "report", "working"]);
  assert.deepEqual(evidenceKinds(null), ["report", "working"]);
  assert.equal(startKind(null, "model"), "model");
  assert.equal(startKind(null, null), "report");
  assert.equal(startKind({ type: "working", id: "f" }, "model"), "working");
  assert.equal(startKind({ type: "model", id: "m" }, "model"), "model");
});

test("the function notes on offer are the mode's position's functions with notes, its own function first", () => {
  const rcm = { positions: [
    { id: "other", functions: [{ id: "f9", text: "Elsewhere", notes: "x", failures: [] }], unassigned: [] },
    { id: "pump", functions: [
      { id: "f1", text: "Contain water", notes: "Rated 10 bar", basis_preview: "Rated 10 bar", failures: [] },
      { id: "f2", text: "No notes", notes: "  ", failures: [] },
      { id: "f3", text: "Pump water", notes: "50 L/s", basis_preview: "50 L/s", failures: [{ id: "x", modes: [mode("seal")] }] },
    ], unassigned: [mode("loose")] },
  ] };
  assert.deepEqual(workingsFor(rcm, "seal").map((w) => w.id), ["f3", "f1"]);
  assert.deepEqual(workingsFor(rcm, "loose"), [
    { id: "f1", label: "Contain water", meta: "Rated 10 bar" }, { id: "f3", label: "Pump water", meta: "50 L/s" }]);
  assert.deepEqual(workingsFor(rcm, "nowhere"), []);
  assert.deepEqual(workingsFor(null, "seal"), []);
});
