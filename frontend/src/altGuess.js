// First guesses for an accelerated life fit's Data step: the failure time,
// the censor flag, the stress column(s) and their units, read from the
// columns' names and types. Never a text column (a unit id) for a time or a
// stress, and never a time-like column ("hours") for a stress. Pure, so
// `node --test` covers it.
import { censorInverted, guessUnit, isNumeric } from "./datasetGuess.js";
import { missingFor } from "./datasetReading.js";
import { codedStatus, unitColumnProblem } from "./readingCodes.js";

// A column name as words: "temp_C" → "temp C", "TempK" → "Temp K".
const words = (name) =>
  String(name || "").replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_\-./()[\]#:]+/g, " ").trim();

const TIME = /\b(hours?|hrs?|hr|h|time|times|ttf|tbf|age|cycles?|km|kms|miles?|days?|weeks?|months?|years?|minutes?|mins?|life|duration|runtime|starts?)\b/i;
const ID = /\b(id|ids|no|number|serial|sn|tag|asset|unit|units|item|code|row|index|specimen|sample|part|name)\b/i;
const FLAG = /\b(c|cens|censor|censored|censoring|suspended|suspension|running|status|event|failed|fail|failure|state)\b/i;
const TEMPERATURE = /\b(temp|temps|temperature|temperatures|tc|tk|celsius|kelvin|fahrenheit|thermal|deg|degc|degk|degf)\b|°|℃|℉/i;
const OTHER_STRESS = /\b(stress|volt|volts|voltage|v|kv|mv|load|loads|pressure|psi|bar|kpa|mpa|humidity|rh|current|amps?|a|power|w|kw|vibration|grms|g|speed|rpm|torque|force|n|kn|strain|duty)\b/i;
// Models whose first stress enters as exp(a / T): a temperature (backend.alt).
const THERMAL = new Set(["arrhenius", "eyring", "power_exponential", "dual_exponential"]);

export const isThermal = (lifeModel) => THERMAL.has(lifeModel);

// The temperature unit a column's name says: "°C", "K", "°F" or "".
export function temperatureUnitOf(name) {
  const w = words(name);
  if (/kelvin|°\s*k\b|\bdeg\s*k\b|\bdegk\b|\bk\b|\btk\b/i.test(w)) return "K";
  if (/celsius|℃|°\s*c\b|\bdeg\s*c\b|\bdegc\b|\bc\b|\btc\b/i.test(w)) return "°C";
  if (/fahrenheit|℉|°\s*f\b|\bdeg\s*f\b|\bdegf\b|\bf\b/i.test(w)) return "°F";
  return "";
}

// The column facts the Data step has ({ columns, dtypes, values, n_unique },
// as the columns preview and the dataset page give them) as one list.
export function columnFacts(source) {
  const names = source?.columns || source?.preview_columns || [];
  return names.map((name, i) => ({
    name,
    dtype: source?.dtypes?.[i] ?? null,
    values: source?.values?.[i] ?? null,
    distinct: source?.n_unique?.[i] ?? null,
  }));
}

// Numeric when the dtype says so; with no dtype, when every preview value is.
function numericColumns(facts, preview) {
  return facts.filter((c, i) => {
    if (c.dtype != null) return isNumeric(c.dtype);
    const vals = (preview || []).map((row) => row?.[i]).filter((v) => v != null && String(v).trim() !== "");
    return vals.length > 0 && vals.every((v) => Number.isFinite(Number(v)));
  });
}

const isFlagValues = (c) => {
  const keys = Object.keys(c.values || {});
  return keys.length > 0 && keys.every((v) => ["0", "1", "2", "-1"].includes(String(v)));
};

