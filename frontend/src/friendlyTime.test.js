import test from "node:test";
import assert from "node:assert/strict";
import {
  FRIENDLY_CONVENTION, calendarUnit, convertTime, defaultFriendlyUnit, friendlyRange, friendlyText,
  loadFriendlyUnit, pickFriendlyUnit, saveFriendlyUnit,
} from "./friendlyTime.js";

test("calendarUnit: the five calendar units in any spelling, nothing else", () => {
  assert.equal(calendarUnit("Days"), "days");
  assert.equal(calendarUnit("hrs"), "hours");
  assert.equal(calendarUnit(" Months "), "months");
  assert.equal(calendarUnit("yr"), "years");
  assert.equal(calendarUnit("wk"), "weeks");
  for (const u of ["Cycles", "km", "starts", "operating hours", "Flight hours", "", null, undefined, "Minutes"]) {
    assert.equal(calendarUnit(u), null, String(u));
  }
});

test("convertTime: the app's calendar convention (24 h, 7 d, 365.25/12 d, 365.25 d)", () => {
  assert.equal(convertTime(36, "hours", "days"), 1.5);
  assert.equal(convertTime(2, "weeks", "days"), 14);
  assert.equal(convertTime(365.25, "days", "years"), 1);
  assert.equal(convertTime(12, "months", "years"), 1);
  assert.ok(Math.abs(convertTime(1, "years", "hours") - 8766) < 1e-9);
  assert.equal(convertTime(10, "cycles", "days"), null);
  assert.equal(convertTime(null, "days", "years"), null);
  assert.equal(convertTime(Infinity, "days", "years"), null);
});

test("defaultFriendlyUnit: the largest unit in which the headline is at least 1", () => {
  assert.equal(defaultFriendlyUnit(9730, "Days"), "years");
  assert.equal(defaultFriendlyUnit(36, "Hours"), "days");
  assert.equal(defaultFriendlyUnit(200, "Hours"), "weeks");
  assert.equal(defaultFriendlyUnit(1000, "Hours"), "months");
  assert.equal(defaultFriendlyUnit(5, "Days"), "days");
  assert.equal(defaultFriendlyUnit(0.5, "Hours"), "hours");
  assert.equal(defaultFriendlyUnit(500, "Cycles"), null);
});

test("pickFriendlyUnit: the viewer's choice wins, else the default; none off calendar time", () => {
  assert.equal(pickFriendlyUnit("months", 9730, "Days"), "months");
  assert.equal(pickFriendlyUnit(null, 9730, "Days"), "years");
  assert.equal(pickFriendlyUnit("bogus", 9730, "Days"), "years");
  assert.equal(pickFriendlyUnit("years", 9730, "km"), null);
});

test("friendlyText: about 3 significant figures, nothing when it adds nothing", () => {
  assert.equal(friendlyText(9730, "days", "years"), "≈ 26.6 years");
  assert.equal(friendlyText(36, "Hours", "days"), "≈ 1.5 days");
  assert.equal(friendlyText(365.25, "days", "years"), "≈ 1 year");
  assert.equal(friendlyText(9730, "days", "days"), "");
  assert.equal(friendlyText(9730, "Days", "days"), "");
  assert.equal(friendlyText(9730, "Cycles", "years"), "");
  assert.equal(friendlyText(null, "days", "years"), "");
  assert.equal(friendlyText(9730, "days", null), "");
});

test("friendlyRange: both ends converted, the unit once", () => {
  assert.equal(friendlyRange(8000, 12000, "days", "years"), "≈ 21.9–32.9 years");
  assert.equal(friendlyRange(8000, 12000, "days", "days"), "");
  assert.equal(friendlyRange(8000, null, "days", "years"), "");
});

test("the convention is stated in words", () => {
  assert.match(FRIENDLY_CONVENTION, /365\.25 days/);
  assert.match(FRIENDLY_CONVENTION, /running all the time/);
});

test("the choice is remembered per browser, and storage failing is harmless", () => {
  const store = new Map();
  globalThis.window = { localStorage: { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) } };
  try {
    assert.equal(loadFriendlyUnit(), null);
    saveFriendlyUnit("Months");
    assert.equal(loadFriendlyUnit(), "months");
    globalThis.window = { localStorage: { getItem: () => { throw new Error("blocked"); },
                                          setItem: () => { throw new Error("blocked"); } } };
    assert.equal(loadFriendlyUnit(), null);
    assert.doesNotThrow(() => saveFriendlyUnit("years"));
  } finally {
    delete globalThis.window;
  }
});
