import { test } from "node:test";
import assert from "node:assert/strict";
import {
  isTimeZone, setWorkspaceTimeZone, shouldSuggestTimeZone, timeZoneOptions, todayIn, workspaceToday,
} from "./workspaceDate.js";

const late = new Date("2026-10-14T23:30:00Z"); // 09:30 on the 15th in Brisbane

test("today is the day in the workspace's zone", () => {
  assert.equal(todayIn("Australia/Brisbane", late), "2026-10-15");
  assert.equal(todayIn("America/Los_Angeles", late), "2026-10-14");
});

test("unset or unknown is UTC, as the server", () => {
  assert.equal(todayIn(null, late), "2026-10-14");
  assert.equal(todayIn("Mars/Olympus_Mons", late), "2026-10-14");
  assert.equal(isTimeZone("Mars/Olympus_Mons"), false);
});

test("the active workspace's today follows its zone", () => {
  setWorkspaceTimeZone("Australia/Brisbane");
  assert.equal(workspaceToday(late), "2026-10-15");
  setWorkspaceTimeZone(null);
  assert.equal(workspaceToday(late), "2026-10-14");
});

test("a nudge only when unset and the browser isn't on UTC", () => {
  assert.equal(shouldSuggestTimeZone(null, "Australia/Brisbane"), true);
  assert.equal(shouldSuggestTimeZone("Australia/Brisbane", "Australia/Brisbane"), false);
  assert.equal(shouldSuggestTimeZone(null, "UTC"), false);
  assert.equal(shouldSuggestTimeZone(null, "Etc/UTC"), false);
});

test("the picker offers UTC and the zones", () => {
  const zones = timeZoneOptions();
  assert.ok(zones.includes("UTC") && zones.includes("Australia/Brisbane"));
});
