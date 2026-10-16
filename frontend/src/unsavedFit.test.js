// Run with: node --test src/
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAX_KEPT_CSV, canSaveAgain, forgetUnsavedFit, loadUnsavedFit, rememberUnsavedFit, unsavedFitRecord,
} from "./unsavedFit.js";

// A localStorage stand-in for node.
function withStorage(fn) {
  const data = new Map();
  globalThis.window = {
    localStorage: {
      getItem: (k) => (data.has(k) ? data.get(k) : null),
      setItem: (k, v) => data.set(k, String(v)),
      removeItem: (k) => data.delete(k),
    },
  };
  try {
    fn(data);
  } finally {
    delete globalThis.window;
  }
}

const FIT = {
  name: "Weibull — raw", distribution: "weibull", mapping: { x: "col 1" }, opts: { unit: "Hours" },
};

test("an unsaved fit of an upload keeps its data, so one click saves both", () => {
  const rec = unsavedFitRecord({ ...FIT, csv: "col 1\n300\n410\n", fileName: "raw.csv", at: "2026-10-16T00:00:00Z" });
  assert.deepEqual(rec, { ...FIT, csv: "col 1\n300\n410\n", fileName: "raw.csv", at: "2026-10-16T00:00:00Z" });
  assert.equal(canSaveAgain(rec), true);
});

test("a fit of a saved dataset keeps only the dataset's id", () => {
  const rec = unsavedFitRecord({ ...FIT, datasetId: "ds1", csv: "ignored" });
  assert.equal(rec.datasetId, "ds1");
  assert.equal("csv" in rec, false);
  assert.equal(canSaveAgain(rec), true);
});

test("a large upload isn't copied into the browser: the reminder offers a refit", () => {
  const rec = unsavedFitRecord({ ...FIT, csv: "x".repeat(MAX_KEPT_CSV + 1), fileName: "big.csv" });
  assert.equal("csv" in rec, false);
  assert.equal(canSaveAgain(rec), false);
});

test("remembered per workspace until saved or dismissed", () => {
  withStorage(() => {
    const rec = unsavedFitRecord({ ...FIT, datasetId: "ds1" });
    rememberUnsavedFit("u1:personal", rec);
    assert.deepEqual(loadUnsavedFit("u1:personal"), rec);
    assert.equal(loadUnsavedFit("u1:team-2"), null);
    forgetUnsavedFit("u1:personal");
    assert.equal(loadUnsavedFit("u1:personal"), null);
  });
});

test("no storage, or a broken record, is no reminder", () => {
  assert.equal(loadUnsavedFit("u1:personal"), null);
  rememberUnsavedFit("u1:personal", unsavedFitRecord(FIT)); // no throw
  withStorage((data) => {
    data.set("reliafy:unsaved-fit:u1:personal", "{not json");
    assert.equal(loadUnsavedFit("u1:personal"), null);
  });
});
