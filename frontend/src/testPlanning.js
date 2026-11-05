// Test planning (Strategy › Test planning): its tabs and their paths, the
// form helpers the tabs share, and the accelerated-test prefill from a saved
// ALT model. Pure logic, tested in testPlanning.test.js.

export const TEST_PLANNING_PATH = "/strategy/test-planning";

// The tabs, in order. The Demonstration tab is the page's own path, so the
// old /strategy/demonstration-test links land on it.
export const TEST_PLAN_TABS = [
  { id: "demonstration", label: "Demonstration", path: TEST_PLANNING_PATH },
  { id: "sequential", label: "Sequential test", path: `${TEST_PLANNING_PATH}/sequential` },
  { id: "life", label: "Life test", path: `${TEST_PLANNING_PATH}/life` },
  { id: "accelerated", label: "Accelerated test", path: `${TEST_PLANNING_PATH}/accelerated` },
  { id: "comparison", label: "Comparison", path: `${TEST_PLANNING_PATH}/comparison` },
];

// The tab a path shows (the Demonstration tab for the page itself, or
// anything unknown under it).
export function tabFromPath(pathname) {
  const p = String(pathname || "").replace(/\/+$/, "");
  const hit = TEST_PLAN_TABS.find((t) => t.id !== "demonstration" && t.path === p);
  return hit ? hit.id : "demonstration";
}

// Form values are strings: "" (or null) is "not given".
export const num = (s) => (s === "" || s == null ? null : Number(s));
// A percentage typed as 90 → 0.9.
export const frac = (s) => (s === "" || s == null ? null : Number(s) / 100);

// The life-stress models a plan takes (the app's single-stress ones whose
// log life is linear in a function of the stress) and their parameters.
export const PLAN_LIFE_MODELS = {
  arrhenius: { label: "Arrhenius", params: ["a", "b"] },
  eyring: { label: "Eyring", params: ["a", "b"] },
  inverse_power: { label: "Inverse power law", params: ["a", "n"] },
};
export const PLAN_DISTRIBUTIONS = { weibull: "Weibull", lognormal: "Lognormal" };

export const altPlanLink = (modelId) => `${TEST_PLANNING_PATH}/accelerated?model=${encodeURIComponent(modelId)}`;

// A saved ALT model's planning values for the next test, or null when the
// plan can't use it (two stresses, or a distribution other than Weibull or
// lognormal). Strings, as the form holds them.
// A fitted value as a form field's starting value: 4 significant figures, in a
// form a number field accepts (5.158909835425411e-26 → "5.159e-26",
// 15.829945744196094 → "15.83", 6694 → "6694"). A planning value is a best
// guess, and a field full of digits reads as more certain than the fit is.
export function planningValue(v) {
  const n = Number(v);
  return Number.isFinite(n) ? String(Number(n.toPrecision(4))) : "";
}

export function altPrefill(results) {
  const r = results || {};
  const model = PLAN_LIFE_MODELS[r.life_model_id];
  if (!model || !PLAN_DISTRIBUTIONS[r.distribution_id] || (r.stresses || []).length !== 1) return null;
  const coeffs = Object.fromEntries((r.coefficients || []).map((c) => [c.name, c.value]));
  if (model.params.some((n) => !Number.isFinite(coeffs[n]))) return null;
  const shape = (r.params || [])[0]?.value;
  if (!Number.isFinite(shape) || shape <= 0) return null;
  const tested = (r.levels || []).map((l) => (l.stress || [])[0]).filter(Number.isFinite);
  const out = {
    distribution: r.distribution_id,
    lifeModel: r.life_model_id,
    params: Object.fromEntries(model.params.map((n) => [n, planningValue(coeffs[n])])),
    shape: planningValue(shape),
    unit: r.unit || "",
    stressUnit: r.stresses[0].unit || "",
  };
  if (tested.length) {
    // The highest stress tested is a safe highest stress for the next test.
    const top = [...tested].sort((a, b) => b - a)[0];
    out.highStress = planningValue(top);
  }
  return out;
}

// Whether a number typed in a form is usable (finite).
export const given = (s) => s !== "" && s != null && Number.isFinite(Number(s));
