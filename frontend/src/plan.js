// Whether to mark Pro-only actions with a "Pro" tag before they're clicked.
// The same rule as the server's premium_compute_allowed (backend/services/
// billing.py): operators, every user when billing is off (self-hosted, the
// single-user mode) and Pro subscribers are entitled, so they see no tags.
// ``billing`` is GET /api/billing's body (null while loading or on error:
// no tags rather than a wrong one).
export function showProTags(billing) {
  if (!billing || !billing.billing_enabled) return false;
  if (billing.admin) return false;
  return billing.plan !== "pro";
}

// Whether a Free (or Agent) user has used up a storage limit (GET /api/billing:
// ``usage`` against ``plan_caps``; the server counts only the user's own items,
// never shared samples). Returns { used, cap } at or past the cap, else null:
// Pro, operators, self-hosted installs and a plan not yet loaded have none.
export function storageCapReached(billing, kind) {
  if (!billing || !billing.billing_enabled || billing.admin) return null;
  const cap = billing.plan_caps?.[kind];
  const used = billing.usage?.[kind];
  if (cap == null || used == null) return null;
  return used >= cap ? { used, cap } : null;
}

// The Free plan's storage limits: the defaults of FREE_MAX_* in
// backend/config.py, in the order of CAPPED_KINDS (backend/services/billing.py).
// The public pricing copy (Landing) reads them from here because a signed-out
// visitor has no GET /api/billing to ask; signed-in pages use the live
// ``caps`` from that call. plan.test.js fails if this drifts from config.py.
export const FREE_CAPS = Object.freeze({
  datasets: 3,
  models: 3,
  rbds: 1,
  degradation_models: 1,
  tracked_items: 3,
  fleets: 1,
  outage_logs: 1,
  fault_trees: 1,
  reliability_predictions: 1,
  maintainability_predictions: 1,
  libraries: 1,
});

// Each capped kind: [key, label on the Billing page, one, many] — ``one`` and
// ``many`` name a saved item in a sentence ("1 RBD", "3 datasets").
export const CAPPED_KINDS = [
  ["datasets", "Datasets", "dataset", "datasets"],
  ["models", "Models", "model", "models"],
  ["rbds", "RBDs", "RBD", "RBDs"],
  ["degradation_models", "Degradation models", "degradation model", "degradation models"],
  ["tracked_items", "Tracked items", "tracked item", "tracked items"],
  ["fleets", "Fleet forecasts", "fleet failure forecast", "fleet failure forecasts"],
  ["outage_logs", "Outage logs", "outage log", "outage logs"],
  ["fault_trees", "Fault trees", "fault tree", "fault trees"],
  ["reliability_predictions", "Reliability predictions", "reliability prediction", "reliability predictions"],
  ["maintainability_predictions", "Maintainability predictions", "maintainability prediction", "maintainability predictions"],
  ["libraries", "Data libraries", "data library", "data libraries"],
];

// "1 RBD", "3 datasets": a count with the kind's noun.
export function capPhrase(kind, caps = FREE_CAPS) {
  const row = CAPPED_KINDS.find(([k]) => k === kind);
  const n = caps?.[kind];
  if (!row || n == null) return null;
  return `${n} ${n === 1 ? row[2] : row[3]}`;
}

const joinAnd = (parts) =>
  parts.length < 2 ? parts.join("") : `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}`;

// The Free plan's storage limits as a few plain lines for a plan card, grouped
// as people think of them. Every capped kind appears exactly once.
export function freeStorageLines(caps = FREE_CAPS) {
  const p = (k) => capPhrase(k, caps);
  const lines = [
    `Save ${joinAnd([p("datasets"), p("models")])}`,
    joinAnd([p("rbds"), p("fault_trees"), p("outage_logs")]),
    joinAnd([p("reliability_predictions"), p("maintainability_predictions"), p("libraries")]),
    `Degradation tracking: ${joinAnd([p("degradation_models"), p("tracked_items")])}`,
    p("fleets"),
  ];
  return lines.map((l) => l.charAt(0).toUpperCase() + l.slice(1));
}

// A refused save past a storage limit (the server's 402 with ``code: "cap"``)?
// Plain-string errors and other refusals aren't.
export function isCapRefusal(error) {
  return !!error && typeof error === "object" && error.code === "cap";
}

// An error's text, whether it's an Error or already a string.
export function errorText(error) {
  if (!error) return "";
  return typeof error === "string" ? error : error.message || String(error);
}
