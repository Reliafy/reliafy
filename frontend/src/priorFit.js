// New model's "With a prior" (FitFlow.jsx): when the data allows it, and the request it sends to
// /api/models/fit-with-prior. The prior's own inputs and rules are the Explorer's (fitDialog.js:
// initialFit, bodyOf, problem), so both places ask for a prior the same way; the class's history
// is a prior only on a position, so it isn't offered here.
import { PRIOR_CHOICES, bodyOf, problem } from "./fitDialog.js";

export const DATASET_PRIOR_CHOICES = PRIOR_CHOICES.filter((p) => p.value !== "class");

// Why the data can't be fitted with a prior (null when it can): a fit with a prior takes one time
// column and a status column, as the Explorer's does.
export function priorBlocked(mapping = {}, { hasCovariates = false, tvc = null } = {}) {
  if (tvc || hasCovariates) return "A fit with a prior takes no covariates: clear them on the Data step to use one.";
  if (mapping.e) return "A fit with a prior takes no failure-mode column: clear it on the Data step to use one.";
  if (mapping.xl || mapping.xr) return "A fit with a prior takes one time column, not the earliest and latest possible failure times.";
  if (mapping.n) return "A fit with a prior takes one row per unit, not a count column.";
  if (mapping.tl || mapping.tr) return "A fit with a prior doesn't take truncation (observed from / until) yet.";
  if (mapping.u) return "A fit with a prior reads every time in one unit and can't convert each row's unit yet: fit without a prior, or put the times in one unit in your sheet.";
  if (!mapping.x) return "Pick the time column on the Data step first.";
  return null;
}

// What stops the fit with a prior asking yet (null once it can): the data's unit, then the prior's.
export function priorProblem(state, unit) {
  if (!String(unit || "").trim()) return "Give the data's unit on the Data step first: the prior is read in it.";
  return problem({ ...state, method: "bayes", data: "position" });
}

// The request: the data (a saved dataset, or the table's CSV text), its columns, and the prior.
//   source  { datasetId } or { content }
export function priorRequest(state, mapping, unit, source, extra = {}) {
  const body = bodyOf({ ...state, method: "bayes", data: "position", unit: String(unit || "").toLowerCase() });
  return {
    ...(source.datasetId ? { dataset_id: source.datasetId } : { content: source.content }),
    time_column: mapping.x,
    censor_column: mapping.c || null,
    ...(mapping.c && mapping.c_map ? { c_map: mapping.c_map } : {}),
    ...(mapping.c && mapping.c_invert ? { c_invert: true } : {}),
    unit: String(unit || "").toLowerCase(),
    distribution: body.distribution === "best" ? "weibull" : body.distribution,
    prior: body.prior,
    trust: body.trust,
    ...(body.age ? { age: body.age } : {}),
    // A required B10: the answer then gives the chance it is met.
    ...(Number(state.need) > 0 ? { need: Number(state.need) } : {}),
    ...extra,
  };
}

// The distribution is asked only where the prior doesn't fix it: a saved model and a B10 bring
// their own family, and typed numbers choose it beside them.
export const priorAsksDistribution = (kind) => ["library", "around"].includes(kind);
