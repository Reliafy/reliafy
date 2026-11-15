// Strategy › Overhaul and replace: what the tool still needs before Compute, the request it
// sends and the saved inputs. Pure functions, tested in overhaulReplace.test.js.

const blank = (v) => v === null || v === undefined || String(v).trim() === "";
const num = (v) => (blank(v) ? null : Number(v));

// The repairable model forms the policy takes: minimal repair only (failures from any age).
export const MINIMAL_REPAIR_FORMS = ["crow_amsaa", "duane", "hpp", "cox_lewis"];
// The forms typed in as two parameters (scale alpha, shape beta).
export const TYPED_FORMS = [
  { value: "crow_amsaa", label: "Crow-AMSAA (power law)" },
  { value: "duane", label: "Duane" },
];

// A saved repairable model the tool can use: a minimal-repair one ({family: "nhpp"} in the list).
export const usableRepairable = (m) => !!m && (m.family || "nhpp") === "nhpp";

// The model's time unit: a saved model's own, else the one typed (no default: a model in days
// read as hours gives an answer 24 times too short).
export const modelUnit = (model, typed) => String(model?.unit || "").trim() || String(typed || "").trim() || null;

// Why Compute is greyed out ("Enter the replacement cost."), or null when ready.
export function overhaulReplaceMissing({ model, f, unit }) {
  if (!model) return "Choose a repairable model, or enter its parameters.";
  if (model.source === "params" && (model.params || []).some((p) => !(Number(p) > 0))) return "Enter the model's parameters, both above 0.";
  if (blank(f.cost_repair)) return "Enter the cost of a repair.";
  if (blank(f.cost_overhaul)) return "Enter the cost of an overhaul.";
  if (blank(f.cost_replace)) return "Enter the replacement cost.";
  if (Number(f.cost_overhaul) <= Number(f.cost_repair)) return "An overhaul must cost more than a repair.";
  if (blank(f.overhaul_restores)) return "Enter how much of its age an overhaul takes off.";
  const r = Number(f.overhaul_restores);
  if (!(r > 0 && r <= 100)) return "An overhaul takes off more than 0% and up to 100% of the unit's age.";
  const down = ["downtime_repair", "downtime_overhaul", "downtime_replace"].some((k) => Number(f[k]) > 0);
  if (down && !(Number(f.downtime_cost) > 0)) return "Enter the cost of an hour down, or leave the downtimes blank.";
  if (!modelUnit(model, unit)) return "Enter the unit of the model's times (e.g. flight hours).";
  return null;
}

const FIELDS = ["cost_repair", "cost_overhaul", "cost_replace", "overhaul_restores", "downtime_repair",
  "downtime_overhaul", "downtime_replace", "downtime_cost", "max_overhauls"];

// The inputs as the server takes them (and a saved analysis keeps): the model as form + params
// (so a saved analysis can be worked out again), plus the saved model's id and name to show and
// reopen it. `extra`: more to keep with it (a position's model row, from the Explorer).
export function overhaulReplaceInputs(model, f, unit, extra = {}) {
  const out = { form: model.form, params: (model.params || []).map((p) => (typeof p === "object" ? p : Number(p))),
    unit: modelUnit(model, unit) };
  for (const k of FIELDS) {
    const v = num(f[k]);
    if (v !== null) out[k] = v;
  }
  if (model.source === "saved" && model.modelId) Object.assign(out, { model_id: model.modelId, model_name: model.name || "" });
  return { ...out, ...extra };
}

// The request: a saved model is read on the server (its live fit and its unit).
export function overhaulReplaceBody(model, f, unit) {
  const inputs = overhaulReplaceInputs(model, f, unit);
  return model.source === "saved" && model.modelId ? { ...inputs, recurrent_model_id: model.modelId } : inputs;
}

// "12%", "costs 3% more" — the best plan against another.
export function savingWords(pct) {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return "—";
  if (Math.abs(pct) < 0.05) return "the same";
  const p = Math.abs(pct) >= 10 ? Math.round(Math.abs(pct)) : Number(Math.abs(pct).toPrecision(2));
  return pct > 0 ? `${p}%` : `costs ${p}% more`;
}
