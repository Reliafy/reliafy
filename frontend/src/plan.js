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
