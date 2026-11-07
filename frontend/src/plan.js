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
