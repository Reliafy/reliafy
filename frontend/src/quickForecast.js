// The quick forecast tool as a sentence (Decisions › Forecasts; forecast plan step 1, Nov 2026).
// "[1] unit, running [12 h a week], over the next [12 months]", then two optional clauses, at least
// one filled in: work on a schedule (a certain count, no model) and a part that fails (the saved-fleet
// engine). Each view asks only its own extra: "each time" and "if it fails" are hours on the Hours
// view, a cost on the Costs view and spares on the Spares view; a value typed in one view is kept in
// the others. The answer updates as you type (POST /api/fleet/quick-forecast); nothing is saved.
// These are the page's pure parts, tested in quickForecast.test.js; drawn by views/ForecastTool.jsx.

import { parseAges } from "./sparesForecast.js";

export const RUNNING = [
  { value: "all", label: "all the time" },
  { value: "day", label: "h a day" },
  { value: "week", label: "h a week" },
];
export const WORK_UNITS = ["hours", "days", "weeks", "months", "years"];
export const EFFECTS = [
  { value: "none", label: "doesn't change the part's life" },
  { value: "replaces", label: "replaces the part" },
  { value: "supports", label: "keeps the part on its life (supporting)" },
];
// A supporting work's what-if (forecast plan step 7): as planned, stretched to another interval, or not done.
export const WHATIFS = [
  { value: "", label: "as planned" },
  { value: "stretch", label: "stretched to…" },
  { value: "drop", label: "not done" },
];
export const HORIZON_OPTIONS = [
  { value: "12", label: "12 months" }, { value: "24", label: "2 years" },
  { value: "36", label: "3 years" }, { value: "60", label: "5 years" },
];

export const BLANK_WORK = { name: "", every: "", unit: "hours", effect: "none", onReplace: "restart", hoursEach: "", costEach: "", sparesEach: "", spareName: "",
  impactK: "", grace: "", whatif: "", whatifEvery: "" };
// When the part is replaced (forecast-rules 1.8): restart (age replacement) or keep (block replacement).
export const ON_REPLACE = [
  { value: "restart", label: "Restart its schedule (age replacement)" },
  { value: "keep", label: "Keep its schedule (block replacement)" },
];
export const BLANK = {
  units: "1", runPer: "all", runHours: "", horizon: "12",
  work: null, part: false, ages: "", partUnit: "hours", hoursIfFails: "", costIfFails: "", spareCost: "", usePerDay: "", spares: {},
};
// The units a typed life (and its age) can be in; hours by default. A saved model brings its own.
export const PART_UNITS = ["hours", "days", "weeks", "months", "years", "cycles", "starts", "km", "miles", "operations"];

const num = (v) => (String(v ?? "").trim() === "" ? null : Number(String(v).replace(/,/g, "")));
const HOURS = new Set(["h", "hr", "hrs", "hour", "hours", "operating hours", "running hours"]);
const CALENDAR = new Set(["day", "days", "week", "weeks", "month", "months", "year", "years"]);
export const isHours = (unit) => HOURS.has(String(unit || "").trim().toLowerCase());
export const isCalendar = (unit) => CALENDAR.has(String(unit || "").trim().toLowerCase());

// What blocks a calculation, field by field: [{field, text}] (empty: ready). `field` names the input to mark
// and focus (ForecastTool.jsx gives each that id: "ft-<field>"). Calculate is never disabled for these:
// pressed, it says them beside their fields.
export function problems(f, model, unit) {
  const out = [];
  const add = (field, text) => out.push({ field, text });
  if (!f.work && !f.part) add("add", "Add work on a schedule, or a part that fails.");
  if (!(Number(f.units) >= 1) || !Number.isInteger(Number(f.units))) add("units", "Enter how many units: a whole number, 1 or more.");
  if (f.runPer !== "all") {
    const h = num(f.runHours);
    const most = f.runPer === "day" ? 24 : 168;
    if (!(h > 0)) add("runHours", `Enter the hours it runs a ${f.runPer}, or choose all the time.`);
    else if (h > most) add("runHours", `It can't run more than ${most} h a ${f.runPer}.`);
  }
  if (f.work) {
    if (!(num(f.work.every) > 0)) add("every", "Enter how often the work is done.");
    if (f.work.effect === "replaces" && !f.part) add("effect", "Work that replaces the part needs a part that fails.");
    if (f.work.effect === "supports" && f.part && f.work.impactK !== "" && !(num(f.work.impactK) >= 1)) {
      add("impact", "The impact is × 1 or more: how many times the failure rate while it isn't done.");
    }
    if (f.part && f.work.effect === "supports" && f.work.whatif === "stretch" && !(num(f.work.whatifEvery) > 0)) {
      add("whatifEvery", "Enter the interval to stretch it to.");
    }
  }
  if (f.part) {
    if (!model) add("life", "Pick a saved model, or type the distribution's parameters.");
    else if (!unit) add("unit", "Pick the unit of its age and its life.");
    const a = parseAges(f.ages);
    if (a.error) add("age", "Enter how old it is now: one age, or one per unit under More options.");
    if (unit && !isHours(unit) && !isCalendar(unit) && !(num(f.usePerDay) > 0)) {
      add("usePerDay", `Enter the ${unit} a unit adds a day.`);
    }
  }
  return out;
}

