// Costs with the workspace's currency symbol (Settings › Currency): "$255",
// "€1,200", "AUD 3,400". Costs are plain numbers in whatever currency the
// user works in; the symbol only labels them, nothing is converted. A symbol
// of letters ("AUD") is followed by a space; a sign ("$", "€", "A$") isn't.
// Tested in money.test.js.
import { formatNumber } from "./format.js";

const MISSING = "—";

const spaced = (sym) => /[A-Za-z]$/.test(sym);

export const DEFAULT_CURRENCY = "$";

// The active workspace's symbol, set by WorkspaceProvider before the pages
// render (as workspaceDate.js's time zone is), so module-level formatters
// (an RBD's fmtMoney) label costs without each caller passing it.
let current = DEFAULT_CURRENCY;
export function setWorkspaceCurrency(symbol) {
  current = String(symbol || "").trim() || DEFAULT_CURRENCY;
}
export const workspaceCurrency = () => current;

// A formatted amount ("1,200", "-35") with the symbol: "$1,200", "−$35".
export function prefixCurrency(amount, symbol = current) {
  const text = String(amount ?? "");
  if (text === "" || text === MISSING) return MISSING;
  const sym = String(symbol || DEFAULT_CURRENCY).trim() || DEFAULT_CURRENCY;
  const neg = /^[-−]/.test(text);
  return `${neg ? "−" : ""}${sym}${spaced(sym) ? " " : ""}${neg ? text.slice(1) : text}`;
}


// A cost: (255.4, "$") → "$255"; (-1200, "€") → "−€1,200"; (3400, "AUD") →
// "AUD 3,400". ``sig`` as formatNumber (3 by default).
export function formatCost(v, symbol = current, { sig = 3 } = {}) {
  if (v == null || v === "") return MISSING;
  const n = Number(v);
  if (!Number.isFinite(n)) return MISSING;
  const sym = String(symbol || DEFAULT_CURRENCY).trim() || DEFAULT_CURRENCY;
  const body = formatNumber(Math.abs(n), { sig });
  return `${n < 0 ? "−" : ""}${sym}${spaced(sym) ? " " : ""}${body}`;
}

// A cost per time: (255, "$", "year") → "$255 a year"; (0.42, "€", "hours")
// → "€0.42 per hour". The unit's plural "s" is dropped.
export function formatCostRate(v, symbol, unit, opts) {
  const s = formatCost(v, symbol, opts);
  if (s === MISSING || !unit) return s;
  const u = String(unit).trim().toLowerCase().replace(/s$/, "");
  return u === "year" || u === "month" || u === "week" || u === "day" ? `${s} a ${u}` : `${s} per ${u}`;
}

// A field label with the symbol: ("Planned replacement cost", "€") →
// "Planned replacement cost (€)".
export const costLabel = (label, symbol = DEFAULT_CURRENCY) => `${label} (${symbol || DEFAULT_CURRENCY})`;

// A server sentence's bare costs labelled: "Long-run cost about 255 a year"
// → "Long-run cost about $255 a year" (the calendar's headline, worded on
// the server, which doesn't know the workspace's symbol).
export function labelCostsInText(text, symbol = DEFAULT_CURRENCY) {
  const sym = String(symbol || DEFAULT_CURRENCY).trim() || DEFAULT_CURRENCY;
  const sp = spaced(sym) ? " " : "";
  return String(text ?? "").replace(/\b(cost about|costs about|cost of about) (−|-)?(\d[\d,]*(?:\.\d+)?(?:e[+-]?\d+)?)/g,
    (_, lead, neg, n) => `${lead} ${neg ? "−" : ""}${sym}${sp}${n}`);
}
