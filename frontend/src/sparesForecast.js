// Decisions › Forecasts: one quick forecast tool with three answers (Derryn, 23 Nov 2026: quick
// one-off work lives in the left menu's tools; the saved work for an asset lives in the Explorer).
// Spares forecast, Hours forecast and Cost forecast are its three views (/forecasts/spares, /hours,
// /costs) over the same inputs: a model picked or typed, units at one age or a list of ages, how
// much they run, a replacement policy, task hours and costs, and a horizon. One call to the
// saved-fleet engine (POST /api/fleet/scratch-forecast) feeds all three; nothing is saved. A node
// in the Explorer can fill it in (Open in ›, ?from=<kind>:<id>&root=<asset>). These are the page's
// pure parts. Tested in sparesForecast.test.js; drawn by views/ForecastTool.jsx.

export const VIEWS = [
  { value: "spares", label: "Spares", path: "/forecasts/spares", title: "Spares forecast",
    purpose: "How many spares a set of units will use over a horizon, and how many to hold: a quick forecast, not saved." },
  { value: "hours", label: "Labour hours", path: "/forecasts/hours", title: "Hours forecast",
    purpose: "The maintenance hours a set of units will need over a horizon: planned task hours plus corrective hours. A quick forecast, not saved." },
  { value: "costs", label: "Costs", path: "/forecasts/costs", title: "Cost forecast",
    purpose: "What a set of units will cost to maintain over a horizon: planned work, corrective work and spares. A quick forecast, not saved." },
];
export const viewOf = (pathname) => VIEWS.find((v) => pathname.startsWith(v.path)) || VIEWS[0];

// A link to the tool on a view, filled in from an Explorer node (kind: position | task | package).
export function toolLink(view = "spares", { kind = null, id = null, root = null } = {}) {
  const q = new URLSearchParams();
  if (kind && id) q.set("from", `${kind}:${id}`);
  if (root) q.set("root", root);
  const text = q.toString();
  return `${(VIEWS.find((v) => v.value === view) || VIEWS[0]).path}${text ? `?${text}` : ""}`;
}
// ?from=position:<id> (or the first links' ?position= / ?task=): {kind, id} or null.
export function fromParam(params) {
  const raw = params.get("from");
  if (raw && /^(position|task|package):./.test(raw)) {
    const at = raw.indexOf(":");
    return { kind: raw.slice(0, at), id: raw.slice(at + 1) };
  }
  if (params.get("task")) return { kind: "task", id: params.get("task") };
  if (params.get("position")) return { kind: "position", id: params.get("position") };
  return null;
}

// The form as it starts (nothing filled in), and as a node's prefill fills it.
export const BLANK_FORM = { ages: "", units: "1", perDay: "", daysWeek: "7", group: "months", horizon: "12", policy: "failure",
  replaceAt: "", failureCost: "", plannedCost: "", plannedHours: "", correctiveHours: "", spareCost: "", spares: {} };
const text = (v) => (v == null ? "" : String(v));
export function formFromStart(start, form = BLANK_FORM) {
  if (!start) return form;
  const ages = start.ages || [];
  return {
    ...form,
    ages: ages.length ? ages.map((a) => String(Math.round(a * 1000) / 1000)).join(", ") : form.ages,
    units: ages.length ? String(ages.length) : start.units ? String(start.units) : form.units,
    perDay: start.hours_per_day != null ? text(start.hours_per_day) : form.perDay,
    policy: start.replace_at != null ? "age" : form.policy,
    replaceAt: start.replace_at != null ? text(start.replace_at) : form.replaceAt,
    plannedCost: start.planned_cost != null ? text(start.planned_cost) : form.plannedCost,
    plannedHours: start.planned_hours != null ? text(start.planned_hours) : form.plannedHours,
    failureCost: start.failure_cost != null ? text(start.failure_cost) : form.failureCost,
  };
}

// Days in a period, as the server's fleet forecast counts them (backend/services/fleet.py).
export const PERIOD_DAYS = { months: 30.4375, quarters: 91.3125, years: 365.25 };
export const HORIZONS = [
  { value: "12", label: "12 months" }, { value: "24", label: "2 years" },
  { value: "36", label: "3 years" }, { value: "60", label: "5 years" },
];
export const GROUPS = [
  { value: "months", label: "Month" }, { value: "quarters", label: "Quarter" }, { value: "years", label: "Year" },
];
const MONTHS_IN = { months: 1, quarters: 3, years: 12 };

