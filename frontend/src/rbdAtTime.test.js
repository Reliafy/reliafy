import { test } from "node:test";
import assert from "node:assert/strict";
import { atTimeLead, AT_TIME_NOTE } from "./rbdAtTime.js";

const pct = (v) => `${(v * 100).toFixed(2)}%`;

test("the answer says the time, where it starts and the chance in words", () => {
  assert.equal(atTimeLead({ t: 50, availability: 0.9095 }, "hours", false, pct),
    "At 50 hours from new, the system is up with a 90.95% chance.");
  assert.match(atTimeLead({ t: 720, availability: 0.99 }, "", true, pct), /^At 720 from now/);
});

test("the note says exact, and names the 90% two-sided range elsewhere", () => {
  assert.match(AT_TIME_NOTE, /^Exact/);
  assert.match(AT_TIME_NOTE, /90% two-sided/);
});
