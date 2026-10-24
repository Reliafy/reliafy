// The model pages' shared frame: which tabs each kind of model shows, the
// answer line under its name, and the plain words of its Effects and
// Diagnostics tabs. Pure functions, so `node --test` covers them; the
// components (components/model/) only lay them out.
//
// Every model page has the same frame: the header (breadcrumb, name, answer
// line, actions), one row of tabs and the tab's body filling the height left.
// The same tab name means the same thing on every kind of model, and a tab
// that doesn't apply is left out, never greyed.
import { formatNumber, formatPercent } from "./format.js";
import { hasMeanLife, meanLifeAnswer } from "./meanLife.js";
import { unitInText } from "./components/unitText.js";

export const TAB_LABELS = {
  plot: "Probability plot",
  survival: "Survival curve",
  chance: "Chance by count",
  effects: "Effects",
  risk: "Risk now",
  calc: "Calculator",
  chars: "Model characteristics",
  diag: "Diagnostics",
  data: "Data",
};

// Tab ids from before the frame (and the old names in links), mapped to the
// tab that now holds that content: "Fit quality" and "Validation" are in
// Diagnostics, "Coefficients" in Effects.
const TAB_ALIASES = {
  gof: "diag", fit: "diag", check: "diag", validation: "diag", diagnostics: "diag",
  coef: "effects", coefficients: "effects",
  characteristics: "chars", calculator: "calc", probability: "plot",
};

const MAX_TABS = 6;
const tab = (id) => ({ id, label: TAB_LABELS[id] });

const isRegression = (r) => r?.kind === "regression";

// Whether a regression-style model can give B-lives (read off its curve at
// the calculator's covariates, or from its life path).
const regressionChars = (r) => !!(r.functions?.curves || r.functions?.life_path);

// The tabs of a model's page, in order: [{ id, label }]. Empty for a model
// with one view (per demand); null for a kind the frame doesn't draw yet.
export function modelTabs(result) {
  const r = result || {};
  const fns = !!r.functions;
  let ids;
  switch (r.kind) {
    case "per_demand":
      return [];
    case "competing_risks":
      return null;
    case "joint":
      ids = ["risk", "calc", "effects", "diag", "data"];
      break;
    case "regression":
      ids = ["effects", fns && "calc", fns && regressionChars(r) && "chars", "diag", "data"];
      break;
    case "nonparametric":
      ids = ["survival", fns && "calc", hasMeanLife(r) && "chars", "data"];
      break;
    case "flexible":
      ids = ["survival", fns && "calc", (hasMeanLife(r) || r.life) && "chars", "diag", "data"];
      break;
    case "discrete":
      ids = [(r.counts || fns) && "chance", fns && "calc", (r.functions?.life_path || r.metrics) && "chars",
             "diag", "data"];
      break;
    default: {
      // A fitted distribution (or mixture); one made from parameters has no
      // data, so no plot and nothing to check it against.
      const data = !!r.plot && !r.params_only;
      ids = [data && "plot", fns && "calc", (hasMeanLife(r) || !!r.life) && "chars", data && "diag", "data"];
    }
  }
  return ids.filter(Boolean).slice(0, MAX_TABS).map(tab);
}

// The tab to open: the one asked for (by id, an old id, or its name in a
// link) when the page has it, else the first.
export function resolveTab(tabs, wanted) {
  if (!tabs?.length) return null;
  const w = String(wanted || "").trim().toLowerCase();
  if (w) {
    const id = TAB_ALIASES[w] || w;
    const hit = tabs.find((t) => t.id === id || t.label.toLowerCase() === w);
    if (hit) return hit.id;
  }
  return tabs[0].id;
}