// The groupings a horizon can be split into whole (12 months by year: 1).
export const groupsFor = (months) => GROUPS.filter((g) => Number(months) % MONTHS_IN[g.value] === 0);
export const periodsOf = (months, group) => Math.max(1, Math.round(Number(months) / MONTHS_IN[group]));

// Running hours (a unit's use is its hours a day); anything else is a use a day in its own unit.
const HOURS = new Set(["h", "hr", "hrs", "hour", "hours", "operating hours", "running hours"]);
export const isHours = (unit) => HOURS.has(String(unit || "").trim().toLowerCase());

// "500" or "100, 900, 1,500" (or one per line): the ages, or {error}.
export function parseAges(text) {
  // Spaces, new lines, semicolons and commas separate; "1,500" (thousands) is one number.
  const parts = String(text ?? "").split(/[\s;]+/).filter(Boolean)
    .flatMap((t) => (/^\d{1,3}(,\d{3})+(\.\d+)?$/.test(t) ? [t] : t.split(","))).map((x) => x.trim()).filter(Boolean);
  if (!parts.length) return { error: "Enter the units' age now: one age for them all, or one per unit." };
  const ages = [];
  for (const p of parts) {
    const n = Number(p.replace(/,/g, ""));
    if (!Number.isFinite(n)) return { error: `"${p}" isn't a number: give each age in the model's unit.` };
    if (n < 0) return { error: "An age can't be negative." };
    ages.push(n);
  }
  return { ages };
}

const num = (v) => (String(v ?? "").trim() === "" ? null : Number(v));

// What's missing before Forecast can run (null: ready), said beside the button.
export function missing(f, model, unit) {
  if (!model) return "Pick a saved model, or choose a distribution and type its parameters.";
  if (!unit) return "Enter the unit of the model's times.";
  const a = parseAges(f.ages);
  if (a.error) return a.error;
  if (a.ages.length === 1 && !(Number(f.units) >= 1)) return "Enter how many units: 1 or more.";
  if (!(num(f.perDay) > 0)) return isHours(unit) ? "Enter the hours a unit runs a day." : `Enter the ${unit} a unit adds a day.`;
  const days = num(f.daysWeek);
  if (!(days > 0 && days <= 7)) return "Days a week is from 1 to 7.";
  if (f.policy === "age" && !(num(f.replaceAt) > 0)) return `Enter the age to replace at, in ${unit}.`;
  return null;
}

// The use a unit adds in one period: its use a day, on the days it runs, over the period's days.
export const ratePerPeriod = (perDay, daysWeek, group) => (Number(perDay) * Number(daysWeek) / 7) * PERIOD_DAYS[group];

// The request for the scratch forecast (POST /api/fleet/scratch-forecast).
export function requestOf(f, model, unit) {
  const { ages } = parseAges(f.ages);
  const spares = f.spares && Object.values(f.spares).some((v) => v != null && v !== "") ? f.spares : null;
  return {
    distribution_id: model.distribution_id, params: model.params, extras: model.extras || null,
    unit, name: model.name || "Typed parameters",
    ages: ages.length === 1 ? ages[0] : ages, units: ages.length === 1 ? Number(f.units) : ages.length,
    rate: ratePerPeriod(f.perDay, f.daysWeek, f.group),
    periods: periodsOf(f.horizon, f.group), period_label: f.group,
    strategy: f.policy === "age" ? "age" : "run_to_failure",
    replace_at: f.policy === "age" ? num(f.replaceAt) : null,
    failure_cost: num(f.failureCost), planned_cost: f.policy === "age" ? num(f.plannedCost) : null,
    planned_hours: f.policy === "age" ? num(f.plannedHours) : null, corrective_hours: num(f.correctiveHours),
    spare_cost: num(f.spareCost),
    spares,
  };
}

const word = (label, n = 2) => (n === 1 ? String(label).replace(/s$/, "") : String(label));
const sig3 = (v) => Number(v).toLocaleString("en-GB", { maximumSignificantDigits: 3 });

// The parts used each period: failures, plus planned replacements under a planned policy.
export function partsByPeriod(fc) {
  const st = fc?.strategy;
  if (st?.per_period?.length) return st.per_period.map((r) => Number(r.parts?.expected ?? r.failures?.expected ?? 0));
  return (fc?.per_period || []).map(Number);
}

