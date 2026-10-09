import ResultSummary from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";

// The answer first for a fitted life distribution (#311): one plain verdict
// with its numbers in bold, then up to four tiles — the parameters by their
// plain names, the data split, the distribution — before the tabs.

// Plain names for SurPyval's parameters. ``time``: the value is in the
// model's time unit; ``rate``: per unit time.
const PARAMS = {
  weibull: { alpha: ["Scale α", "time"], beta: ["Shape β"] },
  exponential: { failure_rate: ["Failure rate λ", "rate"] },
  normal: { mu: ["Mean μ", "time"], sigma: ["Std dev σ", "time"] },
  lognormal: { mu: ["Log-mean μ"], sigma: ["Log-std σ"] },
  gamma: { alpha: ["Shape α"], beta: ["Rate β", "rate"] },
  loglogistic: { alpha: ["Scale α", "time"], beta: ["Shape β"] },
  expo_weibull: { alpha: ["Scale α", "time"], beta: ["Shape β"], mu: ["Exponent μ"] },
  gumbel: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  gumbel_lev: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  logistic: { mu: ["Location μ", "time"], sigma: ["Scale σ", "time"] },
  rayleigh: { sigma: ["Scale σ", "time"] },
};

// "Hours" → "hour" for "per hour"; any other unit as written.
function singular(unit) {
  const u = unitInText(unit);
  return /^(seconds|minutes|hours|days|weeks|months|years|cycles|kilometres|miles|operations|rounds)$/.test(u)
    ? u.slice(0, -1)
    : u;
}

function distId(result) {
  if (result.distribution_id && result.distribution_id !== "best") return result.distribution_id;
  const name = String(result.distribution || "").toLowerCase();
  return Object.keys(PARAMS).find((k) => name === k || name.replace(/[^a-z]/g, "") === k) || null;
}

// A parameter with its plain label (unit included) and formatted value.
export function paramView(result, p) {
  const spec = PARAMS[distId(result)]?.[p.name];
  const unit = result.unit ? unitInText(result.unit) : "";
  const label = spec ? spec[0] : p.name;
  const kind = spec?.[1];
  const suffix = kind === "time" && unit ? ` (${unit})` : kind === "rate" && unit ? ` (per ${singular(result.unit)})` : "";
  return {
    label: label + suffix,
    value: formatNumber(p.value),
    ci: p.ci ? `${formatNumber(p.ci[0])}–${formatNumber(p.ci[1])}` : null,
  };
}

// The time by which a fraction ``q`` of units have failed, read off the fitted
// reliability curve (null when the curve doesn't reach it).
function lifeAt(result, q) {
  const c = result.functions?.curves;
  if (!c?.x || !c?.sf) return null;
  const target = 1 - q;
  for (let i = 1; i < c.x.length; i++) {
    const a = c.sf[i - 1], b = c.sf[i];
    if (a == null || b == null) continue;
    if (a >= target && b <= target) {
      const f = a === b ? 0 : (a - target) / (a - b);
      return c.x[i - 1] + f * (c.x[i] - c.x[i - 1]);
    }
  }
  return null;
}

// A Weibull shape and its interval keep three figures ("1.00", not "1"): the
// verdict turns on which side of 1 they fall.
const shapeFmt = new Intl.NumberFormat("en-US", { minimumSignificantDigits: 3, maximumSignificantDigits: 3 });
const fmtShape = (v) => (Math.abs(v) >= 0.001 && Math.abs(v) < 1e7 ? shapeFmt.format(v) : formatNumber(v));

const HOW_CI = "95% intervals. A positive parameter's interval is taken on the log scale, so it stays above zero.";