// { x, c, unit, stress: [{ col, unit }], warnings }: first guesses for the
// Data step. ``nStress``: the life-stress relationship's stress count;
// ``lifeModel``: its id (a thermal one puts a temperature first).
export function guessAltColumns(source, { nStress = 1, lifeModel = "arrhenius", preview = null } = {}) {
  const facts = columnFacts(source);
  const numeric = numericColumns(facts, preview ?? source?.preview);
  const named = (re) => (c) => re.test(words(c.name));

  // The censor flag: a 0/1 column named like one, and 1 = still running
  // (the fit can't flip a 1 = failed flag here, so that one is left to the user).
  const flag = numeric.find((c) => named(FLAG)(c) && isFlagValues(c) && !censorInverted(c.name));
  const c = flag?.name || "";

  const candidates = numeric.filter((col) => col.name !== c && !(named(ID)(col) && !named(TIME)(col)));
  const x = candidates.find(named(TIME))
    || candidates.find((col) => !named(TEMPERATURE)(col) && !named(OTHER_STRESS)(col) && !isFlagValues(col));
  const xName = x?.name || "";

  // Stresses: never the time, the flag or an id; by what the name says.
  const pool = candidates.filter((col) => col.name !== xName && !named(TIME)(col) && !isFlagValues(col));
  const temps = pool.filter(named(TEMPERATURE))
    // A kelvin column first: it needs no conversion.
    .sort((a, b) => (temperatureUnitOf(b.name) === "K") - (temperatureUnitOf(a.name) === "K"));
  const others = pool.filter((col) => !named(TEMPERATURE)(col) && named(OTHER_STRESS)(col));
  const rest = pool.filter((col) => !temps.includes(col) && !others.includes(col))
    .sort((a, b) => (a.distinct ?? 99) - (b.distinct ?? 99));
  const order = isThermal(lifeModel) ? [temps, others, rest] : [others, temps, rest];
  const picked = [];
  const take = (list) => {
    for (const col of list) {
      if (picked.length >= nStress) return;
      // One temperature column only (temp_C and temp_K are the same stress).
      if (picked.some((p) => named(TEMPERATURE)(p)) && named(TEMPERATURE)(col)) continue;
      if (!picked.includes(col)) picked.push(col);
    }
  };
  if (isThermal(lifeModel)) {
    take(temps.slice(0, 1));
    take(others);
    take(rest);
  } else {
    order.forEach(take);
  }
  const stress = Array.from({ length: nStress }, (_, j) => {
    const col = picked[j];
    if (!col) return { col: "", label: "", unit: "" };
    const t = named(TEMPERATURE)(col) || (isThermal(lifeModel) && j === 0) ? temperatureUnitOf(col.name) : "";
    return { col: col.name, label: "", unit: t };
  });
  return { x: xName, c, unit: guessUnit(xName), stress };
}

// A word for the Data step when a stress column has many distinct values,
// more like a time or a measurement than a few test levels.
export const MANY_LEVELS = 8;
export function stressLevelsWarning(source, col) {
  const fact = columnFacts(source).find((c) => c.name === col);
  if (!fact || !Number.isFinite(fact.distinct) || fact.distinct <= MANY_LEVELS) return null;
  return `“${col}” has ${fact.distinct} different values: a test usually has a few stress levels. Is this the right column?`;
}

// The life-stress relationship to start from, by what the columns' names
// say: a temperature column suggests Arrhenius; a voltage, load, pressure or
// other non-temperature stress (and no temperature) the inverse power law.
// "" when the names don't say.
export function suggestLifeModel(source) {
  const facts = columnFacts(source);
  const numeric = numericColumns(facts, source?.preview);
  const named = (re) => (c) => re.test(words(c.name));
  const pool = numeric.filter((c) => !named(TIME)(c) && !isFlagValues(c) && !(named(ID)(c)));
  if (pool.some(named(TEMPERATURE))) return "arrhenius";
  if (pool.some(named(OTHER_STRESS))) return "inverse_power";
  return "";
}

// The accelerated-life Data step: the life selectors (ColumnMapper) the ALT
// fit takes: x with its range, c (0/1 codes: the fit reads no words and no
// flip), n, tl and tr. Covariates have no place here: the stresses are the
// model's own inputs, on the Model step.
export const ALT_ROWS = ["x", "c", "n", "tl", "tr"];

// The mapping sent, in order, with its unset columns left out.
export function altMapping(map) {
  return Object.fromEntries(["x", "xl", "xr", "c", "n", "tl", "tr"].filter((k) => map?.[k]).map((k) => [k, map[k]]));
}

// The form fields an ALT fit is sent as (api.js altForm): [[field, value]].
export function altFields(mapping, stress = []) {
  const out = [];
  ["x", "xl", "xr", "c", "n", "tl", "tr"].forEach((k) => { if (mapping?.[k]) out.push([k, mapping[k]]); });
  stress.slice(0, 2).forEach((s, j) => {
    if (!s) return;
    out.push([`s${j + 1}`, s.col]);
    if (s.label) out.push([`s${j + 1}_label`, s.label]);
  });
  stress.slice(0, 2).forEach((s, j) => { if (s?.unit?.trim()) out.push([`s${j + 1}_unit`, s.unit.trim()]); });
  return out;
}

