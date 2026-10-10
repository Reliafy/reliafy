// Plain-words helpers for a fitted life model's results (#288, #292, #293):
// the distribution comparison and its verdicts, the best-fit sentence, a
// confidence bound in words, and the time at a reliability read off a curve.
// Pure functions, so `node --test` covers them.

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

const LABELS = { aic: "AIC", aic_c: "AICc", bic: "BIC" };
export const criterionLabel = (key) => LABELS[key] || "AIC";

// Best fit's candidates as table rows, lowest criterion first:
// { id, name, value, delta, verdict, verdictLabel, current }. ``currentId``
// marks the distribution on screen. Candidates without a finite value for
// the criterion are left out.
export function compareRows(candidates, criterion = "aic", currentId = null) {
  const rows = (candidates || [])
    .filter((c) => Number.isFinite(Number(c?.[criterion])))
    .map((c) => ({ id: c.id, name: c.name, value: Number(c[criterion]) }))
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