// When next (from the expected counts): the period by which each of the first spares is likely
// used. "Spare 1 · month 2". Up to `limit`; `more` the rest.
export function whenNext(fc, limit = 20) {
  const parts = partsByPeriod(fc);
  const total = parts.reduce((a, b) => a + b, 0);
  const n = Math.floor(total + 1e-9);
  const out = [];
  let cum = 0;
  let k = 1;
  for (let i = 0; i < parts.length && k <= Math.min(n, limit); i++) {
    cum += parts[i];
    while (k <= Math.min(n, limit) && cum + 1e-9 >= k) {
      out.push({ n: k, period: i + 1 });
      k += 1;
    }
  }
  return { items: out, more: Math.max(0, n - out.length), total };
}

// "Spare 3 · month 2" (the period's word from the forecast's label).
export const whenText = (fc, x) => `Spare ${x.n.toLocaleString("en-GB")} · ${word(fc.period_label || "periods", 1)} ${x.period}`;

// The answer first: "≈ 12 spares in the next 12 months: 12 failures." (planned ones counted too).
export function answerText(fc) {
  const st = fc?.strategy;
  const horizon = `${fc.periods} ${word(fc.period_label, fc.periods)}`;
  const failures = st?.total?.failures?.expected ?? fc.expected;
  const planned = st?.kind === "age" ? st.total?.planned?.expected : null;
  const parts = planned != null ? failures + planned : failures;
  return { parts: sig3(parts), horizon, failures: sig3(failures), planned: planned != null ? sig3(planned) : null };
}

// The table by period: [{period, failures {expected, interval}, planned?, parts, cost?}].
export function rowsOf(fc) {
  const st = fc?.strategy;
  if (st?.per_period?.length) return st.per_period;
  return (fc?.per_period || []).map((v, i) => ({ period: i + 1, failures: { expected: v, interval: fc.per_period_interval?.[i] || null } }));
}

// What a view still needs to answer (null: it has what it needs), said in its card.
export function viewNeeds(view, f) {
  if (view === "hours" && num(f.correctiveHours) == null && !(f.policy === "age" && num(f.plannedHours) != null)) {
    return "Enter the hours a failure takes to put right (and, with planned replacement, the hours a replacement takes).";
  }
  if (view === "costs" && num(f.failureCost) == null && num(f.spareCost) == null && !(f.policy === "age" && num(f.plannedCost) != null)) {
    return "Enter what a failure costs, what a planned replacement costs or what a spare costs.";
  }
  return null;
}

// The rows of a view's table by period, and its CSV.
const n4 = (v) => (v == null || !Number.isFinite(Number(v)) ? "" : Number(Number(v).toPrecision(4)));
export function viewCsv(fc, view) {
  const label = word(fc.period_label || "periods", 1);
  if (view === "hours" && fc.views?.hours) {
    const h = fc.views.hours;
    return [[label, "planned_hours", "corrective_hours", "hours", "hours_p5", "hours_p95"],
      ...h.per_period.map((r) => [r.period, n4(r.planned), n4(r.corrective), n4(r.hours?.expected), n4(r.hours?.interval?.[0]), n4(r.hours?.interval?.[1])]),
      ["total", "", "", n4(h.total?.expected), n4(h.total?.interval?.[0]), n4(h.total?.interval?.[1])]];
  }
  if (view === "costs" && fc.views?.costs) {
    const c = fc.views.costs;
    return [[label, "planned", "corrective", "spares", "cost", "cost_p5", "cost_p95"],
      ...c.per_period.map((r) => [r.period, n4(r.planned), n4(r.corrective), n4(r.spares), n4(r.cost?.expected), n4(r.cost?.interval?.[0]), n4(r.cost?.interval?.[1])]),
      ["total", "", "", "", n4(c.total?.expected), n4(c.total?.interval?.[0]), n4(c.total?.interval?.[1])]];
  }
  const rows = rowsOf(fc);
  return [[label, "failures", "failures_p5", "failures_p95", "planned", "parts"],
    ...rows.map((r) => [r.period, n4(r.failures?.expected), n4(r.failures?.interval?.[0]), n4(r.failures?.interval?.[1]),
      n4(r.planned?.expected ?? 0), n4(r.parts?.expected ?? r.failures?.expected)])];
}