// What stops the ALT fit, beside its selector: the Data step's ([{ row, text }])
// and the Model step's stress inputs ([{ stress: j, text }]).
export function altDataIssues(map) {
  const out = [];
  const range = !!(map.xl || map.xr);
  if (range && !(map.xl && map.xr)) out.push({ row: "x", text: "Pick both xl and xr for the range, or neither." });
  if (!map.x && !range) out.push({ row: "x", text: "Pick x: the column with the value when each unit failed or was removed." });
  return out;
}
export function altStressIssues(stress, nStress, lifeModel, map) {
  const used = new Set(Object.values(altMapping(map)));
  const out = [];
  stress.slice(0, nStress).forEach((s, j) => {
    if (!s.col) out.push({ stress: j, text: `Pick the column for stress ${j + 1}.` });
    else if (used.has(s.col)) out.push({ stress: j, text: `“${s.col}” is mapped on the Data step: pick another column.` });
    else if (stress.slice(0, j).some((o) => o.col === s.col)) out.push({ stress: j, text: "Pick a different column for each stress." });
    if (j === 0 && isThermal(lifeModel) && !["°C", "K", "°F"].includes(String(s.unit || "").trim())) {
      out.push({ stress: 0, text: "Pick the temperature's unit (°C, K or °F): this model needs absolute temperature, so °C and °F are converted to kelvin before the fit." });
    }
  });
  return out;
}

// A saved dataset's reading (datasetReading.js) as the ALT fit's Data-step
// mapping, so a fit from a saved dataset asks no column questions:
// { map, unit, status, missing }. ``map``: x with its range, c, n, tl, tr
// (altMapping sends the set ones); ``status``: readingCodes.codedStatus (this
// fit reads c as 0/1 codes); ``missing``: what stops the fit, in words, or null.
export function altMappingFromReading(r, facts = {}, nRows = 0) {
  if (!r) return null;
  const status = codedStatus(r, facts, nRows);
  const map = {
    x: r.x || "", xl: r.xl || "", xr: r.xr || "", c: status.c, n: r.n || "", tl: r.tl || "", tr: r.tr || "",
  };
  const unit = r.unit || guessUnit(map.x);
  const missing = missingFor("alt", r) || unitColumnProblem(r) || status.problem;
  return { map, unit, status, missing };
}

// The columns offered for the stresses: the reading's covariates (Z), else
// the numeric columns the reading gives no role (nor the fit's c).
export function altStressPool(source, r, c = "") {
  const z = (r?.z || []).filter((col) => col && col !== c);
  if (z.length) return z;
  const used = new Set(["x", "xl", "xr", "c", "n", "tl", "tr", "i", "m", "e", "s", "u"].map((k) => r?.[k]).filter(Boolean));
  if (c) used.add(c);
  const facts = columnFacts(source);
  return numericColumns(facts, source?.preview).map((f) => f.name).filter((name) => !used.has(name));
}

// ``source`` cut to ``cols`` (names, dtypes, values, counts and preview), so
// the stress guess and the life-stress suggestion look only at those.
function sourceOf(source, cols) {
  const names = source?.columns || source?.preview_columns || [];
  const idx = cols.map((c) => names.indexOf(c)).filter((i) => i >= 0);
  const pick = (arr) => (Array.isArray(arr) ? idx.map((i) => arr[i]) : arr);
  return {
    columns: idx.map((i) => names[i]),
    dtypes: pick(source?.dtypes), values: pick(source?.values), n_unique: pick(source?.n_unique),
    preview: (source?.preview || []).map((row) => (Array.isArray(row) ? idx.map((i) => row[i]) : row)),
  };
}

// The first stress guess from the reading: guessAltColumns over the pool only.
export function altStressFromReading(source, r, { nStress = 1, lifeModel = "arrhenius", c = "" } = {}) {
  const pool = sourceOf(source, altStressPool(source, r, c));
  // guessAltColumns also guesses a time: here every pool column is a stress candidate.
  const g = guessAltColumns({ ...pool, columns: pool.columns }, { nStress, lifeModel });
  if (g.x && !g.stress.some((s) => s.col === g.x) && g.stress.some((s) => !s.col)) {
    const free = g.stress.findIndex((s) => !s.col);
    const t = isThermal(lifeModel) && free === 0 ? temperatureUnitOf(g.x) : "";
    g.stress[free] = { col: g.x, label: "", unit: t };
  }
  return g.stress;
}

// The life-stress relationship the pool's names suggest ("" when they don't).
export function suggestLifeModelFromReading(source, r, c = "") {
  return suggestLifeModel(sourceOf(source, altStressPool(source, r, c)));
}
