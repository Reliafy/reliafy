// The percentage fields of each form, and how each one is checked (see
// percent.js). One table so every form treats a percentage the same way:
// typed as 95, sent as 0.95, and a value of 1 or less questioned unless a
// small percentage is normal for that field (a B-life's "% failed", a share,
// a β-factor). Tested in percentForms.test.js.
import { checkPercent } from "./percent.js";

const P = {}; // a probability, availability, reliability or confidence
const SMALL_OK = { fractionCheck: false }; // small percentages are normal here
const SHARE = { fractionCheck: false, allowMax: true }; // can be all of them
const opt = (o) => ({ ...o, optional: true });

export const PERCENT_FORMS = {
  failureFinding: { availability: P },
  demonstration: { reliability: P, confidence: P, design: opt(P), producerRisk: opt(P), bLife: SMALL_OK },
  sequential: { rTarget: P, rGood: P, confidence: P, producerRisk: P },
  lifeTest: { confidence: P, bLife: SMALL_OK, share: SHARE },
  acceleratedTest: { confidence: P, bLife: SMALL_OK },
  comparison: { power: P, confidence: P, drop: SMALL_OK, eventPct: SHARE },
  requirement: { bLife: SMALL_OK },
  rbdTargets: { target: P },
  rbdIntervals: { availability: P },
  rbdCheapest: { floor: opt(P) },
  rbdDesignLife: { reliability: opt(P) },
  calculator: { reliability: P, level: P },
  perDemand: { confidence: P },
  degradation: { confidence: P, reliability: P },
  tvc: { reliability: P, level: P },
  ccf: { beta: SMALL_OK },
};

// Check a form's percentage fields. ``values`` maps field → text; ``active``
// lists the fields on screen (default: every field in ``values`` the form
// knows). Returns the checks (for PercentField's ``check``), the fractions
// (null where not usable) and whether the form can run.
export function readPercents(form, values, active = null) {
  const spec = PERCENT_FORMS[form];
  if (!spec) throw new Error(`Unknown percent form ${form}`);
  const keys = (active || Object.keys(values)).filter((k) => k in spec);
  const checks = {};
  const fractions = {};
  for (const k of keys) {
    const c = checkPercent(values[k], spec[k]);
    checks[k] = c;
    fractions[k] = c.state === "ok" ? c.fraction : null;
  }
  const ready = keys.every((k) => checks[k].state === "ok" || checks[k].state === "empty");
  return { checks, fractions, ready };
}

// The options a field is checked with (for a PercentField without a check).
export const percentOptions = (form, field) => PERCENT_FORMS[form]?.[field] || P;
