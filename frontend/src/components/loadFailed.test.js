import { test } from "node:test";
import assert from "node:assert/strict";
import { isNotFound, plainLoadError } from "./loadFailed.js";

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

test("a 404 Error reads as not found", () => {
  const e = new Error("Gone"); e.status = 404;
  assert.equal(isNotFound(e), true);
});

test("raw server and browser messages become plain words", () => {
  for (const m of ["Internal Server Error", "Request failed (500)", "Bad Gateway", "Service Unavailable",
    "[object Object]", "Traceback (most recent call last)", "", null, undefined]) {
    const text = plainLoadError(m);
    assert.match(text, /went wrong on our side/, String(m));
  }
  for (const m of ["Failed to fetch", "Load failed", "NetworkError when attempting to fetch resource."]) {
    assert.match(plainLoadError(m), /couldn't be reached/, m);
  }
});

test("a 5xx keeps plain words whatever its detail says", () => {
  const e = new Error("KeyError: 'x'"); e.status = 500;
  assert.match(plainLoadError(e), /went wrong on our side/);
});

test("a sentence written for people is kept", () => {
  for (const m of ["Not a member of this workspace.", "Simulations need Pro."]) {
    assert.equal(plainLoadError(m), m);
  }
  const e = new Error("Not authenticated"); e.status = 401;
  assert.equal(plainLoadError(e), "Not authenticated");
});
