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