// Move between tabs with the keyboard (the ARIA tab pattern): the arrow keys
// wrap round, Home and End go to the ends. Null for any other key.
export function nextTabIndex(key, index, count) {
  if (!count) return null;
  if (key === "ArrowRight" || key === "ArrowDown") return (index + 1) % count;
  if (key === "ArrowLeft" || key === "ArrowUp") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

// ---- The answer line -------------------------------------------------------

const withUnit = (v, unit) => `${formatNumber(v)}${unit ? ` ${unitInText(unit)}` : ""}`;
const range = (lo, hi) => `${formatNumber(lo)}–${formatNumber(hi)}`;

// "30 failed", "18 failed, 7 running".
export function dataWords(result, split = null) {
  const s = split || result?.split;
  if (s && Number.isFinite(s.failed)) {
    const parts = [`${s.failed.toLocaleString("en-US")} failed`];
    if (s.running) parts.push(`${s.running.toLocaleString("en-US")} running`);
    if (s.other) parts.push(`${s.other.toLocaleString("en-US")} other censored`);
    return parts.join(", ");
  }
  if (result?.n != null) return `${Number(result.n).toLocaleString("en-US")} observations`;
  return null;
}

const PATTERNS = {
  wear_out: "Wear-out",
  infant_mortality: "Early-life failures",
};

// The usual B-life of a fit, with its stored lower bound: "B10 582 hours (≥ 467 at 90%)".
function bLifeWords(result, label = "B10") {
  const life = result?.life;
  const b = (life?.b_lives || []).find((x) => x.label === label);
  if (!b || !Number.isFinite(Number(b.value))) return null;
  const bound = b.lower != null && Number.isFinite(Number(b.lower)) && life.confidence
    ? ` (≥ ${formatNumber(b.lower)} at ${Math.round(life.confidence * 100)}%)` : "";
  return `${label} ${withUnit(b.value, result.unit)}${bound}`;
}

function meanWords(result) {
  if (!hasMeanLife(result) && result?.kind !== "discrete") return null;
  const mttf = result.life?.mttf || (result.metrics?.mttf != null ? { value: result.metrics.mttf } : null);
  const answer = meanLifeAnswer(result, mttf);
  if (answer.kind !== "mean") return null;
  return `mean ${withUnit(answer.value, result.unit)}`;
}

// A Weibull shape keeps three figures ("2.50", not "2.5"): the verdict turns
// on which side of 1 it falls.
const SHAPE = new Intl.NumberFormat("en-US", { minimumSignificantDigits: 3, maximumSignificantDigits: 3 });
const shape3 = (v) => (Math.abs(v) >= 0.001 && Math.abs(v) < 1e7 ? SHAPE.format(v) : formatNumber(v));

function shapeWords(result) {
  const beta = (result.params || []).find((p) => p.name === "beta");
  if (String(result.distribution_id) !== "weibull" || !beta) return null;
  const ci = beta.ci ? ` (95% ${shape3(beta.ci[0])}–${shape3(beta.ci[1])})` : "";
  return `β ${shape3(beta.value)}${ci}`;
}

// The covariate with the largest effect, in a few words: "temp_C: ×1.15 per °C".
function strongestEffect(result) {
  const rows = forestRows(result).filter((r) => r.ratio != null);
  if (!rows.length) return null;
  const top = rows.reduce((a, b) => (Math.abs(Math.log(b.ratio)) > Math.abs(Math.log(a.ratio)) ? b : a));
  const per = top.unit ? ` per ${top.unit}` : "";
  const ci = top.lo != null && top.hi != null ? ` (${range(top.lo, top.hi)})` : "";
  return `${top.name}: ${result.ratio_label || "ratio"} ${formatNumber(top.ratio)}${per}${ci}`;
}

// The three or four numbers that answer "what does this model say?", as
// short phrases for the line under the model's name. ``saved`` (a phrase,
// e.g. "saved 3 min ago") ends it.
export function answerParts(result, { split = null, saved = null } = {}) {
  const r = result || {};
  const parts = [];
  const add = (p) => p && parts.push(p);
  switch (r.kind) {
    case "per_demand": {
      const d = r.per_demand || {};
      add(d.p != null && `failure probability ${formatPercent(d.p, { sig: 3 })} per demand`
        + (d.ci ? ` (${formatPercent(d.ci[0], { sig: 2 })}–${formatPercent(d.ci[1], { sig: 2 })})` : ""));
      // Near 100%, four figures: "99.25%", not "99%".
      add(d.reliability != null && `reliability ${formatNumber(d.reliability * 100, { sig: 4 })}%`);
      add(d.demands != null && `${d.failures} failed in ${Number(d.demands).toLocaleString("en-US")} demands`);
      break;
    }
    case "joint": {
      add(r.n_items != null && `${r.n_items} units (${r.n_events} failed, ${r.n_running} running)`);
      add(r.n_readings != null && `${Number(r.n_readings).toLocaleString("en-US")} readings of ${r.marker || "the reading"}`);
      const top = (r.risk || [])[0];
      const mid = r.horizons?.labels?.[1];
      if (top && mid) add(`highest risk: unit ${top.id}, ${formatPercent(top.risk?.[1])} in the next ${mid}`);
      add(r.fit_ok === false && "fit not verified");
      break;
    }
    case "regression": {
      add(r.tvc ? `${r.distribution}, covariates changing over time` : r.distribution);
      add(strongestEffect(r));
      const c = r.validation?.available ? r.validation.concordance : null;
      add(c && `ranking ${formatNumber(c.value, { sig: 2 })} (Harrell's C)`);
      add(r.tvc ? `${r.tvc.items ?? "?"} items, ${r.tvc.failures ?? "?"} failures` : dataWords(r, split));
      break;
    }
    default: {
      // A distribution, mixture, flexible spline, discrete fit or estimate.
      const pattern = PATTERNS[r.randomness?.verdict];
      if (r.mixture > 1) add(`${r.mixture} sub-populations`);
      else if (r.kind === "nonparametric") add(r.distribution);
      else if (r.kind === "flexible") add(`flexible spline, ${r.spline?.n_terms ?? 3} terms`);
      else add(pattern || r.distribution);
      add(shapeWords(r));
      add(bLifeWords(r) || (r.metrics?.b10 != null && `B10 ${withUnit(r.metrics.b10, r.unit)}`));
      add(meanWords(r));
      add(r.params_only ? "made from parameters" : dataWords(r, split));
    }
  }
  add(saved);
  return parts.filter(Boolean);
}

// ---- Effects ---------------------------------------------------------------

const RATIO_VERB = {
  "hazard ratio": "the failure rate",
  "time ratio": "the life",
  "odds ratio": "the odds of failing",
};

// "C(site)[T.B]" → "site B (against the first site)"; anything else as given.
function termName(name) {
  const m = /^(?:C\()?([^()[\]]+)\)?\[T\.([^\]]+)\]$/.exec(String(name));
  return m ? { label: `${m[1]} = ${m[2]}`, categorical: true, base: m[1] } : { label: String(name) };
}

