import { test } from "node:test";
import assert from "node:assert/strict";
import {
  clockIn, deviceClockDiffers, isTimeZone, setWorkspaceTimeZone, shouldSuggestTimeZone, timeZoneOptions, todayIn, workspaceClock,
  workspaceMoment, workspaceToday, workspaceZoneName,
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

test("a form's time of day is the workspace's clock, not the device's", () => {
  assert.equal(clockIn("Australia/Brisbane", late), "09:30");
  assert.equal(clockIn(null, late), "23:30");
  assert.equal(clockIn("America/Los_Angeles", new Date("2026-10-14T07:05:00Z")), "00:05"); // midnight is 00, never 24
  assert.equal(clockIn("Mars/Olympus_Mons", late), ""); // unknown here: no time, not a wrong one
  setWorkspaceTimeZone("Australia/Brisbane");
  assert.equal(workspaceClock(late), "09:30");
  assert.equal(workspaceZoneName(), "Australia/Brisbane");
  // The server reads a time with no offset on the workspace's clock.
  assert.equal(workspaceMoment(workspaceToday(late), workspaceClock(late)), "2026-10-15T09:30");
  assert.equal(deviceClockDiffers(late, "Australia/Brisbane"), false);
  setWorkspaceTimeZone(null);
  assert.equal(deviceClockDiffers(late, "Australia/Brisbane"), true);
  assert.equal(deviceClockDiffers(late, "Etc/UTC"), false);
  assert.equal(workspaceClock(late), "23:30");
  assert.equal(workspaceZoneName(), "UTC");
  assert.equal(workspaceMoment(workspaceToday(late), workspaceClock(late)), "2026-10-14T23:30Z");
});