// The one sentence: the failure pattern when the shape says one (Weibull,
// exponential), otherwise the median life.
function sentence(result) {
  const id = distId(result);
  const unit = result.unit ? ` ${unitInText(result.unit)}` : "";
  const byName = Object.fromEntries((result.params || []).map((p) => [p.name, p]));
  const r = result.randomness;
  if (id === "weibull" && byName.alpha && byName.beta) {
    const beta = byName.beta.value;
    const ci = byName.beta.ci;
    const ciText = ci ? ` (95% ${fmtShape(ci[0])}–${fmtShape(ci[1])})` : "";
    const scale = (
      <>scale α = <b>{formatNumber(byName.alpha.value)}{unit}</b>, the age by which 63% have failed.</>
    );
    const shape = <>shape β = <b>{fmtShape(beta)}</b>{ciText}</>;
    const verdict = r?.verdict;
    if (verdict === "wear_out") return <><b>Wear-out</b> — {shape}; {scale}</>;
    if (verdict === "infant_mortality") return <><b>Early-life failures</b> — {shape}; {scale}</>;
    if (verdict === "random" && ci) {
      // The interval includes 1: say so, whichever side the estimate is on.
      const lead = Math.abs(beta - 1) < 0.1 ? "Consistent with random failures"
        : beta > 1 ? "Borderline wear-out" : "Borderline early-life failures";
      return (
        <>
          <b>{lead}</b> — {shape} includes 1, so a constant failure rate fits too; {scale}
        </>
      );
    }
    return <><b>Weibull fit</b> — {shape}; {scale}</>;
  }
  if (id === "exponential" && byName.failure_rate) {
    const rate = byName.failure_rate.value;
    return (
      <>
        <b>Random failures</b> — a constant failure rate λ = <b>{formatNumber(rate)}</b>
        {result.unit ? ` per ${singular(result.unit)}` : ""}; mean life <b>{formatNumber(1 / rate)}{unit}</b>.
      </>
    );
  }
  const median = lifeAt(result, 0.5);
  const name = String(result.distribution || "Model").replace(/\s*\(.*$/, "");
  if (median != null) {
    return <><b>{name}</b> — median life <b>{formatNumber(median)}{unit}</b>: half have failed by then.</>;
  }
  return <><b>{name}</b> fit.</>;
}

// ``split`` ({ failed, running, other }) when the caller can count the data;
// otherwise the tile shows the observation count.
export default function LifeSummary({ result, split = null }) {
  const id = distId(result);
  // Shape before scale (the verdict reads off the shape).
  const order = id === "weibull" || id === "loglogistic" || id === "expo_weibull" ? ["beta", "alpha", "mu"] : null;
  const params = [...(result.params || [])].sort((a, b) =>
    order ? order.indexOf(a.name) - order.indexOf(b.name) : 0
  );
  const tiles = params.slice(0, 2).map((p) => {
    const v = paramView(result, p);
    // The Weibull sentence already gives β's interval.
    const said = id === "weibull" && p.name === "beta";
    return {
      label: v.label,
      value: said ? fmtShape(p.value) : v.value,
      hint: v.ci && !said && (
        <span title={result.ci_note || HOW_CI}>
          95% {v.ci} <span className="help-q" aria-label={HOW_CI}>?</span>
        </span>
      ),
    };
  });
  if (split && split.failed + split.running + split.other === result.n) {
    tiles.push({
      label: "Data",
      value: split.running
        ? `${split.failed.toLocaleString()} failed, ${split.running.toLocaleString()} running`
        : `${split.failed.toLocaleString()} failures`,
      hint: split.other ? `${split.other.toLocaleString()} more censored` : null,
    });
  } else if (result.n != null) {
    tiles.push({ label: "Observations", value: result.n.toLocaleString() });
  }
  // A non-parametric or discrete fit has no scale to read: its mean life.
  if (!params.length || result.kind === "discrete") {
    const mttf = result.metrics?.mttf;
    if (mttf != null) {
      tiles.push({ label: `Mean life${result.unit ? ` (${unitInText(result.unit)})` : ""}`, value: formatNumber(mttf) });
    }
  }
  tiles.push({ label: "Distribution", value: String(result.distribution || "—").replace(/\s*\(.*$/, "") });
  // A fit the optimiser didn't settle is a caveat; the warning says why.
  const caveat = result.fit_warning && !result.no_finite_maximum;
  return (
    <ResultSummary tone={caveat ? "caveat" : "neutral"} sentence={sentence(result)} stats={tiles}>
      {caveat ? result.fit_warning : result.randomness?.reason}
    </ResultSummary>
  );
}