// The first thing that blocks a calculation, in words (null: ready).
export function missing(f, model, unit) {
  return problems(f, model, unit)[0]?.text || null;
}

// The request (POST /api/fleet/quick-forecast). `start` (an ISO date): today where the user is.
export function requestOf(f, model, unit, start = null) {
  const body = {
    units: Number(f.units), months: Number(f.horizon),
    running: f.runPer === "all" ? { all_the_time: true } : { hours: num(f.runHours), per: f.runPer },
  };
  if (start) body.start = start;
  if (f.work) {
    const w = f.work;
    body.work = {
      name: w.name.trim() || "The work", every: num(w.every), unit: w.unit, effect: f.part ? w.effect : "none",
      on_replace: w.onReplace || "restart",
      hours_each: num(w.hoursEach), cost_each: num(w.costEach), spares_each: num(w.sparesEach),
      spare_name: w.spareName.trim() || null,
    };
    if (f.part && w.effect === "supports") {
      body.work.impact_k = num(w.impactK);
      body.work.grace = num(w.grace);
      const stretched = w.whatif === "stretch" && num(w.whatifEvery) > 0 ? { interval: num(w.whatifEvery) } : null;
      body.work.whatif = w.whatif === "drop" ? { drop: true } : stretched;
    }
  }
  if (f.part && model) {
    const { ages } = parseAges(f.ages);
    body.part = {
      distribution_id: model.distribution_id, params: model.params, extras: model.extras || null,
      unit, name: model.name || "The part",
      ...(ages.length === 1 ? { age: ages[0] } : { ages }),
      hours_if_fails: num(f.hoursIfFails), cost_if_fails: num(f.costIfFails), spare_cost: num(f.spareCost),
      use_per_day: num(f.usePerDay),
    };
    if (ages.length > 1) body.units = ages.length;
    const spares = f.spares && Object.values(f.spares).some((v) => v != null && v !== "") ? f.spares : null;
    if (spares) body.spares = spares;
  }
  return body;
}

const sig = (v, n = 3) => Number(v).toLocaleString("en-GB", { maximumSignificantDigits: n });
const rangeOf = (b, fmt) => (b?.interval ? `${fmt(b.interval[0])} to ${fmt(b.interval[1])}` : null);
const KIND_WORDS = {
  certain: "Certain: a schedule, no chance involved",
  "worked out": "Worked out exactly, not simulated",
  simulated: "Simulated",
};
export const kindWords = (line) => line.method || KIND_WORDS[line.number] || line.number;

// The view's key in a line and the totals (Hours view → hours; Costs → cost; Spares → spares).
export const viewKey = (view) => (view === "hours" ? "hours" : view === "costs" ? "cost" : "spares");

// The horizon in words: "the next 12 months", "the next 2 years".
export const horizonWords = (months) => {
  const m = Number(months);
  return m % 12 === 0 && m > 12 ? `the next ${m / 12} years` : `the next ${m} months`;
};

