// "Adjust for conditions…" (backend/services/model_adjust.py): a life model with a known hazard ratio,
// SurPyval's hr. hr times the hazard at every age, the same shape: R(t) = R0(t) ** hr. The numbers
// (B10 and mean life before and after, their bounds) come from the server; this file reads the
// form and words the answer. Pure, so `node --test` covers it.

import { fmt } from "./explorerModels.js";

// The life scales offered in words, and what each means. Only where a life scale is exact (a
// Weibull or an exponential, no offset, LFP or zero inflation): the server converts it.
export const LIFE_SCALES = [
  { value: "0.5", label: "about half as long" },
  { value: "0.667", label: "about 2/3 as long" },
  { value: "0.75", label: "about 3/4 as long" },
  { value: "1.25", label: "about 1¼ times as long" },
  { value: "1.5", label: "about 1½ times as long" },
  { value: "2", label: "about twice as long" },
];

// Can this saved model be adjusted? A single-distribution life model with parameters; null when it
// can, else why not (the server says the same in full).
export function adjustableWhy(model) {
  const r = model?.results;
  if (!model || !r) return "The model isn't loaded yet.";
  if (model.kind !== "distribution" || r.kind !== "distribution") return "Only a single-distribution life model can be adjusted.";
  if (r.distribution_id === "mixture" || r.method === "bayesian_update" || (model.spec || {}).method === "bayesian_update")
    return "Only a single-distribution life model can be adjusted.";
  if (!(r.params || []).length) return "This model has no distribution parameters to adjust.";
  if (r.no_finite_maximum) return "This fit has no finite maximum: refit it first.";
  return null;
}

// Whether a life scale is exact for it (the server's life_scale_note, worked out the same way so the
// choice is offered before a preview comes back).
export function lifeScaleExact(results) {
  const id = String(results?.distribution_id || "").toLowerCase();
  if (id !== "weibull" && id !== "exponential") return false;
  const x = results?.extras || {};
  return !["gamma", "p", "f0"].some((k) => x[k] != null);
}

// The form's numbers as the request's: {hazardRatio} or {lifeScale}, or {error} in words.
export function adjustRequest(mode, text) {
  const raw = String(text ?? "").trim().replace(/,/g, "");
  if (!raw) return { error: mode === "life" ? "Choose how long it lasts here." : "Enter a hazard ratio, e.g. 1.5." };
  const v = Number(raw);
  if (!Number.isFinite(v) || v <= 0) {
    return { error: mode === "life" ? "Enter a life scale above 0, e.g. 0.67." : "Enter a hazard ratio above 0, e.g. 1.5 for harsher conditions." };
  }
  if (mode === "life") return { lifeScale: v };
  if (v < 0.001 || v > 1000) return { error: "Enter a hazard ratio between 0.001 and 1,000." };
  return { hazardRatio: v };
}

// "1.5 times the hazard: harsher conditions, failures come sooner."
export function ratioWords(hr) {
  const x = Number(hr);
  if (!Number.isFinite(x)) return "";
  if (Math.abs(x - 1) < 1e-9) return "The same hazard: nothing changes.";
  return x > 1
    ? `${fmt(x)} times the hazard at every age: harsher conditions, so failures come sooner.`
    : `${fmt(x)} times the hazard at every age: milder conditions, so failures come later.`;
}

// One figure with its bound, for the before-and-after table: "324.6 h (≥ 190.2 h)".
export function withLower(value, lower, unit) {
  if (value == null) return "—";
  const u = unit ? ` ${unit}` : "";
  return lower != null ? `${fmt(value)}${u} (≥ ${fmt(lower)}${u})` : `${fmt(value)}${u}`;
}

// The before-and-after rows of a preview: [{label, before, after, change}], change as "−18%".
export function compareRows(preview) {
  if (!preview) return [];
  const unit = preview.unit ? String(preview.unit).toLowerCase() : "";
  const change = (a, b) => {
    if (a == null || b == null || !(Number(a) > 0)) return "—";
    const pct = (Number(b) / Number(a) - 1) * 100;
    if (Math.abs(pct) < 0.05) return "0%";
    return `${pct > 0 ? "+" : "−"}${fmt(Math.abs(pct))}%`;
  };
  const { before = {}, after = {} } = preview;
  return [
    { id: "b10", label: "B10 life", before: withLower(before.b10, before.b10_lower, unit),
      after: withLower(after.b10, after.b10_lower, unit), change: change(before.b10, after.b10) },
    { id: "mean", label: "Mean life", before: withLower(before.mean, before.mean_lower, unit),
      after: withLower(after.mean, after.mean_lower, unit), change: change(before.mean, after.mean) },
  ];
}

// What's said about the bounds under the table: the level and side, then what SurPyval doesn't give.
export function boundsWords(preview) {
  if (!preview) return [];
  // No bounds at all (a model from parameters): say why, and nothing about their level.
  const none = preview.after?.bounds_note || preview.before?.bounds_note;
  if (none) return [none];
  const out = ["Bounds are 90% one-sided lower bounds (≥), with the hazard ratio held fixed."];
  if (preview.after?.mean_note) out.push(preview.after.mean_note);
  return out;
}

// The model page's line for a model adjusted from another: "Adjusted for conditions from Pump: 1.5 × hazard."
export function adjustedLine(results) {
  const a = results?.adjusted;
  if (!a) return null;
  return { from: a.from_model_id, name: a.from_name || "another model", ratio: fmt(a.hazard_ratio) };
}
