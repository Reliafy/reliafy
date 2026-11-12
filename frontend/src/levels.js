// The one level for every interval the app shows (backend/levels.py has the
// same rule): life quantities (B-lives, mean or median life, life left, the
// time to a limit) get a 90% one-sided lower bound; a chance of failing a 90%
// one-sided upper bound; everything else (parameters, ratios, plot bands,
// rates, forecast ranges, availability) a 90% two-sided interval. A page that
// lets the user pick another level keeps the choice; this is its default.

export const LEVEL = 0.9;
export const LEVEL_PCT = 90;
// SurPyval's alpha_ci for a 90% two-sided interval or a 90% one-sided bound.
export const ALPHA = 0.1;
export const LEVEL_TEXT = "90%";

// "90%" for 0.9 (or "95%", "99.5%" for a level stored or chosen).
export const levelPct = (level) => {
  const v = Number(level);
  return Number.isFinite(v) && v > 0 && v < 1 ? `${Math.round(v * 1000) / 10}%` : LEVEL_TEXT;
};

// A two-sided interval's label: "90% interval", "90% band", "90% range".
export const intervalWords = (noun = "interval", level = LEVEL) => `${levelPct(level)} ${noun}`;

// A forecast's likely range by its level: 0.9 → "90%". Forecasts made or
// shared before the rule said "P10–P90" (or 0.8): those read "80%".
export function rangeLevelText(level) {
  if (typeof level === "string") return /P10/.test(level) ? "80%" : level;
  return levelPct(level ?? LEVEL);
}

// The level a result's intervals were worked out at: its ``ci_level``; a
// result saved before the rule that the server couldn't move to 90% has none,
// and was at 95%.
export const ciLevelOf = (result, fallback = 0.95) => {
  const v = Number(result?.ci_level);
  return Number.isFinite(v) && v > 0 && v < 1 ? v : fallback;
};
export const ciPct = (result, fallback = 0.95) => levelPct(ciLevelOf(result, fallback));

// The side a one-sided bound goes on for each function, by the rule: a
// reliability (and a life read off it) gets the lower bound, a chance of
// failing and the cumulative hazard the upper one (the pessimistic side
// either way); the hazard rate and the density a two-sided interval.
// ``"time"`` is a time at a reliability.
const RULE_BOUND = { sf: "lower", time: "lower", ff: "upper", Hf: "upper" };
export const ruleBound = (fn) => RULE_BOUND[fn] || "two-sided";
// A calculator's bound setting: "auto" (the default) follows the rule for
// the function shown; anything else is the user's own choice.
export const AUTO_BOUND = "auto";
export const effectiveBound = (setting, fn) => (setting === AUTO_BOUND || !setting ? ruleBound(fn) : setting);
// The bound menu's choices, the first naming the side the rule picks.
export const boundOptions = (fn) => [
  { value: AUTO_BOUND, label: `Safe side (${ruleBound(fn)})` },
  { value: "none", label: "None" },
  { value: "two-sided", label: "Two-sided" },
  { value: "lower", label: "Lower" },
  { value: "upper", label: "Upper" },
];
