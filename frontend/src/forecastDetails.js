// A forecast's details (ForecastDetails.jsx): the controls' choices, the query they make, each row's
// label, the CSV, the When next pages and the Forecast row's one-line summary in the tree. The
// numbers are the server's (GET /api/maintenance/positions/{id}/forecast/details,
// backend/maintenance/forecast_details.py, on RePyability): nothing here works out a date.
import { dayText, failuresText, hoursText, moneyText, periodLabel, sig } from "./positionForecast.js";

export const BASES = [
  { value: "calendar", label: "Calendar", title: "From today to a date, by day, week, month, quarter or year" },
  { value: "hours", label: "Operating hours", title: "The next so many running hours, grouped every so many hours" },
];

// The horizon on the calendar: this month and the next N − 1 (so 12 months by month is 12 rows),
// to the end of a month; or to a date picked.
export const CAL_HORIZONS = [
  { value: "3", label: "3 months" },
  { value: "6", label: "6 months" },
  { value: "12", label: "12 months" },
  { value: "24", label: "2 years" },
  { value: "60", label: "5 years" },
  { value: "custom", label: "Pick dates" },
];

export const GROUPS = [
  { value: "day", label: "Day" },
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "quarter", label: "Quarter" },
  { value: "year", label: "Year" },
];

export const HOURS_HORIZONS = [500, 1000, 2000, 5000, 10000].map((h) => ({ value: String(h), label: `${h.toLocaleString("en-GB")} h` }));
export const EVERY = [50, 100, 250, 500, 1000].map((h) => ({ value: String(h), label: `${h.toLocaleString("en-GB")} h` }));

export const PER_PAGE = 20;
const MAX_ROWS = 400;

// Grouping by day is offered up to about a year (the server reads at most 400 rows).
export function groupsFor(months) {
  const m = Number(months);
  return GROUPS.map((g) => (g.value === "day" && m > 13
    ? { ...g, disabled: true, title: "Up to about a year by day: pick a shorter horizon, or group by week" } : g));
}

// The hours "every" choices that keep the rows to MAX_ROWS.
export function everyFor(hours) {
  return EVERY.map((e) => (Number(hours) / Number(e.value) > MAX_ROWS
    ? { ...e, disabled: true, title: `More than ${MAX_ROWS} rows: group by more hours` } : e));
}

// The read for the controls' state: {basis, months, end, group, hours, every, reading} and what it's of
// (subject {kind: level|task|package, taskId?, packageId?}).
export function detailsQuery({ root = null, subject = {}, basis = null, months = "12", end = "", group = "month", hours = "1000", every = "100", reading = "" } = {}) {
  const q = { root: root || null, basis: basis || null };
  if (subject.kind === "task") q.task_id = subject.taskId;
  if (subject.kind === "package") q.package_id = subject.packageId;
  if (basis === "hours") return { ...q, hours, every, reading: reading === "" ? null : reading };
  if (basis === "calendar") return { ...q, period: group, ...(months === "custom" ? { end: end || null } : { months }) };
  return q;
}

// A row's label: the calendar's period ("Dec 2026", "Week of 7 Dec 2026"), or a span of running
// hours ("0 to 100 h").
export function rowLabel(d, row, i) {
  if (d.basis === "hours") return `${sig(row.from_hours)} to ${sig(row.to_hours)} h`;
  return periodLabel(row, d.period, i === 0);
}

// The meter reading a span of hours is at ("1,180 to 1,280 h on the meter").
export const meterText = (row) => `${sig(row.reading_from)} to ${sig(row.reading_to)} h on the meter`;

// What a forecast covers, in words: "1 Dec 2026 to 30 Nov 2027" or "the next 1,000 running hours".
export function horizonText(d) {
  if (!d) return "";
  if (d.basis === "hours") return `the next ${sig(d.hours)} running hours, from ${sig(d.reading)} h`;
  return `${dayText(d.start)} to ${dayText(d.end)}`;
}

