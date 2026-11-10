// Condition and life: remaining life from condition readings (joint models of readings and failures): the pure
// helpers behind the new-model page, the results page and the RBD block —
// first guesses for the two tables' columns, the covariate parts, the risk
// table's words and a block's one line. `node --test src/` covers them.
import { censorInverted, guessLifeColumns, guessUnit, isNumeric } from "./datasetGuess.js";
import { formatNumber, formatPercent } from "./format.js";

// A column name as words: "unit_id" → "unit id".
const words = (name) =>
  String(name || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-./()[\]#:]+/g, " ").trim();

const ID_RE = /\b(id|ids|serial|sn|tag|asset|unit|item|equipment|pump|machine|truck|engine|component|name|no)\b/i;
const AGE_RE = /\b(age|hours?|hrs?|time|days?|weeks?|months?|years?|cycles?|km|miles?|t)\b/i;
const VALUE_RE = /\b(value|reading|readings|measure|measurement|marker|vib|vibration|wear|temp|temperature|debris|level|thickness|pressure|y)\b/i;

// The unit id column: named like an id; else the first text column; else the first.
export function guessIdColumn(columns) {
  const named = columns.find((c) => ID_RE.test(words(c.name)));
  if (named) return named.name;
  return (columns.find((c) => !isNumeric(c.dtype)) || columns[0])?.name || "";
}

// First guesses for the lifetimes table: id, age (x), censoring flag (c),
// whether that flag is 1 = failed (invert), the time unit, and the numeric
// columns left over as candidate covariates.
export function guessLifetimeColumns(columns) {
  const id = guessIdColumn(columns);
  const rest = columns.filter((c) => c.name !== id);
  const g = guessLifeColumns(rest);
  const used = new Set([id, g.x, g.c, g.n].filter(Boolean));
  return {
    id,
    x: g.x,
    c: g.c,
    invert: !!g.c && censorInverted(g.c),
    unit: g.unit || guessUnit(g.x),
    covariates: rest.filter((c) => isNumeric(c.dtype) && !used.has(c.name)).map((c) => c.name),
  };
}

// First guesses for the readings table: unit id, age and value.
export function guessReadingColumns(columns) {
  const id = guessIdColumn(columns);
  const numeric = columns.filter((c) => c.name !== id && isNumeric(c.dtype));
  const age = (numeric.find((c) => AGE_RE.test(words(c.name))) || numeric[0])?.name || "";
  const value = (numeric.find((c) => c.name !== age && VALUE_RE.test(words(c.name)))
    || numeric.find((c) => c.name !== age))?.name || "";
  return { id, age, value };
}

// The covariates' parts as the fit takes them: ``rows`` are
// [{name, risk, path}] (each in the failure risk, the reading's path, or
// both). Every covariate in both: no parts (the model's default).
export function covariateParts(rows) {
  const used = rows.filter((r) => r.risk || r.path);
  const covariates = used.map((r) => r.name);
  if (used.every((r) => r.risk && r.path)) return { covariates };
  return {
    covariates,
    hazard_covariates: used.filter((r) => r.risk).map((r) => r.name),
    path_covariates: used.filter((r) => r.path).map((r) => r.name),
  };
}

// Readings typed as "age value" pairs, one per line (or "age: value", or
// separated by commas): [[age, value], ...] sorted by age, or an error.
export function parseReadings(text) {
  const lines = String(text || "")
    .split(/\n|;/)
    .map((l) => l.trim())
    .filter(Boolean);
  const out = [];
  for (const line of lines) {
    const parts = line.split(/[\s,:=\t]+/).filter(Boolean);
    if (parts.length !== 2) return { error: `“${line}”: give an age and a value.` };
    const [a, v] = parts.map(Number);
    if (!Number.isFinite(a) || !Number.isFinite(v)) return { error: `“${line}”: both must be numbers.` };
    if (a < 0) return { error: `“${line}”: ages are since new, 0 or more.` };
    out.push([a, v]);
  }
  out.sort((p, q) => p[0] - q[0]);
  return { readings: out };
}

export const readingsText = (markers) => (markers || []).map(([a, v]) => `${a} ${v}`).join("\n");

// "not reached" for a median remaining life the curve never falls to; never a
// mean (it can be infinite).
export function medianText(row, unit = "") {
  if (!row || row.median_reached === false || row.median_remaining == null) return "not reached";
  return `${lifeLeftNumber(row.median_remaining)}${unit ? ` ${unit.toLowerCase()}` : ""}`;
}

// A remaining life with the same decimals across a column: one decimal under
// 100 ("10.0", "12.0", "22.4"), else three significant figures ("1,230").
// formatNumber alone gives "9.99" beside "12", which reads as two precisions.
export function lifeLeftNumber(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return Math.abs(n) < 100 ? n.toFixed(1) : formatNumber(n);
}

// A model's chance of failing: never "100%" or "0%", which would read as
// certainty. Above 99.9% it's "> 99.9%", below 0.1% "< 0.1%", and from 99%
// one decimal so 99.6% doesn't round up to 100%.
export function riskText(p) {
  if (p == null || !Number.isFinite(Number(p))) return "—";
  const v = Number(p);
  if (v >= 0.999) return "> 99.9%";
  if (v < 0.001) return "< 0.1%";
  if (v >= 0.99) return `${(Math.floor(v * 1000) / 10).toFixed(1)}%`;
  return formatPercent(v);
}

// The column a risk table is sorted by: the middle horizon where there is
// one, else the first.
export const sortColumn = (labels) => ((labels || []).length > 1 ? 1 : 0);

// A class's fleet in one line (the Explorer by Classes): how many positions,
// how many have risk now, and the highest. Members come highest risk first.
export function fleetAnswer(fleet) {
  if (!fleet) return "";
  const n = fleet.positions;
  const parts = [`${n.toLocaleString("en-AU")} position${n === 1 ? "" : "s"}`];
  if (fleet.scored) {
    const top = fleet.members.find((m) => m.scored);
    const col = sortColumn(fleet.horizons.labels);
    parts.push(`${fleet.scored === n ? "all" : fleet.scored.toLocaleString("en-AU")} with risk now`);
    if (top) parts.push(`highest: ${top.position.name || "(no name)"}, ${riskText(top.risk[col])} in the next ${fleet.horizons.labels[col]}`);
  } else {
    parts.push("no risk now yet");
  }
  return parts.join(" · ");
}

// The number riskText shows, for sorting: rows that show the same figure tie.
function shownRisk(p) {
  const t = riskText(p);
  if (t === "—") return -1;
  const n = parseFloat(t.replace(/[^\d.]/g, ""));
  return t.startsWith(">") ? n + 0.01 : t.startsWith("<") ? n - 0.01 : n;
}

// The risk table's order, by one named column: the chance of failing over the
// middle horizon (the one "Highest risk now" quotes), highest first; rows that
// show the same figure there go shortest median life left first.
export function sortRiskRows(rows, col = 1) {
  const life = (r) => (r.median_reached === false || r.median_remaining == null ? Infinity : r.median_remaining);
  return [...(rows || [])].sort((a, b) => shownRisk(b.risk?.[col]) - shownRisk(a.risk?.[col]) || life(a) - life(b));
}

// A risk's tone: high (≥ 50%), medium (≥ 10%), low.
export function riskTone(p) {
  if (p == null) return "neutral";
  return p >= 0.5 ? "danger" : p >= 0.1 ? "warning" : "success";
}

export const isJointModel = (model) => model?.kind === "joint";

// A joint block's one line on the canvas: "Condition and life · unit P12" or
// "Condition and life · age 120 h, 3 readings".
export function jointBlockLine(model, unitAbbr = "") {
  const u = model?.joint_unit || {};
  if (u.id != null && u.id !== "") return `Condition and life · unit ${u.id}`;
  if (u.age != null) {
    const n = (u.markers || []).length;
    return `Condition and life · age ${formatNumber(u.age)}${unitAbbr ? ` ${unitAbbr}` : ""}, ${n} reading${n === 1 ? "" : "s"}`;
  }
  return "Condition and life · pick a unit";
}

// The RBD block's model for a joint model and a unit (a fitted running unit's
// id, or entered values).
export function jointBlockModel(model, unit) {
  return {
    source: "joint",
    kind: "joint",
    modelId: model.id,
    name: model.name,
    distribution: "Condition and life",
    unit: model.unit || model.results?.unit || "",
    joint_unit: unit,
  };
}

// The parameters, grouped by part in the order the fit gives them.
export function paramGroups(params) {
  const groups = [];
  for (const p of params || []) {
    let g = groups.find((x) => x.part === p.part);
    if (!g) groups.push((g = { part: p.part, label: p.part_label || p.part, rows: [] }));
    g.rows.push(p);
  }
  return groups;
}
