import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_SETUP, boundText, rangeSentence, rangeShort, calendarText, chanceSentence, failuresSentence, runsOnBody, runsOnOptions, sameSetup, setupBody,
  setupErrors, setupForm,
} from "./missionSetup.js";

test("a setup is checked field by field and sent with numbers as numbers", () => {
  assert.deepEqual(setupErrors(DEFAULT_SETUP), {});
  assert.ok(setupErrors({ ...DEFAULT_SETUP, start: "" }).start);
  assert.ok(setupErrors({ ...DEFAULT_SETUP, length: { value: "", unit: "months" } }, { withLength: true }).length);
  assert.deepEqual(setupErrors({ ...DEFAULT_SETUP, length: { value: "12", unit: "months" } }, { withLength: true }), {});
  const own = { start: "2026-12-01", calendar: { linked: false, hours_per_day: "8", days_per_week: "5" }, from: "today" };
  assert.deepEqual(setupErrors(own), {});
  assert.ok(setupErrors({ ...own, calendar: { linked: false, hours_per_day: "30", days_per_week: "5" } }).calendar);
  assert.ok(setupErrors({ ...own, calendar: { linked: false, hours_per_day: "8", days_per_week: "5.5" } }).calendar);
  assert.deepEqual(setupBody(own), { start: "2026-12-01", calendar: { hours_per_day: 8, days_per_week: 5 }, from: "today" });
  assert.deepEqual(setupBody(DEFAULT_SETUP), { start: "now", calendar: { linked: true }, from: "new" });
  // As saved, back into the form, and compared.
  const back = setupForm({ start: "2026-12-01", calendar: { hours_per_day: 8, days_per_week: 5 }, from: "today" });
  assert.ok(sameSetup(back, own));
  assert.ok(!sameSetup(back, DEFAULT_SETUP));
  assert.deepEqual(setupForm(null), DEFAULT_SETUP);
});

test("runs on: every saved non-repairable RBD here and below, then the tree (or a leaf's model)", () => {
  const rows = new Map([
    ["site", { key: "site", type: "pos", ref: { name: "Site" }, kids: ["st"], rbds: [] }],
    ["st", { key: "st", type: "pos", ref: { name: "Pump station" }, kids: ["pa"], rbds: [
      { link_id: "L1", rbd: { id: "r1", name: "Station RBD" } },
      { link_id: "L2", rbd: { id: "r2", name: "Station — Duty", mission_rbd: true } },
      { link_id: "L3", rbd: { id: "r3", name: "Repairable", repairable: true } },
    ] }],
    ["pa", { key: "pa", type: "pos", ref: { name: "Pump A" }, kids: [], rbds: [], hasModel: true }],
  ]);
  assert.deepEqual(runsOnOptions(rows, "site").map((o) => [o.value, o.hint]),
    [["rbd:L1", "At Pump station"], ["tree", runsOnOptions(rows, "site")[1].hint]]);
  assert.deepEqual(runsOnOptions(rows, "st").map((o) => o.value), ["rbd:L1", "tree"]);
  assert.deepEqual(runsOnOptions(rows, "pa").map((o) => o.value), ["model"]);
  assert.deepEqual(runsOnBody("rbd:L1"), { linkId: "L1" });
  assert.deepEqual(runsOnBody("tree"), { tree: true });
  assert.deepEqual(runsOnBody("model"), {});
});

test("the answers in plain words, the bound and the range saying which side", () => {
  assert.equal(chanceSentence({ value: 0.9713 }), "About 97 in 100 missions like this finish without a system failure.");
  assert.equal(chanceSentence({ value: 0.9999 }), "Almost all missions like this finish without a system failure.");
  assert.equal(boundText({ value: 0.97, lower_bound: { lower: 0.952, confidence: 0.9 } }), "At least 95.2% (90% one-sided lower bound)");
  assert.equal(boundText({ value: 0.97, lower_bound: null, bound_note: "No bound yet." }), "No bound yet.");
  assert.equal(failuresSentence({ expected: 0.6, range: { lower: 0, upper: 2 } }, 30, "hours"),
    "Expect about 0.6 part failures over the 30 hours. In 90 of 100 missions like this, between 0 and 2 (two-sided).");
  assert.equal(failuresSentence({ expected: 1, range: null }, 10, "hours"), "Expect about 1 part failure over the 10 hours.");
  // A range of 0 to 0 said plainly, from the share of missions with a failure (1 in 43 for 2.35%).
  assert.equal(failuresSentence({ expected: 0.0235, range: { lower: 0, upper: 0, p_any: 0.0233, runs: 2000 } }, 720, "hours"),
    "Expect about 0.0235 part failures over the 720 hours. In more than 9 of 10 missions like this, nothing fails; about 1 in 43 has a failure.");
  assert.equal(rangeSentence({ lower: 0, upper: 0, p_any: 0, runs: 2000 }), "None of the 2,000 simulated missions had a failure.");
  assert.equal(rangeShort({ lower: 0, upper: 0, p_any: 0.02 }), "nothing fails in more than 9 of 10 missions");
  assert.equal(rangeShort({ lower: 1, upper: 4 }), "90% range 1 to 4 (two-sided)");
  assert.equal(failuresSentence({ expected: null, note: "Not yet." }, 10, "hours"), "Not yet.");
  assert.equal(calendarText({ start: "2026-12-01", end: "2026-12-15", clock: { text: "its own duty: 8 h a day, 5 days a week" } }),
    "1 Dec 2026 to about 15 Dec 2026 · its own duty: 8 h a day, 5 days a week");
});
