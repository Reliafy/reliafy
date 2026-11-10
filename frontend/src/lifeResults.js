// Plain-words helpers for a fitted non-repairable model's results (#288, #292, #293):
// the distribution comparison and its verdicts, the best-fit sentence, a
// confidence bound in words, and the time at a reliability read off a curve.
// Pure functions, so `node --test` covers them.

import { formatNumber, formatPercent, singularUnit } from "./format.js";
import { unitInText } from "./components/unitText.js";

// ΔAIC below 2: the data can't tell the two apart (Burnham and Anderson).
export const ABOUT_AS_GOOD = 2;
// Above 10: essentially no support beside the best.
export const CLEARLY_WORSE = 10;

const VERDICTS = {
  best: "Best",
  about: "About as good",
  worse: "Worse",
  clearly: "Clearly worse",
};

// What a less familiar distribution is, beside its name in the sentence.
const GLOSS = {
  rayleigh: "a Weibull with β = 2",
  exponential: "a constant failure rate",
  gumbel: "the smallest-extreme-value distribution",
  gumbel_lev: "the largest-extreme-value distribution",
  expo_weibull: "a Weibull with a second shape parameter",
};

const LABELS = { aic: "AIC", aic_c: "AICc", bic: "BIC", neg_ll: "−log L" };
export const criterionLabel = (key) => LABELS[key] || "AIC";

// Best fit's candidates as table rows, lowest criterion first:
// { id, name, value, delta, verdict, verdictLabel, current }. ``currentId``
// marks the distribution on screen. Candidates without a finite value for
// the criterion are left out.
export function compareRows(candidates, criterion = "aic", currentId = null) {
  const rows = (candidates || [])
    .filter((c) => Number.isFinite(Number(c?.[criterion])))
    .map((c) => ({ id: c.id, name: c.name, value: Number(c[criterion]), k: c.k ?? null }))
    .sort((a, b) => a.value - b.value);
  if (!rows.length) return [];
  const best = rows[0].value;
  return rows.map((r, i) => {
    const delta = r.value - best;
    const verdict = i === 0 ? "best" : delta < ABOUT_AS_GOOD ? "about" : delta <= CLEARLY_WORSE ? "worse" : "clearly";
    return { ...r, delta, verdict, verdictLabel: VERDICTS[verdict], current: r.id === currentId };
  });
}

