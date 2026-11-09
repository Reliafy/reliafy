// Covariate models in the data library (NSWC-11, the Navy's mechanical handbook: Derryn, 9 Nov
// 2026, "literally just a library of covariate models"): a part's failure rate is a base rate
// scaled by factors for the conditions it works in. The words and the input handling shared by the
// record page's Try it and a prediction line's Conditions… (CovariateCalculator.jsx). The
// arithmetic is the server's (backend/library/covariate.py); these only read and shape it.
import { sig } from "./libraryModels.js";

export const COVARIATE_SOURCE = "nswc-11";
export const isCovariate = (rec) => rec?.kind === "covariate_model";
// A record id from NSWC-11 (a saved prediction's line keeps only the id).
export const isCovariateId = (id) => String(id || "").startsWith(`${COVARIATE_SOURCE}:`);

// The rate unit, short: "per 10⁶ h", "per 10⁶ cycles".
export const UNIT_SHORT = {
  per_million_hours: "per 10⁶ h",
  per_million_cycles: "per 10⁶ cycles",
  per_million_operations: "per 10⁶ operations",
};
export const unitShort = (u) => UNIT_SHORT[u] || u || "";
export const perCycle = (u) => u === "per_million_cycles" || u === "per_million_operations";
// What one cycle is called for a unit (for "cycles an hour").
export const cycleWord = (u) => (u === "per_million_operations" ? "operations" : "cycles");

// What a covariate is (Derryn, 9 Nov 2026): fixed by the design, set by how it's used, or by where
// it works. A position may fix some, all or none; use and environment can be set in an RBD.
export const ROLES = [
  { role: "design", label: "Design", what: "Fixed by the design: material, geometry, finish, type, how many." },
  { role: "use", label: "Use", what: "How it's used: load, speed, pressure, duty, cycles." },
  { role: "environment", label: "Environment", what: "Where it works: temperature, contamination, humidity, vibration." },
];
export const roleLabel = (role) => ROLES.find((r) => r.role === role)?.label || "Other";

// The inputs by what they are (Design, Use, Environment, in that order), each keeping its part
// ("Seals", "Bearings") for a label; a role with no inputs is left out.
export function groupInputs(inputs = []) {
  const known = ROLES.map((r) => ({ ...r, inputs: inputs.filter((i) => i.role === r.role) }));
  const other = inputs.filter((i) => !ROLES.some((r) => r.role === i.role));
  return [...known, ...(other.length ? [{ role: "other", label: "Other", what: "", inputs: other }] : [])]
    .filter((g) => g.inputs.length);
}

const fmtNum = (v) => {
  const n = Number(v);
  if (!Number.isFinite(n)) return String(v);
  if (n !== 0 && (Math.abs(n) >= 1e6 || Math.abs(n) < 1e-3)) return sig(n);
  return String(Number(n.toPrecision(6)));
};

// One limit in words: "at least 0", "60 to 260 °C".
function boundWords(l, unit) {
  const u = unit ? ` ${unit}` : "";
  if (l.min != null && l.max != null) return `${fmtNum(l.min)} to ${fmtNum(l.max)}${u}`;
  if (l.min != null) return `${l.exclusive ? "more than" : "at least"} ${fmtNum(l.min)}${u}`;
  return `${l.exclusive ? "less than" : "at most"} ${fmtNum(l.max)}${u}`;
}

