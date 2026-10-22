// Replacement over a shutdown calendar (Strategy › Replacement): the form's
// logic, kept out of the component so it can be tested. The server turns the
// dates into model time with "today = 0"; the form sends dates as given.

export const TIME_UNITS = ["Hours", "Days", "Weeks", "Months", "Years"];
export const EVERY_UNITS = ["days", "weeks", "months", "years"];

export const METHODS = [
  { value: "dp", label: "Exact, on a fine time grid", hint: "Free. Works for any calendar." },
  { value: "integration", label: "Exact, in continuous time", hint: "Free. Only with no replacement between shuts." },
  { value: "sampling", label: "Sampled (Pro)", hint: "For calendars whose pattern takes very long to repeat." },
];

const ALIASES = {
  h: "Hours", hr: "Hours", hrs: "Hours", hour: "Hours", hours: "Hours",
  d: "Days", day: "Days", days: "Days",
  wk: "Weeks", wks: "Weeks", week: "Weeks", weeks: "Weeks",
  mo: "Months", mon: "Months", mth: "Months", mths: "Months", month: "Months", months: "Months",
  y: "Years", yr: "Years", yrs: "Years", year: "Years", years: "Years",
};

// A model's unit as one of TIME_UNITS, or "" when it isn't a unit of time
// (cycles, km) or is blank.
export function timeUnit(unit) {
  const key = String(unit || "").trim().toLowerCase().replace(/\.$/, "");
  return ALIASES[key] || "";
}

const pad = (n) => String(n).padStart(2, "0");

// Today in the viewer's own time zone, as YYYY-MM-DD.
export function localToday(now = new Date()) {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

// "2027-03-17" → "17 Mar 2027" (read as a calendar date: no time zone shift).
export function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}

// Dates typed in a box: one per line or comma-separated, each YYYY-MM-DD.
export function parseDates(text) {
  const parts = String(text || "").split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
  const bad = parts.filter((p) => !/^\d{4}-\d{2}-\d{2}$/.test(p) || Number.isNaN(new Date(`${p}T00:00:00Z`).getTime()));
  return { dates: parts.filter((p) => !bad.includes(p)), bad };
}

export function newShut(today, i = 0) {
  return i === 0
    ? { name: "Annual shutdown", cost: "", how: "every", every: "12", everyUnit: "months", start: today, dates: "" }
    : { name: `Shut ${i + 1}`, cost: "", how: "every", every: "3", everyUnit: "months", start: today, dates: "" };
}

const num = (v) => (v === "" || v == null ? null : Number(v));

// The request body from the form, or { error } saying what's missing.
export function buildRequest({ model, unit, today, shuts, failureCost, anytimeCost, maxAge, method }) {
  if (!model || !model.distribution_id) return { error: "Choose a non-repairable model." };
  if (model.kind === "regression") return { error: "Pick a plain distribution: regression models aren't supported here." };
  if (!timeUnit(unit)) return { error: "Choose the model's time unit: the shut dates are turned into model time with it." };
  if (num(failureCost) == null || !(Number(failureCost) > 0)) return { error: "Enter what a failure costs." };
  const opportunities = [];
  for (const [i, s] of shuts.entries()) {
    const name = String(s.name || "").trim() || `Shut ${i + 1}`;
    if (s.cost === "" || s.cost == null || !(Number(s.cost) >= 0)) return { error: `Enter what replacing at “${name}” costs.` };
    if (s.how === "dates") {
      const { dates, bad } = parseDates(s.dates);
      if (bad.length) return { error: `“${name}”: ${bad[0]} isn't a date (use YYYY-MM-DD).` };
      if (!dates.length) return { error: `“${name}”: list its dates.` };
      opportunities.push({ name, cost: Number(s.cost), dates });
    } else {
      if (!(Number(s.every) > 0)) return { error: `“${name}”: say how often it comes.` };
      opportunities.push({ name, cost: Number(s.cost), every: Number(s.every), every_unit: s.everyUnit || "days",
                           start: s.start || today });
    }
  }
  if (!opportunities.length && num(anytimeCost) == null) {
    return { error: "Add a shut, or a cost for replacing between shuts." };
  }
  return {
    body: {
      distribution_id: model.distribution_id,
      params: model.params,
      extras: model.extras || null,
      unit: timeUnit(unit),
      today,
      opportunities,
      failure_cost: Number(failureCost),
      anytime_cost: num(anytimeCost),
      max_age: num(maxAge),
      method: method || "dp",
    },
  };
}

// The schedule rows shown by default: the shuts the rule uses (``used``, the
// kinds whose rule line says they replace) or where a replacement is likely
// (chance ≥ 0.1%); all of them when none is, or when asked.
export function visibleSchedule(rows, showAll = false, used = []) {
  const list = rows || [];
  if (showAll) return list;
  const likely = list.filter((r) => (r.chance || 0) >= 1e-3 || used.includes(r.kind));
  return likely.length ? likely : list;
}

// "+23%" for how much dearer a rule is than the best.
export function dearer(fraction) {
  if (fraction == null || !Number.isFinite(fraction)) return "—";
  if (Math.abs(fraction) < 0.0005) return "the same";
  const p = fraction * 100;
  return `${p > 0 ? "+" : ""}${Math.abs(p) >= 10 ? Math.round(p) : p.toFixed(1)}%`;
}