// "A, B and C"
function listNames(names) {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

// The comparison in one sentence: "Rayleigh (a Weibull with β = 2) fits best;
// Weibull, Gamma and Lognormal are about as good; the other 7 are worse."
// The worse ones are named when there are one or two, counted otherwise, and
// called "clearly worse" when every one of them is.
export function bestFitSentence(rows) {
  if (!rows?.length) return "";
  const [best, ...rest] = rows;
  const gloss = GLOSS[best.id] ? ` (${GLOSS[best.id]})` : "";
  let s = `${best.name}${gloss} fits best`;
  if (!rest.length) return `${s}.`;
  const about = rest.filter((r) => r.verdict === "about");
  const worse = rest.filter((r) => r.verdict !== "about");
  if (about.length) s += `; ${listNames(about.map((r) => r.name))} ${about.length === 1 ? "is" : "are"} about as good`;
  if (worse.length) {
    const how = worse.every((r) => r.verdict === "clearly") ? "clearly worse" : "worse";
    if (worse.length <= 2) {
      s += `; ${listNames(worse.map((r) => r.name))} ${worse.length === 1 ? "is" : "are"} ${how}`;
    } else {
      s += `; the other ${worse.length} are ${how}`;
    }
  }
  return `${s}.`;
}

// A confidence bound in words: "we're 90% sure it's at least 38%". ``fmt``
// formats the values; ``noun`` names the quantity ("it" by default).
export function boundWords(level, bound, lower, upper, fmt = String, noun = "it") {
  const lv = `${Number(level).toLocaleString("en-US", { maximumFractionDigits: 2 })}%`;
  if (bound === "two-sided" && lower != null && upper != null)
    return `we're ${lv} sure ${noun}'s between ${fmt(lower)} and ${fmt(upper)}`;
  if (bound === "lower" && lower != null) return `we're ${lv} sure ${noun}'s at least ${fmt(lower)}`;
  if (bound === "upper" && upper != null) return `we're ${lv} sure ${noun}'s at most ${fmt(upper)}`;
  return "";
}

// The time at which a falling curve ``y`` (over ``x``) first reaches
// ``target``, by linear interpolation; null when it never does on the grid.
export function timeAtValue(x, y, target) {
  if (!x || !y) return null;
  for (let i = 1; i < x.length; i++) {
    const a = y[i - 1];
    const b = y[i];
    if (a == null || b == null) continue;
    if (a >= target && b <= target) {
      const f = a === b ? 0 : (a - target) / (a - b);
      return x[i - 1] + f * (x[i] - x[i - 1]);
    }
  }
  return null;
}

// ---- The Calculator's answer sentence ----
// Pure wording and input checks, so the sentence never rounds the answer away
// and every refused value gets a message.

const MAX_PERCENT_DECIMALS = 8;
const trimZeros = (s) => (s.includes(".") ? s.replace(/\.?0+$/, "") : s);

// A probability as a percentage that keeps the answer near both ends:
// 0.9982 → "99.82%" (not "100%"), 0.00177 → "0.177%", 0.5714 → "57.1%".
// Only exactly 0 and 1 read "0%" and "100%". Near 100% the decimals are
// chosen so the distance from 100% shows two significant figures, the same
// information "0.18%" carries at the other end.
export function precisePercent(fraction) {
  if (fraction == null || fraction === "") return "—";
  const f = Number(fraction);
  if (!Number.isFinite(f)) return "—";
  const p = f * 100;
  if (p === 0) return "0%";
  if (p === 100) return "100%";
  // Outside 0–100 (a model that isn't a proper probability): as it comes.
  if (p < 0 || p > 100) return formatPercent(f, { sig: 3 });
  if (p < 10) return `${formatNumber(p, { sig: 3 })}%`;
  const gap = 100 - p;
  const decimals = gap >= 10 ? 1 : Math.min(MAX_PERCENT_DECIMALS, Math.max(1, 1 - Math.floor(Math.log10(gap))));
  const shown = p.toFixed(decimals);
  // Closer to 100% than the decimals can show: say so rather than print 100%.
  if (Number(shown) >= 100) return `>${(100 - 10 ** -MAX_PERCENT_DECIMALS).toFixed(MAX_PERCENT_DECIMALS)}%`;
  return `${trimZeros(shown)}%`;
}

// A time in a sentence: (1, "Months") → "1 month"; (1000, "Hours") → "1,000
// hours"; (0.5, "months") → "0.5 months". The number is shown as typed (up to
// six decimals), never rounded to three figures: it is the user's own input.
export function timeInWords(value, unit) {
  const n = Number(value);
  if (value == null || value === "" || !Number.isFinite(n)) return "—";
  const s = n.toLocaleString("en-US", { maximumFractionDigits: 6 });
  const u = unitInText(unit);
  return u ? `${s} ${s === "1" ? singularUnit(u) : u}` : s;
}

// The unit of a rate: "Months" → "per month". "" when there is no unit.
export function perUnit(unit) {
  const u = unitInText(unit);
  return u ? `per ${singularUnit(u)}` : "";
}

// A typed time, checked as typed. { ok, value, message }: a blank optional
// box is ok with value 0; anything refused says what to type instead.
export function checkTime(text, { optional = false, example = null } = {}) {
  const raw = String(text ?? "").trim().replace(/,/g, "");
  const eg = example != null && Number.isFinite(Number(example)) && Number(example) > 0
    ? `, e.g. ${Number(example).toLocaleString("en-US", { maximumFractionDigits: 6 })}` : "";
  if (raw === "") {
    return optional ? { ok: true, value: 0, message: null }
      : { ok: false, value: null, message: `Enter a time${eg}.` };
  }
  const v = Number(raw);
  if (!Number.isFinite(v)) return { ok: false, value: null, message: `Enter a number${eg}.` };
  if (v < 0) {
    return { ok: false, value: null,
             message: optional ? "Time can't be negative. Enter 0 or more, or leave this empty."
               : "Time can't be negative. Enter 0 or more." };
  }
  return { ok: true, value: v, message: null };
}

// Which way "good" runs for each function: reliability (and density, which
// has no cautious side) keep the side as chosen; failure probability, hazard
// and cumulative hazard rise as reliability falls.
const FALLS_WITH_RELIABILITY = new Set(["ff", "hf", "Hf"]);

// The bound side after the function changes. A lower bound on reliability
// and an upper bound on the probability of failure are the same statement,
// so a one-sided bound flips when the function's direction does; two-sided
// and none stay as they are.
export function boundSideFor(fromFn, toFn, bound) {
  if (bound !== "lower" && bound !== "upper") return bound;
  if (FALLS_WITH_RELIABILITY.has(fromFn) === FALLS_WITH_RELIABILITY.has(toFn)) return bound;
  return bound === "lower" ? "upper" : "lower";
}

// Where a chart has to end to show ``reach``: the next 1-2-5 value at least
// a tenth past it (100 → 200, 76 → 100, 470 → 1,000). A coarse ladder, so
// typing a few times past the end asks for a few ranges, not one each.
export function stretchTo(reach) {
  const r = Number(reach);
  if (!Number.isFinite(r) || r <= 0) return null;
  const want = r * 1.1;
  const decade = 10 ** Math.floor(Math.log10(want));
  for (const m of [1, 2, 5, 10]) {
    if (m * decade >= want) return Number((m * decade).toPrecision(12));
  }
  return 10 * decade;
}
