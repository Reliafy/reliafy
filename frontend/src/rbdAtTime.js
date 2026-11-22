// The repairable calculator's "Availability at a time" answer (components/RbdCalculator.jsx):
// the plain-words parts, kept pure so they can be tested.
import { formatNumber } from "./format.js";

// "At 50 hours from new, the system is up with a 90.98% chance." ``pct`` formats a fraction.
export function atTimeLead(row, unitText, fromNow, pct) {
  const u = unitText ? ` ${unitText}` : "";
  return `At ${formatNumber(row.t, { sig: 4 })}${u} ${fromNow ? "from now" : "from new"}, the system is up with a ${pct(row.availability)} chance.`;
}

// Who the answer is for: exact, so no sampling range, and where the fitted-model range lives.
export const AT_TIME_NOTE =
  "Exact: worked out from the failure and repair models, not simulated, so there is no sampling range. " +
  "It takes the models as given; to see how their fitted uncertainty widens it (90% two-sided), use What to improve.";
