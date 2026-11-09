import { test } from "node:test";
import assert from "node:assert/strict";
import { isNotFound } from "./loadFailed.js";

test("a missing item reads as not found", () => {
  for (const m of ["Not found.", "Fleet not found.", "Dataset not found", "NOT FOUND"]) {
    assert.equal(isNotFound(m), true, m);
  }
});

test("other failures stay errors", () => {
  for (const m of ["Request failed (500)", "Not authenticated", "Failed to fetch", "", null, undefined]) {
    assert.equal(isNotFound(m), false, String(m));
  }
});
