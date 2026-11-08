// The interval calculators on an RCM task card (RcmModeTasks' "Calculate…", IntervalCalculator.jsx):
// which one a task's kind opens, and the words they write: the interval in a unit people
// schedule in, and the one paragraph appended to the failure mode's notes and rationale.

export const TIME_UNITS = ["hours", "days", "weeks", "months", "years"];

// The calculator for a task's kind (its decision member's outcome), or null.
export const CALCULATOR = {
  on_condition: { key: "pf", title: "Work out the check interval", name: "P-F calculator", word: "check interval" },
  failure_finding: { key: "ff", title: "Work out the test interval", name: "failure-finding calculator", word: "test interval" },
  fixed_interval: { key: "fixed", title: "Work out the replacement interval", name: "replacement calculator", word: "replacement interval" },
};
export const calculatorFor = (outcome) => CALCULATOR[outcome] || null;

const ALIASES = {
  h: "hours", hr: "hours", hrs: "hours", hour: "hours", d: "days", day: "days", wk: "weeks", wks: "weeks", week: "weeks",
  mo: "months", month: "months", mth: "months", mths: "months", y: "years", yr: "years", yrs: "years", year: "years",
  cycle: "cycles", kilometres: "km", kilometers: "km", kilometre: "km", kilometer: "km",
};

// A unit as the task card's unit picker spells it ("Hours" → "hours"); anything else as typed, trimmed.
export function taskUnit(unit) {
  const key = String(unit || "").trim().toLowerCase();
  return ALIASES[key] || key;
}

// A number for a sentence: up to 3 significant figures, thousands separated.
export function num(value) {
  const v = Number(value);
  if (!Number.isFinite(v)) return String(value);
  if (v !== 0 && (Math.abs(v) < 0.001 || Math.abs(v) >= 1e9)) return v.toPrecision(3);
  const r = Number(v.toPrecision(3));
  return r.toLocaleString("en-AU", { maximumFractionDigits: 6 });
}

export const money = (value) => (value == null || !Number.isFinite(Number(value)) ? "–" : `$${num(value)}`);

// A small chance as people read it: 0.83%, 0.05%, 12%.
export function pct(p) {
  const v = 100 * Number(p);
  if (!Number.isFinite(v)) return "–";
  if (v >= 10) return `${Math.round(v)}%`;
  return `${Number(v.toPrecision(2))}%`;
}

// "1 month", "2 months", "490 hours".
export function withUnit(value, unit) {
  const u = taskUnit(unit);
  const one = Number(value) === 1 && TIME_UNITS.includes(u);
  return `${num(value)} ${one ? u.slice(0, -1) : u}`.trim();
}

// An interval in a model's own unit, rounded down for the task: whole from 10, else to 0.1.
export function roundDown(value) {
  const v = Number(value);
  if (!Number.isFinite(v) || v <= 0) return null;
  if (v >= 10) return Math.floor(v + 1e-9);
  return Math.max(0.1, Math.floor(v * 10 + 1e-9) / 10);
}

// "9 Nov 2026".
export const dateText = (date = new Date()) => date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });

// The one paragraph a used calculation adds to the failure mode's notes and rationale.
export function rationale(key, inputs, result, use, date = new Date()) {
  const to = withUnit(use.value, use.unit);
  const when = dateText(date);
  if (key === "pf") {
    const parts = [
      `P-F ${withUnit(inputs.pf_interval, inputs.pf_unit)}`, `onset ${num(inputs.onset_rate)}/year`,
      `inspection ${money(inputs.inspection_cost)}`, `found ${money(inputs.found_cost)}`, `failure ${money(inputs.failure_cost)}`,
    ];
    if (Number(inputs.detection_probability ?? 1) !== 1) parts.push(`detection ${pct(inputs.detection_probability)}`);
    const at = result.at_recommended || {};
    return `Interval from the P-F calculator (${when}): ${parts.join(", ")} → ${to}; cost rate ${money(at.cost_rate)}/year `
      + `(letting it fail: ${money(result.run_to_failure_cost_rate)}/year; rule of thumb: half the P-F interval).`;
  }
  if (key === "ff") {
    const dev = result.device || {};
    const parts = [dev.source === "model" ? `device ${dev.distribution} model (${dev.unit})` : `device ${num(dev.rate)} failures/year`];
    if (result.target_unavailability != null) {
      parts.push(`target unavailability ${pct(result.target_unavailability)}${inputs.target_assumed ? " (assumed)" : ""}`);
    }
    if (Number(inputs.test_cost) > 0) parts.push(`test ${money(inputs.test_cost)}`);
    if (Number(inputs.repair_cost) > 0) parts.push(`repair ${money(inputs.repair_cost)}`);
    if (inputs.demand_rate) parts.push(`demands ${num(inputs.demand_rate)}/year`);
    if (Number(inputs.consequence_cost) > 0) parts.push(`demand on a failed device ${money(inputs.consequence_cost)}`);
    const at = result.at_recommended || {};
    const cost = at.cost_rate != null ? `, cost rate ${money(at.cost_rate)}/year` : "";
    return `Interval from the failure-finding calculator (${when}): ${parts.join(", ")} → ${to}; `
      + `mean unavailability ${pct(at.mean_unavailability)}${cost}.`;
  }
  const unit = taskUnit(result.unit) || "unit";
  const saving = result.savings ? ` (${Math.round(result.savings * 100)}% saving)` : "";
  return `Interval from the replacement calculator (${when}): ${result.distribution || "life"} model`
    + `${inputs.model_name ? ` “${inputs.model_name}”` : ""}, planned ${money(inputs.planned_cost)}, unplanned ${money(inputs.unplanned_cost)} → ${to}; `
    + `cost rate ${money(result.optimal_cost_rate)}/${unit.replace(/s$/, "")} against ${money(result.run_to_failure_cost_rate)}/${unit.replace(/s$/, "")} `
    + `running to failure${saving}.`;
}

// The notes with the paragraph added at the end (a blank line between).
export function appendNotes(notes, line) {
  const before = String(notes || "").trimEnd();
  return before ? `${before}\n\n${line}` : line;
}

// The saved analysis's name: the failure mode and what was worked out.
export function analysisName(modeText, key) {
  const word = Object.values(CALCULATOR).find((c) => c.key === key)?.word || "interval";
  const text = String(modeText || "Failure mode").trim();
  const name = `${text}: ${word}`;
  return name.length > 120 ? `${text.slice(0, 120 - word.length - 3)}…: ${word}` : name;
}

// The saved analysis's kind for each calculator.
export const ANALYSIS_KIND = { pf: "on_condition_interval", ff: "failure_finding_interval", fixed: "optimal_replacement" };

// Whether a used calculation should also become the decision's evidence: only when it has none.
export const linksEvidence = (decision) => !(decision?.evidence?.type && decision?.evidence?.id);