// Every covariate's effect as a ratio with its 95% interval: [{ name,
// ratio, lo, hi, unit, p }]; for an additive model (no ratio) the
// coefficient itself, with ``additive``.
export function forestRows(result) {
  const r = result || {};
  if (r.kind === "joint") {
    return (r.hazard_ratios || []).map((h) => ({
      name: h.kind === "marker" ? r.marker || h.name : h.name, ratio: h.hr, lo: h.lower, hi: h.upper,
      unit: h.kind === "marker" ? r.marker_unit || "" : "", text: h.text,
    }));
  }
  const table = Object.fromEntries((r.coef_table || []).filter((t) => t.part === "coefficients").map((t) => [t.name, t]));
  return (r.coefficients || []).map((c) => {
    const ci = c.ci || table[c.name]?.ci || null;
    const p = table[c.name]?.p ?? null;
    const unit = c.covariate_unit || r.covariate_units?.[c.name] || "";
    if (!r.ratio_label) {
      return { name: c.name, value: c.value, lo: ci?.[0] ?? null, hi: ci?.[1] ?? null, unit, p, additive: true };
    }
    const exp = (v) => (v == null ? null : Math.exp(v));
    return { name: c.name, ratio: c.ratio ?? exp(c.value), lo: exp(ci?.[0]), hi: exp(ci?.[1]), unit, p };
  });
}

// One effect in words: "Each +1 °C in temp_C multiplies the failure rate by
// 1.15 (95% 1.10 to 1.20)." For a small effect per unit it also gives a step
// of 10 ("+10: ×4.0"), so it reads at a size people think in.
export function effectText(row, ratioLabel = "hazard ratio") {
  if (row.text) return row.text;
  const name = termName(row.name);
  const unit = row.unit ? ` ${row.unit}` : "";
  const subject = name.categorical ? `${name.label}` : `Each +1${unit} in ${name.label}`;
  if (row.additive) {
    const ci = row.lo != null ? ` (95% ${formatNumber(row.lo)} to ${formatNumber(row.hi)})` : "";
    return `${subject} adds ${formatNumber(row.value)} to the failure rate${ci}.`;
  }
  const verb = RATIO_VERB[ratioLabel] || "the rate";
  const r = row.ratio;
  let text = name.categorical
    ? `${subject} (against the base level) multiplies ${verb} by ${formatNumber(r)}`
    : `${subject} multiplies ${verb} by ${formatNumber(r)}`;
  if (row.lo != null && row.hi != null) {
    text += ` (95% ${formatNumber(row.lo)} to ${formatNumber(row.hi)})`;
  }
  if (!name.categorical && r > 0.95 && r < 1.05 && r !== 1) {
    text += `; +10${unit} multiplies it by ${formatNumber(r ** 10)}`;
  }
  if (row.lo != null && row.hi != null && row.lo <= 1 && row.hi >= 1) {
    text += ". The interval includes 1, so the data can't rule out no effect";
  }
  return `${text}.`;
}

// ---- Diagnostics -----------------------------------------------------------

// The verdict chips: tone, its word and an icon, so colour is never the only
// signal.
export const VERDICT = {
  good: { label: "OK", icon: "✓" },
  caveat: { label: "Check", icon: "!" },
  bad: { label: "Problem", icon: "✕" },
};

