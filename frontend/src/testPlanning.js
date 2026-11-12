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

// ``use``: the use stress entered on the model's page (the model's units), carried over.
export const altPlanLink = (modelId, use = null) => {
  const u = Array.isArray(use) && use.length === 1 && Number.isFinite(Number(use[0])) ? Number(use[0]) : null;
  return `${TEST_PLANNING_PATH}/accelerated?model=${encodeURIComponent(modelId)}${u != null ? `&use=${encodeURIComponent(String(u))}` : ""}`;
};

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
    // "Check a test of my own" starts from the test as it was run.
    const levels = (r.levels || []).filter((l) => Number.isFinite((l.stress || [])[0]))
      .sort((a, b) => a.stress[0] - b.stress[0]);
    out.stresses = levels.map((l) => planningValue(l.stress[0])).join(", ");
    if (levels.every((l) => Number.isFinite(l.n))) out.unitsAt = levels.map((l) => String(l.n)).join(", ");
  }
  return out;
}

// Whether a number typed in a form is usable (finite).
export const given = (s) => s !== "" && s != null && Number.isFinite(Number(s));

// Whole-number ticks on a log axis (1, 2, 5, 10, 20, 50 …) within the data,
// so no label loses a digit as Plotly's minor log labels do ("2" for 20).
export function logTicks(xs) {
  const v = (xs || []).filter((x) => Number.isFinite(x) && x > 0);
  if (!v.length) return {};
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const ticks = [];
  for (let d = 10 ** Math.floor(Math.log10(lo)); d <= hi * 10; d *= 10) {
    for (const m of [1, 2, 5]) {
      const t = m * d;
      if (t >= lo / 1.0001 && t <= hi * 1.0001) ticks.push(t);
    }
  }
  return ticks.length >= 2 ? { tickvals: ticks, ticktext: ticks.map((t) => t.toLocaleString("en-US")) } : {};
}

