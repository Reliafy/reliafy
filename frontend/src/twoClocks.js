// Lives on two clocks (hours and starts): pure helpers for the result and the
// Explorer's panel, so `node --test` covers them. The numbers are the server's
// (SurPyval's at_usage); this only words and checks what the user typed.
import { formatNumber } from "./format.js";

// A starts-per-hour rate from what was typed: "0.125", "1/8" (1 start every 8 h),
// or "every 8" — or an error in words. { rate } | { error }.
export function parseRate(text) {
  const t = String(text ?? "").trim().toLowerCase();
  if (!t) return { error: "Enter starts per hour, e.g. 0.125 (1 start every 8 hours)." };
  const every = t.match(/^(?:1\s*\/|every)\s*([0-9]*\.?[0-9]+)$/);
  if (every) {
    const h = Number(every[1]);
    return h > 0 ? { rate: 1 / h } : { error: "Hours between starts must be above 0." };
  }
  const v = Number(t);
  if (!Number.isFinite(v)) return { error: "Enter starts per hour as a number, e.g. 0.125, or 1/8 for 1 start every 8 hours." };
  if (v < 0) return { error: "Starts per hour can't be negative." };
  return { rate: v };
}

// "0.125" for the input box: enough figures to round-trip what the server sent.
export const rateText = (rate) => (rate == null ? "" : String(Number(Number(rate).toPrecision(4))));

// A B-life row's value with its 90% lower bound: "6,294 h (at least 5,812 h)".
export function lifeText(b, unit) {
  if (!b || b.value == null) return "—";
  const u = unit ? ` ${unit}` : "";
  return `${formatNumber(b.value)}${u}` + (b.lower != null ? ` (at least ${formatNumber(b.lower)}${u})` : "");
}

// The B-life with a label from an at-rate answer's life summary.
export const bLife = (atRate, label) => (atRate?.life?.b_lives || []).find((b) => b.label === label) || null;

// Where a rate came from, in words, for the Explorer panel: "From the operating plan …".
export function sourceWords(usage) {
  if (!usage) return "";
  return usage.text || "";
}

// The k reading: "One start wears it as much as 18.4 hours of running (90% range 14.8–22.8)".
export function kWords(result) {
  const k = (result?.params || []).find((p) => p.name === "k");
  if (!k) return "";
  const c = result.clocks || {};
  const range = k.ci?.[0] != null && k.ci?.[1] != null
    ? ` (90% range ${formatNumber(k.ci[0])}–${formatNumber(k.ci[1])})` : "";
  return `One ${c.second_one || "start"} wears it as much as ${formatNumber(k.value)} ${c.first_word || "hours"} of running${range}.`;
}