// An input's limits in words, the handbook's range (with its page) first: "Handbook range 60 to 260
// °C (p. 7-17) · must be more than 0".
export function limitText(input = {}) {
  const ls = input.limits || [];
  const warn = ls.filter((l) => l.severity === "warn").map((l) => `handbook range ${boundWords(l, input.unit)}${l.page ? ` (p. ${l.page})` : ""}`);
  const refuse = ls.filter((l) => l.severity !== "warn").map((l) => `must be ${boundWords(l, input.unit)}`);
  const text = [...warn, ...refuse].join(" · ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

// The default in words, and where it comes from: "default 50 (the handbook's)", "default 1 (no
// effect)", "default Ball bearing (typical)"; "" when there's none (the input is needed).
export function defaultText(input = {}) {
  if (input.default == null) return "";
  const shown = input.kind === "choice"
    ? (input.choices || []).find((c) => c.code === input.default)?.label || input.default
    : `${fmtNum(input.default)}${input.unit ? ` ${input.unit}` : ""}`;
  const why = { handbook: "the handbook’s", neutral: "no effect", typical: "a typical value" }[input.default_basis];
  return `Default ${shown}${why ? ` (${why})` : ""}`;
}

// A number input past one of its limits, in words (null when it's within them, blank or not a
// number): what the field shows under it as you type.
export function limitProblem(input = {}, raw = "") {
  const s = String(raw ?? "").trim();
  if (input.kind === "choice" || s === "") return null;
  const v = Number(s);
  if (!Number.isFinite(v)) return { severity: "refuse", text: "Not a number." };
  for (const l of input.limits || []) {
    const below = l.min != null && (v < l.min || (l.exclusive && v === l.min));
    const above = l.max != null && (v > l.max || (l.exclusive && v === l.max));
    if (below || above) {
      const words = l.severity === "warn"
        ? `Outside the handbook’s range (${boundWords(l, input.unit)}${l.page ? `, p. ${l.page}` : ""})${l.why ? `: ${l.why}` : ""}.`
        : `Must be ${boundWords(l, input.unit)}${l.why ? `: ${l.why}` : ""}.`;
      return { severity: l.severity === "warn" ? "warn" : "refuse", text: words };
    }
  }
  return null;
}

// The values typed, as the server takes them: blanks left out (they take the default), numbers as
// numbers, choices as their codes.
export function valuesForServer(values = {}, inputs = []) {
  const kinds = new Map(inputs.map((i) => [i.key, i.kind]));
  const out = {};
  for (const [k, raw] of Object.entries(values || {})) {
    const s = String(raw ?? "").trim();
    if (s === "") continue;
    if (kinds.get(k) === "choice") out[k] = s;
    else {
      const n = Number(s);
      out[k] = Number.isFinite(n) ? n : s;
    }
  }
  return out;
}

// The inputs still needed (no default and nothing typed).
export function missingInputs(inputs = [], values = {}) {
  return inputs.filter((i) => i.default == null && String(values?.[i.key] ?? "").trim() === "");
}

// A rate as shown: 3–4 significant figures, never NaN or Infinity.
export function fmtRate(v) {
  const n = Number(v);
  if (v == null || !Number.isFinite(n)) return "—";
  return sig(n);
}

// The model in words for a record row: "Base × 6 condition factors" / "Sum of 5 parts".
export function modelShape(cov = {}) {
  const modes = cov.modes || [];
  if (modes.length > 1) return `Sum of ${modes.length} parts or failure modes`;
  const f = modes[0]?.factors ?? cov.factors ?? 0;
  return `Base rate × ${f} condition factor${f === 1 ? "" : "s"}`;
}

// The source page's rows: one per component part or failure mode ({record, mode}), the component's
// name, the part, its base rate with the unit, and how many factors scale it.
export function modeRows(records = []) {
  const rows = [];
  for (const r of records) {
    const cov = r.covariate;
    if (!cov) continue;
    for (const m of cov.modes || []) {
      rows.push({
        id: `${r.id}#${m.key}`, recordId: r.id, component: r.name, equipment: r.equipment_type, mode: m.name,
        base: m.uses ? `Its own model: ${m.uses_name || m.uses}` : m.base === "from the inputs" ? "From the inputs" : `${m.base} ${unitShort(cov.rate_unit)}`,
        factors: m.uses ? "—" : String(m.factors), equation: cov.equation,
      });
    }
  }
  return rows;
}

// The model in words, the answer first: the record's own sentence.
export const modelWords = (rec) => rec?.covariate_model?.words || "";

// The result as one line: "0.442 failures per million hours (bearing 0.442)".
export function resultLine(result) {
  if (!result) return "";
  const words = { per_million_hours: "failures per million hours", per_million_cycles: "failures per million cycles",
    per_million_operations: "failures per million operations" }[result.unit] || result.unit_words || "";
  return `${fmtRate(result.total)} ${words}`;
}

// A line's conditions as the prediction keeps them (values cleaned) and its cycles an hour.
export function lineConditions(line = {}) {
  const c = {};
  for (const [k, v] of Object.entries(line.conditions || {})) {
    const s = String(v ?? "").trim();
    if (s === "") continue;
    const n = Number(s);
    c[k] = Number.isFinite(n) ? n : s;
  }
  const cph = Number(line.cycles_per_hour);
  return {
    ...(Object.keys(c).length ? { conditions: c } : {}),
    ...(String(line.cycles_per_hour ?? "").trim() !== "" && Number.isFinite(cph) && cph > 0 ? { cycles_per_hour: cph } : {}),
  };
}

// ---- fixing covariates at a position (CovariateBindPane.jsx) --------------------------------------

// A binding's address part: "nswc:nswc-11:bearing-rolling-load-rating", "alt:<id>", "ph:<id>".
export const bindingParam = (source, ref) => `${source}:${ref}`;
export function bindingFromParam(param) {
  const s = String(param || "");
  const i = s.indexOf(":");
  if (i < 1) return null;
  const source = s.slice(0, i);
  return ["nswc", "alt", "ph"].includes(source) ? { source, ref: s.slice(i + 1) } : null;
}

// What's ticked to start with: what the position's binding fixes when there is one; else, for an
// NSWC-11 model, its design inputs (fixed by the design), and for an ALT or PH model none (their
// stresses and covariates are use or environment by nature).
export function initialFix(source, inputs = [], binding = null) {
  if (binding?.fixed) return Object.fromEntries(inputs.map((i) => [i.key, i.key in binding.fixed]));
  return Object.fromEntries(inputs.map((i) => [i.key, source === "nswc" && i.role === "design"]));
}

// The values to start with: the binding's fixed ones, else each input's default (as text).
export function initialValues(inputs = [], binding = null) {
  return Object.fromEntries(inputs.map((i) => {
    const v = binding?.fixed?.[i.key] ?? i.default;
    return [i.key, v == null ? "" : String(v)];
  }));
}

// The binding the position saves: the ticked inputs with their values (as numbers or codes), and
// for ALT and PH what each covariate is. {binding, missing: [labels ticked with no value]}.
export function bindingToSave({ source, ref, inputs = [], fix = {}, values = {}, roles = {} }) {
  const ticked = inputs.filter((i) => fix[i.key]);
  const missing = ticked.filter((i) => String(values[i.key] ?? "").trim() === "").map((i) => i.label);
  const fixed = valuesForServer(Object.fromEntries(ticked.map((i) => [i.key, values[i.key]])), inputs);
  return {
    binding: { source, ref, fixed, ...(source === "nswc" ? {} : { roles: Object.fromEntries(inputs.map((i) => [i.key, roles[i.key] || i.role])) }) },
    missing,
  };
}

// The summary under the form: "3 of 14 fixed here; 11 set where it's used (an RBD block, or the
// diagram's Use and Environment values)", or "Every covariate fixed: a constant-rate model here".
export function bindSummary(source, inputs = [], fix = {}) {
  const n = inputs.filter((i) => fix[i.key]).length;
  if (inputs.length && n === inputs.length) {
    return source === "nswc"
      ? "Every covariate fixed: it's saved as a constant-rate model at this position."
      : "Every covariate fixed: a constant-stress model at this position.";
  }
  const open = inputs.length - n;
  return `${n} of ${inputs.length} fixed here; ${open} set where it's used (each RBD block, or the diagram's Use and Environment values).`;
}

// The diagram's Use and Environment values as the server keeps them: named rows only, a number
// where the value is one.
export function cleanConditions(rows = []) {
  return rows.filter((r) => String(r.name || "").trim() && String(r.value ?? "").trim() !== "").map((r) => {
    const n = Number(String(r.value).trim());
    return { name: String(r.name).trim(), role: r.role || "environment", unit: String(r.unit || "").trim(),
      value: Number.isFinite(n) ? n : String(r.value).trim() };
  });
}

// A diagram's blocks whose covariates were left open at their positions.
export const boundNodes = (graph) => (graph?.nodes || []).filter((n) => n.data?.model?.kind === "bound");