// The answer first, for a view: {lead, detail [{label, value}] (the tiles), known, leavesOut[]}. `money(v)` formats a cost.
export function answerOf(out, view, money = (v) => `$${sig(v, 4)}`) {
  const when = horizonWords(out.months);
  const fail = out.lines.find((l) => l.owner_kind === "failure");
  const work = out.lines.find((l) => l.owner_kind === "task");
  const key = viewKey(view);
  const detail = [];
  if (key === "spares") {
    const items = out.totals.spares.items || [];
    if (!items.length) {
      return { lead: work ? `${sig(work.times.expected)} times in ${when}: no spares given for it.` : `No spares in ${when}.`,
        detail, known: false, leavesOut: out.totals.spares.leaves_out || [] };
    }
    // Plain: "About 99 spares in the next 12 months (90% range: 91–107)." The part's name, when the user gave
    // it, goes on the line below (Answer), not in brackets here.
    const chance = items.filter((x) => x.number !== "certain");
    const certain = items.filter((x) => x.number === "certain");
    const about = (v) => (v >= 10 ? Math.round(v).toLocaleString("en-GB") : sig(v, 2));
    const bits = [];
    let range = "";
    if (chance.length) {
      const total = chance.reduce((t, x) => t + Number(x.expected || 0), 0);
      bits.push(`About ${about(total)} ${Math.abs(total - 1) < 1e-9 ? "spare" : "spares"}`);
      const iv = chance.length === 1 ? chance[0].interval : null;
      if (iv) range = ` (90% range${certain.length ? " for the spares" : ""}: ${sig(iv[0])}–${sig(iv[1])})`;
    }
    for (const x of certain) bits.push(`${sig(x.expected)} × ${x.name}`);
    return { lead: `${bits.join(" and ")} in ${when}${range}.`, detail, known: out.totals.spares.known, leavesOut: out.totals.spares.leaves_out || [] };
  }
  const t = out.totals[key];
  const fmt = key === "hours" ? (v) => `${sig(v)} h` : money;
  if (!t || t.expected == null) {
    return { lead: key === "hours" ? "No hours given: enter the hours each time or if it fails." : "No costs given: enter the cost each time or if it fails.",
      detail, known: false, leavesOut: t?.leaves_out || [] };
  }
  const one = fail && out.units === 1 && fail.times.probability != null && fail.times.expected < 1;
  let lead;
  if (!fail && work) {
    lead = `${sig(work.times.expected)} times in ${when}: ${fmt(t.expected)}.`;
  } else if (one && !work) {
    lead = `${Math.round(fail.times.probability * 100)}% chance it fails in ${when}: ${fmt(t.expected)} expected.`;
  } else {
    lead = `${fmt(t.expected)} expected in ${when}${t.known ? "" : " (known " + (key === "hours" ? "hours" : "costs") + ")"}.`;
  }
  if (fail) {
    const r = rangeOf(t, fmt);
    if (r) detail.push({ label: "Likely range (90% two-sided)", value: r });
    detail.push({ label: "Failures expected", value: sig(fail.times.expected) });
    if (fail.times.probability != null && out.units === 1) {
      detail.push({ label: "Chance of one or more", value: `${Math.round(fail.times.probability * 100)}%` });
    }
  }
  return { lead, detail, known: t.known, leavesOut: t.leaves_out || [] };
}

// "90% chance of no failure before month 2" (90% one-sided), from the part's life bound.
export function boundText(out) {
  const b = out?.no_failure_before;
  if (!b || b.days == null) return null;
  const months = b.days / 30.4375;
  const when = months < 1 ? `${sig(b.days, 2)} days` : `month ${Math.floor(months) + 1}`;
  return `90% chance of no failure before ${when} (90% one-sided).`;
}

// One line's cells for a view: the times and the view's amount, in words.
export function lineCells(line, view, money = (v) => `$${sig(v, 4)}`) {
  const t = line.times || {};
  const times = line.number === "certain" ? sig(t.expected)
    : `${sig(t.expected)} expected${t.interval ? ` (${sig(t.interval[0])} to ${sig(t.interval[1])})` : ""}`;
  const key = viewKey(view);
  const v = line[key];
  const gap = (line.gaps || []).find((g) => g.view === key);
  const fmt = key === "hours" ? (x) => `${sig(x)} h` : key === "cost" ? money : (x) => sig(x);
  const amount = gap ? null : v == null ? null : line.number === "certain" || !v.interval ? fmt(v.expected)
    : `${fmt(v.expected)} (${fmt(v.interval[0])} to ${fmt(v.interval[1])})`;
  return { times, amount, gap: gap ? gap.text : null };
}

// The rows by period for the chart and the table: [{period, work, failures, value, low, high}] for a
// view. The certain work is added to both ends of the part's range in each period.
export function seriesOf(out, view) {
  const key = viewKey(view);
  const engine = out.part?.views;
  const work = out.lines.find((l) => l.owner_kind === "task" && l.number === "certain");
  const sparesEach = work?.spares && work.times.expected ? work.spares.expected / work.times.expected : 0;
  return out.rows.map((r, i) => {
    const eng = key === "hours" ? engine?.hours?.per_period?.[i]?.hours : key === "cost" ? engine?.costs?.per_period?.[i]?.cost
      : out.part?.strategy?.per_period?.[i]?.parts;
    const value = key === "spares" ? r.work * sparesEach + (eng?.expected ?? 0) : r[key] ?? 0;
    const certain = value - (eng?.expected ?? 0);
    const low = eng?.interval ? certain + eng.interval[0] : value;
    const high = eng?.interval ? certain + eng.interval[1] : value;
    return { period: r.period, work: r.work, failures: r.failures, value, low: Math.max(0, low), high };
  });
}

// A what-if beside the answer (supporting work here, or the Explorer's supporting tasks): the view's
// figure as planned and with the change, and the difference. `a`, `b`: {expected} blocks, or null.
export function changeText(a, b, view, money = (v) => `$${sig(v, 4)}`) {
  if (!a || !b || a.expected == null || b.expected == null) return null;
  const fmt = view === "hours" ? (v) => `${sig(v)} h` : view === "costs" ? money : (v) => sig(v);
  const d = b.expected - a.expected;
  const sign = d > 0 ? "+" : d < 0 ? "less " : "";
  return { planned: fmt(a.expected), changed: fmt(b.expected), diff: d === 0 ? "no change" : `${sign}${fmt(Math.abs(d))}` };
}
