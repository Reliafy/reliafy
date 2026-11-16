// Lives on two clocks (hours and starts, flight hours and landings, hours and
// cycles...): pure helpers for the result, the reading and the Explorer's panel,
// so `node --test` covers them. The numbers are the server's (SurPyval's
// at_usage); this only words and checks what the user typed, in the user's units:
// the first clock's (the model's unit, "hours") and the second's ("landings").
import { formatNumber, singularUnit } from "./format.js";
import { unitInText } from "./components/unitText.js";

// What a model saved before the second clock had a unit reads as (display only).
export const LEGACY_UNIT = "starts";

// A unit read for many: "cycle" → "cycles"; "cycles", "km", "kWh" stay as they are.
// The backend's twin is two_clocks.plural_unit.
export function pluralUnit(unit) {
  const text = String(unit ?? "").trim();
  const m = text.match(/^(.*?)([A-Za-z]{3,})$/s);
  if (!m) return text;
  const word = m[2];
  if (word !== word.toLowerCase() || /(s|x|z|ch|sh|y)$/.test(word) || word === "km" || word === "mm") return text;
  return m[1] + word + "s";
}

// The second clock's unit as typed, tidied (two_clocks.clean_unit).
export const cleanUnit = (unit) => {
  const text = String(unit ?? "").split(/\s+/).filter(Boolean).join(" ").slice(0, 40);
  return text ? pluralUnit(text) : "";
};

const FILLER = new Set(["no", "num", "number", "of", "count", "counts", "total", "cum", "cumulative", "n", "nr",
  "qty", "since", "new", "at", "failure", "to", "date", "the"]);

// The second clock's unit guessed from its column's name: "Landings" → "landings",
// "num_cycles" → "cycles", "Distance (km)" → "km"; "uses" when the name says nothing.
// The backend's twin is two_clocks.default_unit.
export function defaultSecondUnit(column) {
  const name = String(column ?? "").trim();
  const paren = name.match(/\(([^()]+)\)\s*$/);
  if (paren) return cleanUnit(paren[1].toLowerCase());
  const words = name.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z]+/)
    .filter((w) => w.length > 1 && !FILLER.has(w));
  return words.length ? cleanUnit(words.slice(-2).join(" ")) : "uses";
}

// How to say the two clocks. ``clocks``: the server's words (result.clocks,
// at_rate.clocks), else built from the first clock's unit and the second's.
export function clockWords(clocks, unit = "", secondUnit = "") {
  if (clocks?.second_word && clocks?.rate_unit) return clocks;
  const firstWord = String(clocks?.first_word || unitInText(unit) || "hours");
  const second = cleanUnit(clocks?.second_word || secondUnit) || LEGACY_UNIT;
  const firstOne = singularUnit(firstWord) || firstWord;
  return {
    ...(clocks || {}), first_word: firstWord, first_one: firstOne, second_word: second,
    second_one: singularUnit(second) || second, rate_unit: `${second} per ${firstOne}`,
  };
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

// The rate box's label: "Landings per hour".
export const rateLabel = (words) => cap(clockWords(words).rate_unit);

// A rate from what was typed: "0.125", "1/8" (1 every 8 hours), or "every 8" —
// or an error in words, in the model's units. { rate } | { error }.
export function parseRate(text, words = null) {
  const w = clockWords(words);
  const example = `0.125 (1 ${w.second_one} every 8 ${w.first_word})`;
  const t = String(text ?? "").trim().toLowerCase();
  if (!t) return { error: `Enter ${w.rate_unit}, e.g. ${example}.` };
  const every = t.match(/^(?:1\s*\/|every)\s*([0-9]*\.?[0-9]+)$/);
  if (every) {
    const h = Number(every[1]);
    return h > 0 ? { rate: 1 / h } : { error: `${cap(w.first_word)} between ${w.second_word} must be above 0.` };
  }
  const v = Number(t);
  if (!Number.isFinite(v)) {
    return { error: `Enter ${w.rate_unit} as a number, e.g. 0.125, or 1/8 for 1 ${w.second_one} every 8 ${w.first_word}.` };
  }
  if (v < 0) return { error: `${cap(w.rate_unit)} can't be negative.` };
  return { rate: v };
}

// The rate box's hint: "0.125 is 1 landing every 8 hours; 1/8 works too."
export const rateHint = (words) => {
  const w = clockWords(words);
  return `0.125 is 1 ${w.second_one} every 8 ${w.first_word}; 1/8 works too.`;
};

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

// A number with its unit, singular for exactly 1: "1 hour", "18.4 hours".
const counted = (value, many, one) => {
  const text = formatNumber(value);
  return `${text} ${text === "1" ? one : many}`;
};

// The k reading: "One landing wears it as much as 18.4 hours (90% range 14.8–22.8)."
export function kWords(result) {
  const k = (result?.params || []).find((p) => p.name === "k");
  if (!k) return "";
  const w = clockWords(result.clocks, result.unit, result.second_unit);
  const range = k.ci?.[0] != null && k.ci?.[1] != null
    ? ` (90% range ${formatNumber(k.ci[0])}–${formatNumber(k.ci[1])})` : "";
  return `One ${w.second_one} wears it as much as ${counted(k.value, w.first_word, w.first_one)}${range}.`;
}

// Whether the second clock matters, in words: "Landings clearly matter: …".
export function kTestWords(result, pText) {
  const w = clockWords(result?.clocks, result?.unit, result?.second_unit);
  const test = result?.k_test || {};
  return test.matters
    ? `${cap(w.second_word)} clearly matter: the test that they don't gives p ${pText(test.p_value)}.`
    : `The data can't tell ${w.second_word} from no effect (p ${pText(test.p_value)}): ${w.first_word} alone may do.`;
}
