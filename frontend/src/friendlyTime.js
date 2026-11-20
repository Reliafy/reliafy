// A life answer in a friendlier calendar unit as well as the model's own
// ("9,730 days (≈ 26.6 years)"). The model's unit stays the primary value:
// inputs, parameters, plots, exports and the API all keep it; this only adds
// a second reading beside answer lines. It uses the app's one calendar
// convention (backend/services/strategy_calendar.py): 24 hours a day, 7 days a
// week, 365.25 / 12 days a month and 365.25 days a year, running all the time.
// Pure functions plus a guarded localStorage memo, so `node --test` covers them.
import { formatNumber, formatWithUnit } from "./format.js";

// Days in one of each calendar unit, smallest first.
const DAYS = { hours: 1 / 24, days: 1, weeks: 7, months: 365.25 / 12, years: 365.25 };
export const FRIENDLY_UNITS = Object.keys(DAYS);

// The spellings of each calendar unit a model's unit might use (backend/units.py
// UNIT_ALIASES, the calendar ones only). "Operating hours", cycles, km, a blank
// or a typed unit are not calendar time, so they get no friendly unit.
const ALIASES = {
  h: "hours", hr: "hours", hrs: "hours", hour: "hours", hours: "hours",
  d: "days", day: "days", days: "days",
  wk: "weeks", wks: "weeks", week: "weeks", weeks: "weeks",
  mo: "months", mon: "months", mth: "months", mths: "months", month: "months", months: "months",
  y: "years", yr: "years", yrs: "years", year: "years", years: "years",
};

export const FRIENDLY_CONVENTION =
  "A day is 24 hours, a month 365.25 / 12 days and a year 365.25 days, running all the time.";

// The model's unit as one of FRIENDLY_UNITS, or null when it isn't calendar time.
export function calendarUnit(unit) {
  const key = String(unit ?? "").trim().toLowerCase().replace(/\.$/, "");
  return ALIASES[key] || null;
}

// A time in the model's unit, in another calendar unit (null if either isn't one).
export function convertTime(value, from, to) {
  const f = calendarUnit(from);
  const t = calendarUnit(to);
  const n = Number(value);
  if (!f || !t || value == null || value === "" || !Number.isFinite(n)) return null;
  return (n * DAYS[f]) / DAYS[t];
}

// The default friendly unit for a headline value: the largest calendar unit in
// which it is at least 1 (9,730 days → years; 36 hours → days), else hours.
export function defaultFriendlyUnit(value, unit) {
  if (!calendarUnit(unit)) return null;
  for (const u of [...FRIENDLY_UNITS].reverse()) {
    const v = convertTime(value, unit, u);
    if (v != null && Math.abs(v) >= 1) return u;
  }
  return "hours";
}

// The unit to show beside the model's: the viewer's choice when it is one,
// else the default for the headline; null when the model's unit isn't
// calendar time.
export function pickFriendlyUnit(chosen, headline, unit) {
  if (!calendarUnit(unit)) return null;
  return calendarUnit(chosen) || defaultFriendlyUnit(headline, unit);
}

// "≈ 26.6 years" for a value in the model's unit, or "" when there's nothing
// to add (not calendar time, the same unit, or no number).
export function friendlyText(value, unit, friendly, opts) {
  const f = calendarUnit(friendly);
  if (!f || !calendarUnit(unit) || calendarUnit(unit) === f) return "";
  const v = convertTime(value, unit, f);
  return v == null ? "" : `≈ ${formatWithUnit(v, f, opts)}`;
}

// "≈ 21.9–32.9 years" for a range in the model's unit, or "".
export function friendlyRange(lower, upper, unit, friendly, opts) {
  const f = calendarUnit(friendly);
  if (!f || !calendarUnit(unit) || calendarUnit(unit) === f) return "";
  const lo = convertTime(lower, unit, f);
  const hi = convertTime(upper, unit, f);
  return lo == null || hi == null ? "" : `≈ ${formatNumber(lo, opts)}–${formatWithUnit(hi, f, opts)}`;
}

// The viewer's chosen friendly unit, remembered per browser (a convenience:
// without storage the default applies).
const KEY = "reliafy.friendlyTimeUnit";

export function loadFriendlyUnit() {
  try {
    return calendarUnit(window.localStorage.getItem(KEY));
  } catch {
    return null;
  }
}

export function saveFriendlyUnit(unit) {
  try {
    window.localStorage.setItem(KEY, calendarUnit(unit) || "");
  } catch {
    /* no storage: the choice lasts this page only */
  }
}
