// The active workspace's calendar day. A workspace can say where it is (an IANA
// time zone, on Settings or Team settings); the server works out "today", due
// dates and overdue in that zone, so forms that pre-fill today use the same day.
// Unset, the server uses UTC, and so does this.
//
// WorkspaceProvider sets the zone when the workspace (or its zone) changes;
// everything else just calls workspaceToday().

let current = null;

export function setWorkspaceTimeZone(zone) {
  current = zone || null;
}

export function workspaceTimeZone() {
  return current;
}

// The browser's own zone ("Australia/Brisbane"), offered as the suggestion.
export function browserTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

// Whether a zone is one this browser knows (a stored one may not be).
export function isTimeZone(zone) {
  if (!zone) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

// The ISO day ("2026-10-15") it is in `zone` (UTC when unset or unknown) at `now`.
export function todayIn(zone, now = new Date()) {
  const timeZone = isTimeZone(zone) ? zone : "UTC";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

// Today in the active workspace.
export function workspaceToday(now = new Date()) {
  return todayIn(current, now);
}

// The clock time ("14:05", 24-hour) it is in `zone` (UTC when unset) at `now`.
// "" for a zone this browser doesn't know: no time is better than a wrong one.
export function clockIn(zone, now = new Date()) {
  if (zone && !isTimeZone(zone)) return "";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone || "UTC", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const get = (type) => parts.find((p) => p.type === type)?.value;
  return `${get("hour")}:${get("minute")}`;
}

// The time now on the active workspace's clock: what a form's time of day
// starts with. The device's own clock time is wrong whenever the device is in
// another zone (a phone in Brisbane, a workspace on UTC).
export function workspaceClock(now = new Date()) {
  return clockIn(current, now);
}

// Whether this device's clock reads differently from the workspace's (another
// zone): then a form says whose clock its times are on.
export function deviceClockDiffers(now = new Date(), deviceZone = browserTimeZone()) {
  return !!deviceZone && clockIn(deviceZone, now) !== workspaceClock(now);
}

// The zone the workspace's clock is on, to show beside a time field.
export function workspaceZoneName() {
  return current || "UTC";
}

// A day and a time of day on the workspace's clock, as the API takes a reading's
// `at`: in the workspace's zone when it has one, else marked as UTC.
export function workspaceMoment(day, time) {
  return `${day}T${time}${current ? "" : "Z"}`;
}

// Every zone the browser can list, for the picker (a short list where it can't).
export function timeZoneOptions() {
  try {
    const zones = Intl.supportedValuesOf("timeZone");
    if (zones?.length) return zones.includes("UTC") ? zones : ["UTC", ...zones];
  } catch {
    // older browsers: fall through
  }
  return ["UTC", "Europe/London", "America/New_York", "America/Chicago", "America/Los_Angeles",
    "Asia/Singapore", "Australia/Perth", "Australia/Brisbane", "Australia/Sydney", "Pacific/Auckland"];
}

// Whether to nudge: no zone set, and the browser is somewhere UTC isn't local.
export function shouldSuggestTimeZone(zone, browserZone = browserTimeZone()) {
  if (zone || !browserZone) return false;
  return !["UTC", "Etc/UTC", "Etc/GMT", "GMT", "Etc/Universal", "Etc/Zulu"].includes(browserZone);
}
