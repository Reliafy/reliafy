import { test } from "node:test";
import assert from "node:assert/strict";
import { isStruck, liveReadings, readingStatusText } from "./maintenanceReadings.js";

const trail = [
  { id: "a", at: "2026-10-13", value: 3774, status: "replaced", voided_on: "2026-10-13", void_reason: "old reading",
    replaced_by: { id: "b", at: "2026-03-27", value: 3774 } },
  { id: "c", at: "2026-10-01", value: 9000, status: "voided", voided_on: "2026-10-02", void_reason: "fat finger" },
  { id: "b", at: "2026-03-27", value: 3774, status: "correction", reason: "old reading",
    replaces: { id: "a", at: "2026-10-13", value: 3774 } },
  { id: "d", at: "2025-09-08", value: 3000, status: "ok" },
];

test("struck-out readings leave the live list", () => {
  assert.deepEqual(liveReadings(trail).map((r) => r.id), ["b", "d"]);
  assert.deepEqual(liveReadings(undefined), []);
  // A feed's readings carry no status: all of them count.
  assert.equal(liveReadings([{ at: "x", value: 1 }]).length, 1);
  assert.equal(isStruck(trail[0]), true);
  assert.equal(isStruck(trail[2]), false);
});

test("each change says what happened and why", () => {
  assert.equal(readingStatusText(trail[0]), "corrected 2026-10-13 to 3774 on 2026-03-27: old reading");
  assert.equal(readingStatusText(trail[1]), "voided 2026-10-02: fat finger");
  assert.equal(readingStatusText(trail[2], (d) => `<${d}>`), "correction of 3774 on <2026-10-13>: old reading");
  assert.equal(readingStatusText(trail[3]), "");
});
