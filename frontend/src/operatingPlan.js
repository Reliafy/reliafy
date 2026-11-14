// An operating plan: how a position runs (backend/maintenance/operating_plan.py holds the
// saved shape and the same arithmetic). Pure: no React, so the tests can hold it.
//
//   {version: 1,
//    background: {kind: "shifts", shifts: [{days: ["Monday", ...], start: "06:00", stop: "22:00"}]}
//              | {kind: "roster", on: 4, off: 4, anchor: "2026-11-16", start: "07:00", stop: "19:00"}
//              | {kind: "rate", amount: 3, per: "day", meter: "hours"}
//              | {kind: "runs", runs: [["2026-11-14T12:31", "2026-11-15T03:27"], ...]}
//              | {kind: "continuous"},
//    specific: [{kind: "runs", runs: [[on, off], ...], covers: [from, to]}]}
//
// The hours shown ("about 80 hours a week", the strip of the next two weeks) are a simple
// in-app summary in clock hours, until the scheduling library's forecast replaces them. One
// rule already holds (Derryn, 14 Nov 2026): where specific runs hand over to the background,
// the background counts only the time the runs don't cover, pro rata, so no hours appear or
// vanish at the handover and each day's total is the sum of its parts.

export const PLAN_KINDS = [
  ["shifts", "Repeating week", "The same clock times each week: Monday to Friday, 06:00 to 22:00"],
  ["roster", "Roster", "Days on and days off: 4 on, 4 off, 07:00 to 19:00"],
  ["rate", "Rate", "A rough amount of running: about 3 hours a day"],
  ["runs", "Runs", "Only the runs you list, each an on and an off time"],
  ["continuous", "All the time", "Runs around the clock"],
];
export const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
export const RATE_PER = { day: 1, week: 7, month: 365.25 / 12, year: 365.25 };
const DAY_MS = 86400000;

// ---- moments: wall-clock times as minutes, with no time zone ------------------------------

const MOMENT = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})/;
const DAY_FIRST = /^(\d{1,2})\/(\d{1,2})\/(\d{4})[ T]+(\d{1,2}):(\d{2})/;

// "2026-11-14T12:31" (or "2026-11-14 12:31", or "14/11/2026 12:31") as ms, or null.
export function parseMoment(text) {
  const s = String(text || "").trim();
  let m = MOMENT.exec(s);
  let y; let mo; let d; let h; let mi;
  if (m) [, y, mo, d, h, mi] = m.map(Number);
  else if ((m = DAY_FIRST.exec(s))) [, d, mo, y, h, mi] = m.map(Number);
  else return null;
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 24 || mi > 59) return null;
  const t = Date.UTC(y, mo - 1, d, h, mi);
  return new Date(t).getUTCDate() === d || h === 24 ? t : null;
}
const pad = (n) => String(n).padStart(2, "0");
export function momentText(ms) {
  const d = new Date(ms);
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}
const dayMs = (iso) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)));
const clockMs = (hhmm) => (Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5))) * 60000;
const isoDay = (ms) => momentText(ms).slice(0, 10);
const weekdayOf = (ms) => (new Date(ms).getUTCDay() + 6) % 7;

// Pasted or imported runs: a line each, on then off (a comma, a tab or a semicolon between).
// A first line that isn't two times is taken as a heading. {runs, problems}.
export function parseRuns(text) {
  const runs = [];
  const problems = [];
  const lines = String(text || "").split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  lines.forEach((line, i) => {
    const cells = line.split(/\t|;|,(?=\s*\d)/).map((c) => c.trim()).filter(Boolean);
    const on = parseMoment(cells[0]);
    const off = parseMoment(cells[1]);
    if (on == null || off == null) {
      if (i === 0 && !/\d{4}|\d\/\d/.test(cells[0] || "")) return; // a heading row
      problems.push(`Line ${i + 1}: give an on and an off time, like 2026-11-14 12:31, 2026-11-15 03:27.`);
      return;
    }
    if (off <= on) {
      problems.push(`Line ${i + 1}: the off time must be after the on time.`);
      return;
    }
    runs.push([on, off]);
  });
  runs.sort((a, b) => a[0] - b[0]);
  for (let k = 1; k < runs.length; k += 1) {
    if (runs[k][0] < runs[k - 1][1]) {
      problems.push(`Two runs overlap: ${momentText(runs[k - 1][0]).replace("T", " ")} to ${momentText(runs[k - 1][1]).replace("T", " ")} and ${momentText(runs[k][0]).replace("T", " ")} onwards.`);
    }
  }
  return { runs: runs.map(([a, b]) => [momentText(a), momentText(b)]), problems };
}
export const runsText = (runs = []) => runs.map(([a, b]) => `${a.replace("T", " ")}, ${b.replace("T", " ")}`).join("\n");

// ---- the form ------------------------------------------------------------------------------