// Planned plus unplanned, with "+ ?" when some failures forecast have no cost (it isn't the whole cost).
export function totalText(row, totals) {
  if (row.total_cost == null) return "—";
  return totals?.total_complete === false && totals?.failures ? `${moneyText(row.total_cost)} + ?` : moneyText(row.total_cost);
}

const money0 = (v) => (v ? moneyText(v) : "—");

// The table's columns: [{id, label, title, cell(row), csv(row)}]; failures only when the forecast has a life.
export function columns(d) {
  const fails = d?.totals?.failures != null;
  const cols = [
    { id: "tasks", label: d?.subject?.kind === "package" ? "Tasks done" : "Times done", title: "Each time a task is done (a package's visit counts each task on it)", cell: (r) => (r.tasks || 0).toLocaleString("en-GB"), csv: (r) => r.tasks || 0 },
    { id: "labour_hours", label: "Labour", title: "Labour hours: each task's What it needs lines (people × hours)", cell: (r) => (r.labour_hours ? hoursText(r.labour_hours) : "—"), csv: (r) => r.labour_hours ?? "" },
    { id: "labour_cost", label: "Labour cost", title: "The labour at the trade rates", cell: (r) => money0(r.labour_cost), csv: (r) => r.labour_cost ?? "" },
    { id: "materials_cost", label: "Parts and consumables", title: "Each task's spares and consumables, at their cost", cell: (r) => money0(r.materials_cost), csv: (r) => r.materials_cost ?? "" },
    { id: "visits_cost", label: "Visit cost", title: "Each visit's call-out and setup, once a visit (set on the package, or on a task in no package)", cell: (r) => money0(r.visits_cost), csv: (r) => r.visits_cost ?? "" },
    { id: "planned_cost", label: "Planned cost", title: "Labour, parts, visits and any typed cost the What it needs lines don't explain", cell: (r) => money0(r.planned_cost), csv: (r) => r.planned_cost ?? "" },
  ];
  if (fails) {
    cols.push(
      { id: "failures", label: "Expected failures", title: "Expected failures of the failure modes forecast, with the 90% two-sided range (5th to 95th percentile)", cell: (r) => failuresText(r.failures, r.failures_range), csv: (r) => r.failures ?? "" },
      { id: "failure_cost", label: "Failure cost", title: "Expected failures × what a failure costs, with the 90% two-sided range", cell: (r) => (r.failure_cost == null ? "—" : failureCostText(r)), csv: (r) => r.failure_cost ?? "" },
    );
  }
  cols.push({ id: "total_cost", label: "Total", title: "Planned plus failure cost", cell: (r) => totalText(r, d?.totals), csv: (r) => r.total_cost ?? "" });
  return cols.filter((c) => !OPTIONAL.has(c.id) || d?.totals?.[c.id]);
}

// Columns left out when nothing in the forecast has them (named under the table, with where to set them).
const OPTIONAL = new Set(["labour_hours", "labour_cost", "materials_cost", "visits_cost"]);
const OPTIONAL_WORDS = { labour_hours: "labour", labour_cost: "labour cost", materials_cost: "parts and consumables", visits_cost: "visit costs" };
export function emptyColumns(d) {
  return [...OPTIONAL].filter((id) => !d?.totals?.[id]).map((id) => OPTIONAL_WORDS[id]);
}

function failureCostText(r) {
  const range = r.cost_range;
  return range && range[0] != null && range[1] != null && range[1] > range[0]
    ? `${moneyText(r.failure_cost)} (${moneyText(range[0])} to ${moneyText(range[1])})` : moneyText(r.failure_cost);
}

