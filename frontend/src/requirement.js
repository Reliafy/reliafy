// A B-life requirement and the demonstration test that would show it (#295).
// Pure functions, so `node --test` covers them: a B-life's label, reading a
// link that opens the demonstration test pre-filled (b, life, conf, unit and
// β's source), and a fitted Weibull's β as that source.

// 10 → "B10", 0.1 → "B0.1".
export function bLabel(b) {
  return `B${Number(b).toLocaleString("en-US", { maximumFractionDigits: 4, useGrouping: false })}`;
}

const posNum = (s) => {
  const n = Number(s);
  return s != null && s !== "" && Number.isFinite(n) && n > 0 ? n : null;
};

// Read a link's query string into the demonstration test's starting inputs, or
// null when it carries no requirement. Values stay strings (the form's
// inputs); anything malformed is left out rather than half-applied. A model
// alone ("Plan a test" from a model, #294) brings its β and unit only.
export function parseDemoPrefill(search) {
  const q = new URLSearchParams(search || "");
  const b = posNum(q.get("b"));
  const life = posNum(q.get("life"));
  if (b == null || b >= 100 || life == null) {
    const model = (q.get("model") || "").trim();
    const unit = (q.get("unit") || "").trim();
    return model && q.get("b") == null && q.get("life") == null
      ? { modelId: model, ...(unit ? { unit: unit.slice(0, 40) } : {}) } : null;
  }
  const out = { target: "b_life", bLife: String(b), missionTime: String(life) };
  const conf = posNum(q.get("conf"));
  if (conf != null && conf < 100) out.confidence = String(conf);
  const unit = (q.get("unit") || "").trim();
  if (unit) out.unit = unit.slice(0, 40);
  const model = (q.get("model") || "").trim();
  if (model) out.modelId = model;
  else {
    const est = posNum(q.get("beta"));
    if (est != null) {
      const lo = posNum(q.get("beta_lo"));
      const hi = posNum(q.get("beta_hi"));
      out.beta = {
        name: (q.get("from") || "this fit").slice(0, 200),
        estimate: est,
        lower: lo != null && hi != null && lo <= est && est <= hi ? lo : null,
        upper: lo != null && hi != null && lo <= est && est <= hi ? hi : null,
      };
    }
  }
  return out;
}

// A saved (or just fitted) Weibull model's β as a source for the
// demonstration test: { name, estimate, lower, upper, modelId? }, or null
// for another distribution. ``results`` is the model's results payload.
export function betaSource(results, name, modelId = null) {
  if (!results) return null;
  const id = results.distribution_id && results.distribution_id !== "best" ? results.distribution_id : null;
  if ((id || String(results.distribution || "")).toLowerCase() !== "weibull") return null;
  const beta = (results.params || []).find((p) => p.name === "beta");
  if (!beta || !Number.isFinite(Number(beta.value))) return null;
  const ci = Array.isArray(beta.ci) && beta.ci.length === 2 && beta.ci.every((v) => Number.isFinite(Number(v)))
    ? beta.ci.map(Number)
    : null;
  return {
    name: name || "this fit",
    estimate: Number(beta.value),
    lower: ci ? ci[0] : null,
    upper: ci ? ci[1] : null,
    ...(modelId ? { modelId } : {}),
  };
}