export function formFromPlan(brief, today) {
  const p = brief?.plan;
  const bg = p?.background || { kind: "shifts", shifts: [{ days: WEEKDAYS.slice(0, 5), start: "06:00", stop: "22:00" }] };
  const specific = p?.specific || [];
  return {
    kind: bg.kind,
    shifts: bg.kind === "shifts" ? bg.shifts.map((s) => ({ ...s, days: [...s.days] }))
      : [{ days: WEEKDAYS.slice(0, 5), start: "06:00", stop: "22:00" }],
    roster: bg.kind === "roster" ? { on: String(bg.on), off: String(bg.off), anchor: bg.anchor, start: bg.start, stop: bg.stop }
      : { on: "4", off: "4", anchor: today, start: "07:00", stop: "19:00" },
    rate: bg.kind === "rate" ? { amount: String(bg.amount), per: bg.per } : { amount: "3", per: "day" },
    runs: bg.kind === "runs" ? runsText(bg.runs) : "",
    specific: runsText(specific.flatMap((s) => s.runs)),
    name: brief?.name || "", from: today, notes: brief?.notes || "",
  };
}

const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;

// The plan the form says, or {problem}.
export function planFromForm(form) {
  let background;
  if (form.kind === "continuous") background = { kind: "continuous" };
  else if (form.kind === "shifts") {
    if (!form.shifts.length) return { problem: "Add a shift." };
    for (const [i, s] of form.shifts.entries()) {
      if (!s.days.length) return { problem: `Shift ${i + 1}: tick the days it runs.` };
      if (!CLOCK.test(s.start) || !CLOCK.test(s.stop)) return { problem: `Shift ${i + 1}: times are like 06:00.` };
      if (s.start === s.stop) return { problem: `Shift ${i + 1}: the start and stop are the same. For all day, pick All the time.` };
    }
    background = { kind: "shifts", shifts: form.shifts.map((s) => ({ days: WEEKDAYS.filter((d) => s.days.includes(d)), start: s.start, stop: s.stop })) };
    const clash = shiftClash(background);
    if (clash) return { problem: clash };
  } else if (form.kind === "roster") {
    const r = form.roster;
    if (!(Number.isInteger(Number(r.on)) && Number(r.on) >= 1)) return { problem: "Days on is a whole number, 1 or more." };
    if (!(Number.isInteger(Number(r.off)) && Number(r.off) >= 0)) return { problem: "Days off is a whole number, 0 or more." };
    if (!/^\d{4}-\d{2}-\d{2}$/.test(r.anchor || "")) return { problem: "Say the first day on." };
    if (!CLOCK.test(r.start) || !CLOCK.test(r.stop)) return { problem: "Times are like 07:00." };
    background = { kind: "roster", on: Number(r.on), off: Number(r.off), anchor: r.anchor, start: r.start, stop: r.stop };
  } else if (form.kind === "rate") {
    const n = Number(form.rate.amount);
    if (!(n > 0)) return { problem: "Say about how many hours it runs: a number more than 0." };
    if (n > 24 * RATE_PER[form.rate.per]) return { problem: `There are only ${Math.round(24 * RATE_PER[form.rate.per]).toLocaleString("en-GB")} hours in a ${form.rate.per}.` };
    background = { kind: "rate", amount: n, per: form.rate.per, meter: "hours" };
  } else {
    const { runs, problems } = parseRuns(form.runs);
    if (problems.length) return { problem: problems[0] };
    if (!runs.length) return { problem: "List at least one run: an on and an off time on each line." };
    background = { kind: "runs", runs };
  }
  const plan = { version: 1, background, specific: [] };
  if (form.kind !== "runs" && form.specific.trim()) {
    const { runs, problems } = parseRuns(form.specific);
    if (problems.length) return { problem: problems[0] };
    if (runs.length) {
      const first = runs[0][0].slice(0, 10);
      plan.specific = [{ kind: "runs", runs, covers: [`${first}T00:00`, runs[runs.length - 1][1]] }];
    }
  }
  return { plan };
}

// ---- the hours -----------------------------------------------------------------------------

function dayShifts(bg, day) {
  let found;
  if (bg.kind === "shifts") found = bg.shifts.filter((s) => s.days.includes(WEEKDAYS[weekdayOf(day)]));
  else {
    const cycle = bg.on + bg.off;
    const k = (((Math.round((day - dayMs(bg.anchor)) / DAY_MS)) % cycle) + cycle) % cycle;
    found = k < bg.on ? [bg] : [];
  }
  return found.map((s) => {
    const a = day + clockMs(s.start);
    let b = day + clockMs(s.stop);
    if (b <= a) b += DAY_MS;
    return [a, b];
  });
}

function shiftClash(bg) {
  const monday = Date.UTC(2024, 0, 1);
  const runs = [];
  for (let k = 0; k < 8; k += 1) runs.push(...dayShifts(bg, monday + k * DAY_MS));
  runs.sort((a, b) => a[0] - b[0]);
  for (let k = 1; k < runs.length; k += 1) {
    if (runs[k][0] < runs[k - 1][1]) return `Two shifts overlap on ${WEEKDAYS[weekdayOf(runs[k][0])]}: the same hour can't count twice.`;
  }
  return null;
}