// The P-P plot's reading: the largest gap between the data's fraction failed
// and the model's, in percentage points, and where. A check to look at, not a
// test: no verdict, just the words.
export function ppSummary(empirical, unit = "") {
  const e = empirical;
  if (!e?.x?.length) return null;
  let gap = -1;
  let at = 0;
  e.x.forEach((x, i) => {
    const g = Math.abs(e.F[i] - e.model_F[i]);
    if (g > gap) { gap = g; at = i; }
  });
  const pts = gap * 100;
  const when = withUnit(e.x[at], unit);
  const side = e.F[at] > e.model_F[at] ? "more" : "fewer";
  return {
    gap,
    words: pts < 0.5
      ? "The points sit on the diagonal: the model puts the failures where they happened."
      : `The largest gap is ${formatNumber(pts, { sig: 2 })} percentage points, at ${when}: ${side} had failed by then than the model says.`,
  };
}

// The fitted curve against the data's own estimate: the same largest gap,
// read as reliability.
export function curveSummary(empirical, unit = "") {
  const s = ppSummary(empirical, unit);
  if (!s) return null;
  return {
    ...s,
    words: s.gap * 100 < 0.5
      ? "The fitted curve runs through the data's own steps."
      : `The fitted curve stays within ${formatNumber(Math.ceil(s.gap * 1000) / 10, { sig: 2 })} percentage points of the data's own estimate.`,
  };
}

// A discrete fit's counts: the largest difference between the failures seen
// at a count and the failures the model expects there.
export function countsSummary(counts, unit = "") {
  const c = counts;
  if (!c?.k?.length) return null;
  let worst = null;
  c.k.forEach((k, i) => {
    const d = Math.abs((c.failed[i] ?? 0) - (c.expected[i] ?? 0));
    if (c.expected[i] != null && (!worst || d > worst.d)) worst = { k, d, i };
  });
  if (!worst) return null;
  const u = unit ? ` ${unitInText(unit)}` : "";
  return {
    words: `The biggest difference is at ${worst.k}${u}: ${formatNumber(c.failed[worst.i])} failed where the model `
      + `expects ${formatNumber(c.expected[worst.i], { sig: 2 })}.`,
  };
}

// The shape of a fitted hazard rate in words: rising, falling, a bathtub
// (falls then rises), a hump, or about level.
export function hazardShape(x, h) {
  const pts = (x || []).map((v, i) => [v, h?.[i]]).filter(([, y]) => y != null && Number.isFinite(y) && y > 0);
  if (pts.length < 5) return null;
  const ys = pts.slice(Math.floor(pts.length * 0.05)).map(([, y]) => y);
  const first = ys[0];
  const last = ys[ys.length - 1];
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  if (hi / lo < 1.2) return { shape: "level", words: "About level: failures come at a steady rate, whatever the age." };
  const iLo = ys.indexOf(lo);
  const iHi = ys.indexOf(hi);
  if (iLo > 0 && iLo < ys.length - 1 && first > lo * 1.2 && last > lo * 1.2)
    return { shape: "bathtub", words: "Falls then rises (a bathtub): early failures, a steady stretch, then wear-out." };
  if (iHi > 0 && iHi < ys.length - 1 && first < hi / 1.2 && last < hi / 1.2)
    return { shape: "hump", words: "Rises then falls: the risk peaks at middle age. Check there's data at both ends." };
  return last > first
    ? { shape: "rising", words: "Rising: the older a unit, the likelier it is to fail next (wear-out)." }
    : { shape: "falling", words: "Falling: units that survive early on fail less often later (early-life failures)." };
}

// How many units' deviance residuals are beyond ±2.5 (poorly predicted).
export function oddUnits(deviance, limit = 2.5) {
  const ys = deviance?.y || [];
  const odd = ys.filter((v) => Math.abs(v) > limit).length;
  return {
    odd,
    tone: odd === 0 ? "good" : odd / Math.max(ys.length, 1) > 0.05 ? "caveat" : "neutral",
    words: odd === 0
      ? `No unit is beyond ±${limit}: the model predicts every unit reasonably well.`
      : `${odd} unit${odd === 1 ? " is" : "s are"} beyond ±${limit}: worth checking in the data.`,
  };
}

// A discrete model's chance of failing at each whole count, read off its
// failure-probability curve (a step function on a fine grid): for a model
// saved before its fit carried the counts. [{ k, p }].
export function pmfFromCurves(curves) {
  const x = curves?.x || [];
  const F = curves?.ff || [];
  const at = new Map();
  x.forEach((v, i) => {
    const k = Math.floor(v + 1e-9);
    if (k >= 1 && !at.has(k) && F[i] != null) at.set(k, F[i]);
  });
  const out = [];
  let prev = 0;
  for (let k = 1; at.has(k); k++) {
    out.push({ k, p: Math.max(0, at.get(k) - prev) });
    prev = at.get(k);
  }
  return out;
}
