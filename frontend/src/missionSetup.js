// A mission's setup and its two answers, in words (the Explorer's Missions tab, 23 Nov 2026).
// Pure functions, tested in missionSetup.test.js; drawn by MissionSetup.jsx, NewMissionPane and
// MissionAnswers.jsx. The answers come from POST /api/rbds/{id}/missions/{mission}/answers
// (backend/services/mission_answers.py).

import { fmt, lengthText, pct } from "./explorerMissions.js";
import { formatDate } from "./dates.js";

export const DEFAULT_SETUP = Object.freeze({ start: "now", calendar: { linked: true }, from: "new" });
export const NEW_LENGTH = Object.freeze({ value: "", unit: "months" });

const num = (v) => (v === "" || v == null ? NaN : Number(v));

// What's wrong with a setup, per field ({start?, length?, calendar?}); {} when it can be saved.
export function setupErrors(v, { withLength = false } = {}) {
  const out = {};
  if (v?.start !== "now" && !/^\d{4}-\d{2}-\d{2}$/.test(String(v?.start || ""))) out.start = "Pick the day it starts, or Now.";
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
  return { start: v?.start || "now", calendar: cal, from: v?.from === "today" ? "today" : "new" };
}

// A saved setup (the API's) as the form edits it.
export function setupForm(saved) {
  if (!saved) return { ...DEFAULT_SETUP };
  const cal = saved.calendar?.linked ? { linked: true }
    : { linked: false, hours_per_day: saved.calendar?.hours_per_day ?? 8, days_per_week: saved.calendar?.days_per_week ?? 5 };
  return { start: saved.start || "now", calendar: cal, from: saved.from || "new" };
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
export function chanceSentence(chance) {
  const r = Number(chance?.value);
  if (chance?.value == null || !Number.isFinite(r)) return "";
  const inHundred = r >= 0.995 ? "Almost all" : r < 0.005 ? "Almost none" : `About ${Math.round(r * 100)} in 100`;
  return `${inHundred} missions like this finish without a system failure.`;
}

// The bound, in words: "At least 95.2% (90% one-sided lower bound)", or why there's none.
export function boundText(chance) {
  const lb = chance?.lower_bound;
  if (lb?.lower != null) return `At least ${pct(lb.lower)} (${Math.round((lb.confidence || 0.9) * 100)}% one-sided lower bound)`;
  return chance?.bound_note || "";
}

// "Expect about 0.6 part failures over the 30 hours (90% range: 0 to 2, two-sided)."
export function failuresSentence(failures, length, unit) {
  const e = failures?.expected;
  if (e == null) return failures?.note || "";
  const n = Number(e);
  const what = n === 1 ? "part failure" : "part failures";
  const range = failures.range
    ? ` In 90 of 100 missions like this, between ${fmt(failures.range.lower)} and ${fmt(failures.range.upper)} (two-sided).` : "";
  return `Expect about ${fmt(n)} ${what} over the ${lengthText(length, unit)}.${range}`;
}

// "1 Dec 2026 to about 1 Dec 2027 · at 8 h a day" (or the start alone when it can't be put on the calendar).
export function calendarText(cal) {
  if (!cal?.start) return "";
  const from = formatDate(cal.start);
  const how = cal.clock?.text ? ` · ${cal.clock.text}` : "";
  return cal.end ? `${from} to about ${formatDate(cal.end)}${how}` : `From ${from}${how}`;
}
