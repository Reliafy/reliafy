import { test } from "node:test";
import assert from "node:assert/strict";
import { failureModeBody, failureModeNamed, failureModeReady } from "./maintenanceModes.js";

test("a position's mode goes by id, any other by its words", () => {
  assert.deepEqual(failureModeBody({ choice: "id:fm1" }), { failure_mode_id: "fm1", failure_mode_text: null });
  assert.deepEqual(failureModeBody({ choice: "text:Seal leaking" }),
    { failure_mode_id: null, failure_mode_text: "Seal leaking" });
  assert.deepEqual(failureModeBody({ choice: "new", typed: "  Impeller cracked " }),
    { failure_mode_id: null, failure_mode_text: "Impeller cracked" });
  assert.deepEqual(failureModeBody({ choice: "" }), { failure_mode_id: null, failure_mode_text: null });
  assert.deepEqual(failureModeBody(null), { failure_mode_id: null, failure_mode_text: null });
});

test("typing one in needs the words", () => {
  assert.equal(failureModeReady({ choice: "new", typed: " " }), false);
  assert.equal(failureModeReady({ choice: "new", typed: "Worn" }), true);
  assert.equal(failureModeReady({ choice: "" }), true);
  assert.equal(failureModeNamed({ choice: "" }), false);
  assert.equal(failureModeNamed({ choice: "id:x" }), true);
});