const clip = (list, lo, hi) => list.filter(([a, b]) => b > lo && a < hi).map(([a, b]) => [Math.max(a, lo), Math.min(b, hi)]);
function minus(lo, hi, covers) {
  let free = [[lo, hi]];
  for (const [c0, c1] of covers) {
    const next = [];
    for (const [a, b] of free) {
      if (c1 <= a || c0 >= b) { next.push([a, b]); continue; }
      if (a < c0) next.push([a, c0]);
      if (c1 < b) next.push([c1, b]);
    }
    free = next;
  }
  return free;
}
const hoursOf = (list) => list.reduce((t, [a, b]) => t + (b - a), 0) / 3600000;

// What runs on one day: runs as hours from midnight (each specific or background), `spread` (a
// rate's hours over the day's uncovered time) and `hours` in all.
export function dayRuns(plan, isoDate) {
  const lo = dayMs(isoDate);
  const hi = lo + DAY_MS;
  const toMs = (runs) => runs.map(([a, b]) => [parseMoment(a), parseMoment(b)]);
  const covers = (plan.specific || []).map((s) => [parseMoment(s.covers[0]), parseMoment(s.covers[1])]);
  const free = minus(lo, hi, covers);
  const out = [];
  for (const s of plan.specific || []) for (const [a, b] of clip(toMs(s.runs), lo, hi)) out.push([a, b, "specific"]);
  const bg = plan.background;
  let spread = 0;
  if (bg.kind === "continuous") for (const [a, b] of free) out.push([a, b, "background"]);
  else if (bg.kind === "shifts" || bg.kind === "roster") {
    const mine = [...dayShifts(bg, lo - DAY_MS), ...dayShifts(bg, lo)];
    for (const run of mine) for (const [f0, f1] of free) for (const [a, b] of clip([run], Math.max(lo, f0), Math.min(hi, f1))) out.push([a, b, "background"]);
  } else if (bg.kind === "runs") for (const [a, b] of clip(toMs(bg.runs), lo, hi)) out.push([a, b, "background"]);
  else spread = (bg.amount / RATE_PER[bg.per]) * (hoursOf(free) / 24);
  out.sort((x, y) => x[0] - y[0]);
  return {
    date: isoDate, spread,
    runs: out.map(([a, b, layer]) => ({ from: (a - lo) / 3600000, to: (b - lo) / 3600000, layer })),
    hours: hoursOf(out) + spread,
  };
}

export function hoursByDay(plan, startIso, days = 14) {
  return Array.from({ length: days }, (_, k) => dayRuns(plan, isoDay(dayMs(startIso) + k * DAY_MS)));
}

// The background's hours in an ordinary week (null for runs only).
export function typicalWeek(plan) {
  const bg = plan.background;
  if (bg.kind === "continuous") return 168;
  if (bg.kind === "rate") return (bg.amount / RATE_PER[bg.per]) * 7;
  if (bg.kind === "shifts") {
    const monday = Date.UTC(2024, 0, 1);
    let t = 0;
    for (let k = 0; k < 7; k += 1) t += hoursOf(dayShifts(bg, monday + k * DAY_MS));
    return t;
  }
  if (bg.kind === "roster") {
    const [[a, b]] = dayShifts({ ...bg, on: 1, off: 0, anchor: "2024-01-01" }, Date.UTC(2024, 0, 1));
    return hoursOf([[a, b]]) * 7 * bg.on / (bg.on + bg.off);
  }
  return null;
}

// "about 80 hours a week" (whole hours from 10 up; one decimal below).
export function hoursWords(h) {
  if (h == null) return "";
  const r = h >= 10 ? Math.round(h) : Math.round(h * 10) / 10;
  return `about ${r.toLocaleString("en-GB")} hour${r === 1 ? "" : "s"} a week`;
}
const hrs = (h) => {
  const r = h >= 10 ? Math.round(h) : Math.round(h * 10) / 10;
  return `${r.toLocaleString("en-GB")} h`;
};
export { hrs as hoursShort };

// The plan in words: "Monday to Friday, 06:00 to 22:00", "3 hours a day".
export function planWords(plan) {
  const bg = plan.background;
  let text;
  if (bg.kind === "continuous") text = "All the time";
  else if (bg.kind === "rate") text = `About ${bg.amount.toLocaleString("en-GB")} hours a ${bg.per}`;
  else if (bg.kind === "roster") text = `${bg.on} days on, ${bg.off} off, ${bg.start} to ${bg.stop}`;
  else if (bg.kind === "runs") text = `${bg.runs.length} run${bg.runs.length === 1 ? "" : "s"} only`;
  else {
    text = bg.shifts.map((s) => {
      const idx = s.days.map((d) => WEEKDAYS.indexOf(d));
      const run = idx.length > 2 && idx.every((v, i) => i === 0 || v === idx[i - 1] + 1);
      return `${run ? `${s.days[0]} to ${s.days[s.days.length - 1]}` : s.days.map((d) => d.slice(0, 3)).join(", ")}, ${s.start} to ${s.stop}`;
    }).join("; ");
  }
  const n = (plan.specific || []).reduce((t, s) => t + s.runs.length, 0);
  if (n) text += `; ${n} set run${n === 1 ? "" : "s"} first`;
  return text;
}
