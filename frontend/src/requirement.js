// A B-life requirement on a fitted model, and the demonstration test that
// would show it (#295). Pure functions, so `node --test` covers them: the
// verdict in words (the numbers and the verdict come from the backend's life
// path, which reads them off SurPyval), the link that opens the
// demonstration test pre-filled, and reading that link back.

import { formatNumber } from "./format.js";
import { unitInText } from "./components/unitText.js";

// 10 → "B10", 0.1 → "B0.1".
export function bLabel(b) {
  return `B${Number(b).toLocaleString("en-US", { maximumFractionDigits: 4, useGrouping: false })}`;
}

const pctText = (c) => `${Number((c * 100).toFixed(4))}%`;

// The verdict as a tone and a sentence in segments, [text, bold] — the
// numbers bold. ``check`` is the life path's answer to a requirement:
// { b, label, life, confidence, estimate, lower, verdict, estimate_meets }.
//   "meets"          good: the lower bound is at or above the requirement
//   "does_not_meet"  bad: it's below — even when the estimate is above
//   "unknown"        caveat: the model has no bounds to check with
// ``note``: a second, muted line (or null).
export function requirementVerdict(check, unit = "") {
  if (!check) return null;
  const u = unitInText(unit);
  const withUnit = (v) => (u ? `${formatNumber(v)} ${u}` : formatNumber(v));
  const label = check.label || bLabel(check.b);
  const conf = pctText(check.confidence);
  const required = formatNumber(check.life);
  const best = check.estimate != null ? [[" Best estimate ", false], [formatNumber(check.estimate), true], [".", false]] : [];
  if (check.verdict === "meets") {
    return {
      tone: "good",
      short: "Meets",
      segments: [
        ["Meets: ", false], [`at ${conf} confidence ${label} ≥ `, false], [withUnit(check.lower), true],
        [", at or above the ", false], [required, true], [" required.", false], ...best,
      ],
      note: null,
    };
  }
  if (check.verdict === "does_not_meet") {
    return {
      tone: "bad",
      short: "Does not meet",
      segments: [
        ["Does not meet: ", false], [`at ${conf} confidence ${label} ≥ `, false], [withUnit(check.lower), true],
        [", below the ", false], [required, true], [" required.", false], ...best,
      ],
      note: check.estimate_meets
        ? `The best estimate meets it, but these data can't show it at ${conf} confidence yet: more data or a demonstration test could.`
        : null,
    };
  }
  if (check.estimate == null) {
    return { tone: "caveat", short: "Can't check", segments: [[`Can't check: the model gives no ${label}.`, false]], note: null };
  }
  return {
    tone: "caveat",
    short: "Can't check",
    segments: [
      [`Can't check at ${conf} confidence: this model has no confidence bounds. The best estimate of ${label} is `, false],
      [withUnit(check.estimate), true],
      [`, ${check.estimate_meets ? "at or above" : "below"} the `, false], [required, true], [" required.", false],
    ],
    note: check.bounds_note || null,
  };
}

// The verdict's plain text (a title attribute, a test).
export const verdictText = (v) => (v ? v.segments.map(([t]) => t).join("") : "");

export const DEMO_PATH = "/strategy/demonstration-test";

// The demonstration test, pre-filled with a requirement (#295): ``b`` (the x
// in Bx), ``life``, ``confidence`` (%), the model's ``unit``, and β's
// source — a saved model's ``modelId``, or (a fit not saved yet) its
// ``beta`` = { name, estimate, lower, upper }.
export function demoLink({ b, life, confidence, unit, modelId = null, beta = null }) {
  const q = new URLSearchParams();
  q.set("b", String(b));
  q.set("life", String(life));
  if (confidence != null) q.set("conf", String(confidence));
  if (unit) q.set("unit", unit);
  if (modelId) q.set("model", modelId);
  else if (beta && Number.isFinite(beta.estimate)) {
    q.set("beta", String(beta.estimate));
    if (Number.isFinite(beta.lower) && Number.isFinite(beta.upper)) {
      q.set("beta_lo", String(beta.lower));
      q.set("beta_hi", String(beta.upper));
    }
    if (beta.name) q.set("from", beta.name);
  }
  return `${DEMO_PATH}?${q.toString()}`;
}

const posNum = (s) => {
  const n = Number(s);
  return s != null && s !== "" && Number.isFinite(n) && n > 0 ? n : null;
};

// Read a demoLink back into the demonstration test's starting inputs, or
// null when it carries no requirement. Values stay strings (the form's
// inputs); anything malformed is left out rather than half-applied.
export function parseDemoPrefill(search) {
  const q = new URLSearchParams(search || "");
  const b = posNum(q.get("b"));
  const life = posNum(q.get("life"));
  if (b == null || b >= 100 || life == null) return null;
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
