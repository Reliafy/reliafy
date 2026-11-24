// A mission's setup and its two answers, in words (the Explorer's Missions tab, 23 Nov 2026).
// Pure functions, tested in missionSetup.test.js; drawn by MissionSetup.jsx, NewMissionPane and
// MissionAnswers.jsx. The answers come from POST /api/rbds/{id}/missions/{mission}/answers
// (backend/services/mission_answers.py).

import { fmt, lengthText, pct } from "./explorerMissions.js";
import { formatDate } from "./dates.js";

// A mission's clock (Derryn, 23 Nov 2026: "allow a mission to be in operational time as well as
// calendar time"): operating time (a 10-flight-hour sortie: its length and phases in operating units,
// no calendar needed) or calendar time (a start date and days to years, through its duty).
export const CLOCKS = [{ value: "operating", label: "Operating time" }, { value: "calendar", label: "Calendar time" }];
export const OPERATING_UNITS = ["hours", "cycles", "km"];
export const CALENDAR_UNITS = ["days", "weeks", "months", "years"];
export const DEFAULT_SETUP = Object.freeze({ clock: "operating", label: "", start: "now", calendar: { linked: true }, from: "new" });
export const NEW_LENGTH = Object.freeze({ value: "", unit: "hours" });

// A saved setup's clock, as the server reads one saved before the choice (rbd_missions.clock_of):
// calendar where it has a start date, its own duty or a calendar length; else operating.
export function clockOf(saved) {
  if (!saved) return "operating";
  if (saved.clock === "operating" || saved.clock === "calendar") return saved.clock;
  if ((saved.start || "now") !== "now" || (saved.calendar && !saved.calendar.linked) || CALENDAR_UNITS.includes(saved.length?.unit)) return "calendar";
  return "operating";
}

// The length units a clock takes; a length in the other clock's units moves to its first.
export const unitsFor = (clock) => (clock === "calendar" ? CALENDAR_UNITS : OPERATING_UNITS);
export function withClock(v, clock) {
  const units = unitsFor(clock);
  const length = v.length ? { ...v.length, unit: units.includes(v.length.unit) ? v.length.unit : (clock === "calendar" ? "months" : "hours") } : v.length;
  return { ...v, clock, ...(length ? { length } : {}) };
}

const num = (v) => (v === "" || v == null ? NaN : Number(v));

// What's wrong with a setup, per field ({start?, length?, calendar?}); {} when it can be saved.
export function setupErrors(v, { withLength = false } = {}) {
  const out = {};
  if (v?.start !== "now" && !/^\d{4}-\d{2}-\d{2}$/.test(String(v?.start || ""))) out.start = "Pick the day it starts, or Now.";
  if (withLength && v?.length?.unit && !unitsFor(v?.clock || "operating").includes(v.length.unit)) {
    out.length = v?.clock === "calendar" ? "On calendar time, give the length in days, weeks, months or years."
      : "On operating time, give the length in operating hours, cycles or km.";
    return out;
  }
  if (withLength) {
    const n = num(v?.length?.value);
    if (!(n > 0) || !Number.isFinite(n)) out.length = "Enter its length: a number more than 0.";
  }
  if (v?.calendar && v.calendar.linked === false) {
    const h = num(v.calendar.hours_per_day);
    const d = num(v.calendar.days_per_week);
    if (!(h > 0 && h <= 24)) out.calendar = "Hours a day: more than 0, up to 24.";
    else if (!(Number.isInteger(d) && d >= 1 && d <= 7)) out.calendar = "Days a week: a whole number from 1 to 7.";
  }
  return out;
}

// The setup as the API takes it ({start, calendar, from}), numbers as numbers.
export function setupBody(v) {
  const cal = v?.calendar?.linked === false
    ? { hours_per_day: Number(v.calendar.hours_per_day), days_per_week: Number(v.calendar.days_per_week) }
    : { linked: true };
  const label = String(v?.label || "").trim().replace(/\s+/g, " ");
  return { clock: v?.clock === "calendar" ? "calendar" : "operating", ...(label ? { label } : {}), start: v?.start || "now", calendar: cal,
    from: v?.from === "today" ? "today" : "new" };
}

// A saved setup (the API's) as the form edits it.
export function setupForm(saved) {
  if (!saved) return { ...DEFAULT_SETUP };
  const cal = saved.calendar?.linked ? { linked: true }
    : { linked: false, hours_per_day: saved.calendar?.hours_per_day ?? 8, days_per_week: saved.calendar?.days_per_week ?? 5 };
  return { clock: clockOf(saved), label: saved.label || "", start: saved.start || "now", calendar: cal, from: saved.from || "new" };
}

export const sameSetup = (a, b) => JSON.stringify(setupBody(a)) === JSON.stringify(setupBody(b));

// What a new mission can run on, from the tree (graftMissions' rows): each saved, non-repairable
// RBD on this position or one below it ("Pump station RBD · at Pump station"), the position's own
// tree in series when it has positions inside, and its own model in use when it has none (a leaf).
// [{value, label, hint}]: value "rbd:<link id>", "tree" or "model".
export function runsOnOptions(rows, positionKey) {
  const out = [];
  const top = rows?.get(positionKey);
  if (!top) return out;
  const stack = [positionKey];
  while (stack.length) {
    const r = rows.get(stack.pop());
    if (!r || r.type !== "pos") continue;
    for (const l of r.rbds || []) {
      if (!l.rbd || l.rbd.mission_rbd || l.rbd.repairable || l.rbd.network) continue;
      out.push({ value: `rbd:${l.link_id}`, label: l.rbd.name, hint: r.key === positionKey ? "On this position" : `At ${r.ref?.name || "a position below"}` });
    }
    for (const k of [...(r.kids || [])].reverse()) stack.push(k);
  }
  const inside = (top.kids || []).some((k) => rows.get(k)?.type === "pos") || top.inside;
  if (inside) out.push({ value: "tree", label: "Its positions, in series", hint: "Every position inside, in series: rewire its RBD where some back each other up" });
  else if (top.hasModel) out.push({ value: "model", label: "Its model in use", hint: "One block: this position's own life or covariate model" });
  return out;
}

