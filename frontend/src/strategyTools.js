// The Strategy tools' shared bits: which guide "Read the guide" opens, which
// saved analyses each tool makes, and why Compute is greyed out.

// Each tool's saved-analysis kind and its guide.
export const STRATEGY_TOOLS = {
  replacement: {
    kind: "optimal_replacement",
    noun: "replacement analyses",
    help: { walkthrough: "replacement", guide: "optimal-replacement-interval" },
  },
  calendar: {
    kind: "calendar_replacement",
    noun: "shutdown-calendar analyses",
    help: { guide: "optimal-replacement-interval" },
  },
  compare: { kind: "compare_two", noun: "comparisons", help: { guide: "compare-groups" } },
  overhaulReplace: { kind: "overhaul_replace", noun: "overhaul-and-replace analyses", help: { guide: "overhaul-and-replace" } },
  failureFinding: { kind: "failure_finding", noun: "failure-finding analyses", help: { guide: "failure-finding-interval" } },
  testPlanning: { kind: "demonstration_test", noun: "demonstration test plans", help: { guide: "check-a-requirement-and-plan-a-test" } },
  sequential: { kind: "sequential_test", noun: "sequential test plans", help: { guide: "check-a-requirement-and-plan-a-test" } },
  accelerated: { kind: "demonstration_test", noun: "demonstration test plans", help: { guide: "accelerated-life-testing" } },
};

// The Strategy list filtered to one kind of analysis.
export const strategyListFor = (kind) => `/strategy?kind=${encodeURIComponent(kind)}`;

const blank = (v) => v === "" || v === null || v === undefined;

// What a model-based tool still needs before Compute can run: a model, and a
// plain distribution (not a proportional-hazards fit). ``source`` is what the
// picker shows: with "Parameters" open, the parameters are what's missing.
function modelMissing(model, source) {
  if (!model) {
    if (source === "params") return "Enter the model's parameters.";
    if (source === "mean") return "Enter the mean life.";
    return "Choose a non-repairable model first.";
  }
  if (model.kind === "regression" || !model.distribution_id) return "Choose a plain distribution model.";
  return null;
}

// The time unit a Strategy result is in: a saved model's own unit, else the
// one typed beside typed parameters. Never a default: a model fitted in days
// read as hours gives an answer 24 times too short. null when there is none.
export function strategyUnit(model, typed) {
  const own = String(model?.unit ?? "").trim();
  if (own) return own;
  const t = String(typed ?? "").trim();
  return t || null;
}

// Typed parameters carry no unit, so one must be entered (no default).
function unitMissing(model, unit) {
  if (strategyUnit(model, unit)) return null;
  return "Enter the unit of the model's times (e.g. days).";
}

// Optimal replacement: the model, both costs and the model's time unit. null when ready.
export function replacementMissing({ model, planned, unplanned, unit, source }) {
  const m = modelMissing(model, source);
  if (m) return m;
  if (blank(planned) && blank(unplanned)) return "Enter both costs.";
  if (blank(planned)) return "Enter the planned replacement cost.";
  if (blank(unplanned)) return "Enter the unplanned (failure) cost.";
  return unitMissing(model, unit);
}

// Failure finding: the model and a usable target availability (``availCheck``
// is percent.js's checkPercent of the field; the field itself says what's
// wrong with a value). null when ready.
export function failureFindingMissing({ model, availability, availCheck, unit, source }) {
  const m = modelMissing(model, source);
  if (m) return m;
  if (blank(String(availability ?? "").trim())) return "Enter a target availability.";
  if (availCheck && availCheck.state !== "ok") return "Check the target availability.";
  return unitMissing(model, unit);
}

// The line under a long exact compute: what it's doing, how long so far,
// and (past 20 s) that it's still going and can be cancelled.
export function computeWaitText(doing, secs) {
  const took = secs < 60 ? `${secs} s` : `${Math.floor(secs / 60)} min ${secs % 60} s`;
  const tail = secs >= 20 ? " A busy server or a long calendar can take a minute or two; Cancel stops it." : "";
  return `${doing}: ${took} so far.${tail}`;
}
