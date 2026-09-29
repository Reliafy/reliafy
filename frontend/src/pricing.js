// Subscription prices as shown to users. The amounts actually charged are the
// Stripe Prices (STRIPE_PRO_PRICE_ID, STRIPE_AGENT_PRICE_ID) — keep these in
// step with them. Used by the landing page tiers and the /billing comparison.
export const PRO_PRICE = { amount: "US$19", per: "per month" };
export const AGENT_PRICE = { amount: "US$2", per: "per month" };
