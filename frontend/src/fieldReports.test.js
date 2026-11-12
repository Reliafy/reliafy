import assert from "node:assert/strict";
import test from "node:test";
import { arrivingText, clockLength, contentsText, keepText, matches, takenText } from "./fieldReports.js";

test("lengths read as a clock", () => {
  assert.deepEqual([0, 7.9, 75, 3723].map(clockLength), ["0:00", "0:07", "1:15", "1:02:03"]);
});

test("what a report holds, in words", () => {
  assert.equal(contentsText({ counts: { photo: 2, audio: 1, file: 0 }, audio_seconds: 12.4 }), "2 photos, 1 recording (0:12)");
  assert.equal(contentsText({ counts: { photo: 1, audio: 0, file: 2 } }), "1 photo, 2 files");
  assert.equal(contentsText({ counts: { photo: 0, audio: 0, file: 0 } }), "");
});

test("attachments still on the phone are said plainly", () => {
  assert.equal(arrivingText({ complete: true, media_expected: 3, media_arrived: 3 }), "");
  assert.equal(arrivingText({ complete: false, media_expected: null, media_arrived: 0 }), "");
  assert.equal(arrivingText({ complete: false, media_expected: 5, media_arrived: 2 }),
    "2 of 5 attachments have arrived; the rest are still on the phone.");
  assert.match(arrivingText({ complete: false, media_expected: 1, media_arrived: 0 }), /^0 of 1 attachment have/);
});

test("when a report's content goes", () => {
  assert.equal(keepText({ expires_on: "2026-12-12" }, "2026-11-30"), "Deletes in 12 days");
  assert.equal(keepText({ expires_on: "2026-12-01" }, "2026-11-30"), "Deletes in 1 day");
  assert.equal(keepText({ expires_on: "2026-11-30" }, "2026-11-30"), "Deletes today");
  assert.equal(keepText({ keep: true, expires_on: null }, "2026-11-30"), "Kept");
  assert.equal(keepText({ expired: true }, "2026-11-30"), "Deleted");
  assert.equal(keepText({ expires_on: "2026-12-12" }, null), "");
});

test("the device's time is shown as its clock read", () => {
  assert.equal(takenText("2026-11-12T09:30:00+10:00"), "12 Nov 2026, 09:30");
  assert.equal(takenText(""), "");
});

test("search looks at notes, who and what it is about", () => {
  const r = { notes_preview: "Seal weeping", title: "Field report 3", by_name: "Sam", about: [{ name: "Feed pump P-101" }] };
  for (const q of ["seal", "SAM", "p-101", "report 3", ""]) assert.equal(matches(r, q), true, q);
  assert.equal(matches(r, "gearbox"), false);
});
