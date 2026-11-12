// A new model's name, before the user gives one: the distribution and the
// data it was fitted to ("Weibull — Seal history"). Values typed or pasted in
// have no name of their own, so they get the day instead ("Weibull — pasted
// values, 12 Nov 2026"): two quick fits never share a name like
// "pasted-values". The fit asks for a name on Save (FitFlow), starting here.
import { formatDate } from "./dates.js";

export const PASTED_FILE = "pasted-values.csv";

export function dataName({ fileName = "", sourceName = "", today = new Date() } = {}) {
  if (fileName === PASTED_FILE) return `Pasted values, ${formatDate(today)}`;
  const raw = fileName || sourceName || "dataset";
  return raw.replace(/\.(csv|tsv|txt|xlsx?)$/i, "").replace(/\s*\(sample\)\s*$/i, "").trim() || "dataset";
}

export function defaultFitName(distribution, source = {}, { prior = false } = {}) {
  const dist = String(distribution || "Model").trim();
  const data = dataName(source);
  return `${dist}${prior ? " with a prior" : ""} — ${source.fileName === PASTED_FILE ? data.charAt(0).toLowerCase() + data.slice(1) : data}`;
}