const csvCell = (v) => {
  const s = v == null ? "" : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

// The table as CSV: one line a row, then the totals; ranges in their own columns.
export function detailsCsv(d) {
  const cols = columns(d);
  const head = d.basis === "hours" ? ["from_hours", "to_hours", "meter_from", "meter_to"] : ["period", "start", "end"];
  const fails = d.totals?.failures != null;
  const out = [[...head, ...cols.map((c) => c.id), ...(fails ? ["failures_low", "failures_high", "failure_cost_low", "failure_cost_high"] : [])]];
  d.rows.forEach((r, i) => {
    const key = d.basis === "hours" ? [r.from_hours, r.to_hours, r.reading_from, r.reading_to] : [rowLabel(d, r, i), r.start, r.end];
    out.push([...key, ...cols.map((c) => c.csv(r)), ...(fails ? [r.failures_range?.[0] ?? "", r.failures_range?.[1] ?? "", r.cost_range?.[0] ?? "", r.cost_range?.[1] ?? ""] : [])]);
  });
  const t = d.totals || {};
  out.push([...(d.basis === "hours" ? ["In all", "", "", ""] : ["In all", d.start, d.end]), ...cols.map((c) => c.csv(t)),
    ...(fails ? [t.failures_range?.[0] ?? "", t.failures_range?.[1] ?? "", t.cost_range?.[0] ?? "", t.cost_range?.[1] ?? ""] : [])]);
  return out.map((line) => line.map(csvCell).join(",")).join("\n") + "\n";
}

// One page of When next: {items, page, pages, from, to, total} (page from 0, kept in range).
export function pageOf(list, page, per = PER_PAGE) {
  const total = (list || []).length;
  const pages = Math.max(1, Math.ceil(total / per));
  const p = Math.min(Math.max(0, page), pages - 1);
  return { items: (list || []).slice(p * per, p * per + per), page: p, pages, from: total ? p * per + 1 : 0, to: Math.min(total, p * per + per), total };
}

// When one is done: "Mon 7 Dec 2026", "Thu 24 Dec 2026 at 08:00" (by use, the moment the meter gets
// there), or by running hours "in 70 h (1,250 h on the meter)".
export function whenText(d, o) {
  if (d.basis === "hours") return `in ${sig(o.hours)} h (${sig((d.reading || 0) + o.hours)} h on the meter)`;
  const day = periodLabel({ start: o.date }, "day");
  return o.moment ? `${day} at ${o.moment.slice(11, 16)}` : day;
}

// What one is: a task, or a package's visit and the tasks on it.
export function whatText(o) {
  if (o.kind === "visit") return `${o.name} visit: ${o.tasks.map((t) => t.name).join(", ")}`;
  return o.package ? `${o.name} (on the ${o.package.name} visit)` : o.name;
}

// The bars: each row's count, and the largest (at least 1).
export function bars(d) {
  const counts = (d?.rows || []).map((r) => r.tasks || 0);
  return { counts, max: Math.max(1, ...counts) };
}

// ---- the Forecast row in the tree -----------------------------------------------------------------

// The Forecast row's summary from the level's forecast for the year (`d`, a calendar read):
// "next 5 Dec 2026 · 12 a year · $1,240 a year"; a task by use with no duty "every 250 h · not dated:
// set a duty". `ids`: the task ids it's of; `pkg`: a package (its visits counted).
export function treeSummary(d, ids, { pkg = null } = {}) {
  if (!d) return "";
  const want = new Set(ids);
  const tasks = (d.tasks || []).filter((t) => want.has(t.id));
  const left = (d.not_placed || []).filter((x) => want.has(x.task.id));
  if (!tasks.length) return left.length ? left.map((x) => x.reason).join("; ") : "None due in the next year";
  const next = tasks.map((t) => t.dates[0]).filter(Boolean).sort()[0];
  const overdue = tasks.some((t) => t.overdue);
  let n = tasks.reduce((s, t) => s + t.count, 0);
  let word = n === 1 ? "time" : "times";
  if (pkg) {
    const visits = (d.occurrences || []).filter((o) => o.kind === "visit" && o.package?.id === pkg);
    if (visits.length) { n = visits.length; word = n === 1 ? "visit" : "visits"; }
  }
  const priced = tasks.filter((t) => t.cost_each != null);
  const cost = priced.reduce((s, t) => s + Number(t.cost_each) * t.count, 0);
  return [
    next ? `${overdue ? "overdue, done first " : "next "}${dayText(next)}` : null,
    `${n.toLocaleString("en-GB")} ${word} a year`,
    priced.length ? `${moneyText(cost)} a year` : "cost not set",
    left.length ? `${left.length} not dated` : null,
  ].filter(Boolean).join(" · ");
}
