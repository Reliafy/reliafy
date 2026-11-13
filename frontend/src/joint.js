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
// Where the row carries its life bound (the Explorer's positions: `life_level`, 0.9), the
// one-sided lower bound follows: "531 days (at least 402 days, 90%)"; one that couldn't be
// worked out says so rather than showing nothing.
export function medianText(row, unit = "") {
  if (!row || row.median_reached === false || row.median_remaining == null) return "not reached";
  const u = unit ? ` ${unit.toLowerCase()}` : "";
  const text = `${lifeLeftNumber(row.median_remaining)}${u}`;
  if (row.life_level == null) return text;
  const level = `${Math.round(Number(row.life_level) * 100)}%`;
  return row.median_lower == null ? `${text} (no ${level} bound here)`
    : `${text} (at least ${lifeLeftNumber(row.median_lower)}${u}, ${level})`;
}

// A band's name from the two-sided level it was drawn at (alpha_ci: 0.1 → "90%").
export function bandLevel(alpha, fallback = 0.05) {
  const a = Number(alpha);
  return `${Math.round((1 - (Number.isFinite(a) && a > 0 && a < 1 ? a : fallback)) * 100)}%`;
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

// A chance's 90% one-sided upper bound in a cell: "≤ 80%" (blank without one).
export function riskUpperText(p) {
  if (p == null || !Number.isFinite(Number(p))) return "";
  return Number(p) >= 0.999 ? "≤ 100%" : `≤ ${riskText(p)}`;
}

// A median life left's 90% lower bound in a cell: "≥ 6.6 days" (blank without one).
export function medianLowerText(row, unit = "") {
  if (!row || row.median_lower == null || row.median_reached === false || row.median_remaining == null) return "";
  return `≥ ${lifeLeftNumber(row.median_lower)}${unit ? ` ${unit.toLowerCase()}` : ""}`;
}

// What the risk table says about its bounds: the level when rows carry them,
// else why there are none. ``rows``: the table's rows with a risk.
export function riskBoundNote(rows, level = 0.9) {
  const scored = (rows || []).filter((r) => r.risk);
  if (!scored.length) return "";
  const pct = `${Math.round(level * 100)}%`;
  if (scored.some((r) => r.risk_upper)) {
    return `Under each chance, its ${pct} upper bound (we're ${pct} sure the chance is at most that); `
      + `under each median life left, its ${pct} lower bound.`;
  }
  return `No ${pct} bounds on these chances: this model was saved before they were worked out. `
    + "Fit a new model from the same data to see them.";
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

// One position's risk now (the Explorer's Condition monitoring tab on a position, and the member
// a class's fleet has chosen), from its read (api.js getPositionCondition): what to show.
// "scored": its summary and charts. Else why there is no risk, in words, never a blank panel:
// "no-model" (no condition and life model linked: the tab says how to link one) or "not-scored"
// (a model, and the reason the read gives). `why`: the reason; `facts`: what is known all the
// same (the item fitted, its age, its last reading), one line, null with nothing fitted.
export function positionRisk(read) {
  if (!read) return null;
  const m = read.member || null;
  if (read.model && m?.scored && m.unit) return { state: "scored", why: null, facts: null };
  const facts = positionFacts(m, read.age_unit);
  if (!read.model) return { state: "no-model", why: m ? null : read.why || null, facts };
  const why = (m ? m.why : read.why) || "The model gave no risk for this position: check its readings and its item's in-service date.";
  return { state: "not-scored", why, facts };
}

// A member's facts in a line: "Fitted here: Unit 7 (S-7), age 120 days. Last reading of
// Vibration: 4.2 mm/s on 2026-11-01."
export function positionFacts(member, ageUnit = "Days") {
  if (!member) return null;
  const item = `${member.item?.name || "(no name)"}${member.item?.serial ? ` (${member.item.serial})` : ""}`;
  const unit = String(ageUnit || "").toLowerCase();
  const age = Number(member.age) === 1 ? unit.replace(/s$/, "") : unit;
  const parts = [`Fitted here: ${item}, age ${formatNumber(member.age)}${age ? ` ${age}` : ""}.`];
  const point = member.point?.name || "";
  const last = member.last_reading;
  if (last) parts.push(`Last reading${point ? ` of ${point}` : ""}: ${formatNumber(last.value)}${last.unit ? ` ${last.unit}` : ""} on ${last.on}.`);
  else if (point) parts.push(`No readings of ${point} since this item went in.`);
  return parts.join(" ");
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

// Whether a saved condition and life model scores positions on the asset tree:
// some position links it (`links` from GET /api/maintenance/position-models).
// Then its page adds a link to the Explorer beside its own Risk now tab.
export function usedOnPositions(links, modelId) {
  return !!modelId && (links || []).some((l) => l?.model_type === "model" && l?.model_id === modelId);
}

// The condition-and-life Data step: the shared selectors (ColumnMapper) for
// each of its two tables. Lifetimes: i (the item id, sent as ``id``), x and
// its range, c (0/1 codes, flipped with c_invert) and tl; readings: i, x
// (when the reading was taken, sent as ``age``) and m (the measured value,
// sent as ``value``): measurements, not covariates.
export const JOINT_LIFE_ROWS = ["i", "x", "c", "tl"];
export const JOINT_LIFE_KEYS = { i: "id" };
export const JOINT_READ_ROWS = ["i", "x", "m"];
export const JOINT_READ_KEYS = { i: "id", x: "age", m: "value" };

// The lifetimes mapping sent: x, or the range (xl, xr) when x is blank, never
// both (the fit reads one or the other); unset columns left out.
export function jointLifeMapping(map) {
  const m = map.x ? { id: map.id, x: map.x, c: map.c, tl: map.tl }
    : { id: map.id, xl: map.xl, xr: map.xr, c: map.c, tl: map.tl };
  return Object.fromEntries(Object.entries(m).filter(([, v]) => v));
}

// What stops a condition-and-life fit, beside its selector: [{ table, row, text }].
export function jointIssues(map, rmap) {
  const out = [];
  const add = (table, row, text) => out.push({ table, row, text });
  const range = !!(map.xl || map.xr);
  if (!map.id) add("life", "i", "Pick i: the column saying which item each row is.");
  if (map.x && range) add("life", "x", "Condition and life takes x or a range (xl to xr), not both: clear one.");
  else if (range && !(map.xl && map.xr)) add("life", "x", "Pick both xl and xr for the range, or neither.");
  else if (!map.x && !range) add("life", "x", "Pick x: the column with the value when each item failed or was last seen.");
  if (!map.c) add("life", "c", "Pick c: the column saying whether each item failed or is still running.");
  if (!rmap.id) add("reads", "i", "Pick i: the column saying which item each reading belongs to.");
  if (!rmap.age) add("reads", "x", "Pick x: the column saying when each reading was taken.");
  if (!rmap.value) add("reads", "m", "Pick m: the column with the measured value.");
  return out;
}

// A saved dataset's reading as the condition-and-life fit's two mappings (no
// column step). The life data from the main reading: i (sent as ``id``), x or
// its range, c and tl, with c_invert and the time unit; the readings from the
// reading of the measurements part (``r.measurements``: i, x, m), or, for one
// table holding both (``combined``), the main reading's i, x and m. The fit
// takes c as 0/1 codes: a status read by words (c_map) is turned into
// c_invert when its values are 0 and 1, else said in ``statusIssue``.
// Covariates: Z, numeric columns only (``lifeFacts``: column facts).
// { map, rmap, invert, unit, markerUnit, covariates, statusIssue }.
export function jointMappingsFromReading(r, { combined = false, lifeFacts = {} } = {}) {
  const life = r || {};
  const map = {
    id: life.i || "", x: life.x || "", xl: life.x ? "" : life.xl || "", xr: life.x ? "" : life.xr || "",
    c: life.c || "", tl: life.tl || "",
  };
  const meas = (combined ? { i: life.i, x: life.x, m: life.m, m_unit: life.m_unit } : life.measurements) || {};
  const rmap = { id: meas.i || "", age: meas.x || "", value: meas.m || "" };
  let invert = !!life.c_invert && !!life.c;
  let statusIssue = null;
  if (life.c && life.c_map && Object.keys(life.c_map).length) {
    const entries = Object.entries(life.c_map);
    if (entries.every(([k, v]) => ["0", "1"].includes(String(k).trim()) && [0, 1].includes(Number(v)))) {
      invert = entries.some(([k, v]) => String(k).trim() === "1" && Number(v) === 0);
    } else {
      const words = entries.map(([k]) => k).slice(0, 3).join(", ");
      statusIssue = `c (“${life.c}”) says failed or running in words (${words}); condition and life reads 0/1 codes `
        + "only. Change the reading to a column of 0 = failed, 1 = running codes.";
    }
  }
  const covariates = (life.z || []).filter((c) => !lifeFacts[c]?.dtype || isNumeric(lifeFacts[c].dtype));
  return { map, rmap, invert, unit: life.unit || "", markerUnit: meas.m_unit || "", covariates, statusIssue };
}

// The fit request's column fields, as the page sends them (with dataset_id,
// name, path_model, unit, marker and marker_unit beside).
export function jointRequest(map, rmap, invert, covs) {
  return {
    mapping: jointLifeMapping(map),
    readings_mapping: rmap,
    c_invert: invert,
    ...covariateParts(covs),
  };
}