// The create body's runs-on part, from a runsOnOptions value.
export function runsOnBody(value) {
  if (String(value || "").startsWith("rbd:")) return { linkId: value.slice(4) };
  if (value === "tree") return { tree: true };
  return {};
}

// ---- the two answers, in words --------------------------------------------------------------------

// "About 97 in 100 missions like this finish without a system failure."
// `clock` (the answers' clock): the mission's length on it, "(10 flight hours)".
export function chanceSentence(chance, clock = null) {
  const r = Number(chance?.value);
  if (chance?.value == null || !Number.isFinite(r)) return "";
  const inHundred = r >= 0.995 ? "Almost all" : r < 0.005 ? "Almost none" : `About ${Math.round(r * 100)} in 100`;
  const on = clock ? ` (${missionLength(clock)})` : "";
  return `${inHundred} missions like this${on} finish without a system failure.`;
}

// A mission's length on its clock: "10 flight hours"; calendar time "12 months".
export function missionLength(clock) {
  if (!clock) return "";
  if (clock.kind === "calendar" && clock.calendar_length) return `${fmt(clock.calendar_length.value)} ${clock.calendar_length.unit}`;
  return `${fmt(clock.length)} ${clock.label}`;
}

// The chance's figure line: "chance of completing a 10 flight-hour mission" (a 12-month one).
export function chanceOf(clock) {
  if (!clock) return "chance of completing the mission";
  const [n, ...rest] = missionLength(clock).split(" ");
  const words = rest.join(" ");
  const singular = words.endsWith("s") ? words.slice(0, -1) : words;
  return `chance of completing a ${n}-${singular.replace(/ /g, "-")} mission`;
}

// A phase's duration on the mission's clock: operating units as stored; on calendar time, in the
// mission's calendar unit through its duty (`perDay`: the RBD's units a day). {value, unit}.
const DAYS = { days: 1, weeks: 7, months: 365.25 / 12, years: 365.25 };
export function phaseShown(duration, { clock = "operating", perDay = null, calUnit = "days", unit = "", label = "" } = {}) {
  const d = Number(duration);
  if (clock === "calendar" && perDay > 0 && Number.isFinite(d)) return { value: d / perDay / DAYS[calUnit], unit: calUnit };
  return { value: Number.isFinite(d) ? d : null, unit: label || unit };
}
// And back: a duration typed on the calendar, in the RBD's running units (a string, as the editor keeps them).
export function phaseStored(typed, { clock = "operating", perDay = null, calUnit = "days" } = {}) {
  if (clock !== "calendar" || !(perDay > 0) || typed === "" || !Number.isFinite(Number(typed))) return typed;
  return String(Number((Number(typed) * DAYS[calUnit] * perDay).toPrecision(10)));
}

// The bound, in words: "At least 95.2% (90% one-sided lower bound)", or why there's none.
export function boundText(chance) {
  const lb = chance?.lower_bound;
  if (lb?.lower != null) return `At least ${pct(lb.lower)} (${Math.round((lb.confidence || 0.9) * 100)}% one-sided lower bound)`;
  return chance?.bound_note || "";
}

// "Expect about 0.6 part failures over the 30 hours (90% range: 0 to 2, two-sided)."
export function failuresSentence(failures, length, unit, clock = null) {
  const e = failures?.expected;
  if (e == null) return failures?.note || "";
  const n = Number(e);
  const what = n === 1 ? "part failure" : "part failures";
  const range = failures.range ? ` ${rangeSentence(failures.range)}` : "";
  return `Expect about ${fmt(n)} ${what} over the ${clock ? missionLength(clock) : lengthText(length, unit)}.${range}`;
}

// A count's 90% two-sided range in words: "In 90 of 100 missions like this, between 1 and 4
// (two-sided)". When it collapses to 0 to 0, plainly, from the share of missions with a failure:
// "In more than 9 of 10 missions like this, nothing fails; about 1 in 43 has a failure."
export function rangeSentence(range) {
  if (!range) return "";
  if (Number(range.upper) === 0) {
    const p = Number(range.p_any);
    if (!(p > 0)) return `None of the ${(range.runs || 0).toLocaleString("en-AU")} simulated missions had a failure.`;
    return `In more than 9 of 10 missions like this, nothing fails; about 1 in ${Math.round(1 / p).toLocaleString("en-AU")} has a failure.`;
  }
  return `In 90 of 100 missions like this, between ${fmt(range.lower)} and ${fmt(range.upper)} (two-sided).`;
}

// The range beside the card's figure: "90% range 1 to 4 (two-sided)", or "nothing fails in more than 9 of 10".
export function rangeShort(range) {
  if (!range) return "";
  return Number(range.upper) === 0 ? "nothing fails in more than 9 of 10 missions"
    : `90% range ${fmt(range.lower)} to ${fmt(range.upper)} (two-sided)`;
}

// "1 Dec 2026 to about 1 Dec 2027 · at 8 h a day" (or the start alone when it can't be put on the calendar).
export function calendarText(cal) {
  if (!cal?.start) return "";
  const from = formatDate(cal.start);
  const how = cal.clock?.text ? ` · ${cal.clock.text}` : "";
  return cal.end ? `${from} to about ${formatDate(cal.end)}${how}` : `From ${from}${how}`;
}
