import { formatNumber } from "../format.js";
import { unitInText } from "./unitText.js";

// The side panel beside a fitted life distribution's plot (#311): its
// parameters by their plain names with their intervals, the data, and a quiet
// one-line reading of what the fit says — the answer next to the chart, not
// stacked above the tabs.

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

// What the fit says, as a short title and one line: the failure pattern when
// the shape says one (Weibull, exponential), otherwise the median life.
function verdict(result) {
  const id = distId(result);
  const unit = result.unit ? ` ${unitInText(result.unit)}` : "";
  const byName = Object.fromEntries((result.params || []).map((p) => [p.name, p]));
  if (id === "weibull" && byName.beta) {
    const beta = byName.beta.value;
    const v = result.randomness?.verdict;
    if (v === "wear_out")
      return { title: "Wear-out", text: "β is above 1 at 95% confidence: the failure rate rises with age, so preventive replacement can pay off." };
    if (v === "infant_mortality")
      return { title: "Early-life failures", text: "β is below 1 at 95% confidence: the failure rate falls with age, so replacing early does harm." };
    if (v === "random" && byName.beta.ci) {
      const title = Math.abs(beta - 1) < 0.1 ? "Consistent with random failures"
        : beta > 1 ? "Borderline wear-out" : "Borderline early-life failures";
      return { title, text: "β's interval includes 1, so a constant failure rate fits these data too." };
    }
    return null;
  }
  if (id === "exponential" && byName.failure_rate) {
    return {
      title: "Random failures",
      text: <>A constant failure rate: mean life <b>{formatNumber(1 / byName.failure_rate.value)}{unit}</b>.</>,
    };
  }
  const median = lifeAt(result, 0.5);
  if (median != null) {
    return { title: "Median life", text: <><b>{formatNumber(median)}{unit}</b>: half have failed by then.</> };
  }
  return null;
}

// The data in words: failed and still running when the caller counted them,
// otherwise the observation count.
function dataText(result, split) {
  if (split && split.failed + split.running + split.other === result.n) {
    const parts = [`${split.failed.toLocaleString()} failed`];
    if (split.running) parts.push(`${split.running.toLocaleString()} running`);
    if (split.other) parts.push(`${split.other.toLocaleString()} other censored`);
    return parts.join(", ");
  }
  return result.n != null ? `${result.n.toLocaleString()} observations` : null;
}

// ``split`` ({ failed, running, other }) when the caller can count the data.
// ``children`` (the plot) goes on the left; the panel sits on the right.
export default function LifeAside({ result, split = null }) {
  const id = distId(result);
  // Shape before scale: the reading turns on the shape.
  const order = id === "weibull" || id === "loglogistic" || id === "expo_weibull" ? ["beta", "alpha", "mu"] : null;
  const params = [...(result.params || [])].sort((a, b) =>
    order ? order.indexOf(a.name) - order.indexOf(b.name) : 0
  );
  const data = dataText(result, split);
  const reading = verdict(result);
  const method = result.options?.how && result.options.how !== "MLE" ? result.options.how : "Maximum likelihood";
  const caveat = result.fit_warning && !result.no_finite_maximum;
  return (
    <div className="aside">
      <div className="gof-card">
        <div className="gofh">Parameters</div>
        {params.map((p) => {
          const v = paramView(result, p);
          return (
            <div className="gofr" key={p.name}>
              <span className="gk">{v.label}</span>
              <span className="gv-col">
                <span className="gv">{id === "weibull" && p.name === "beta" ? fmtShape(p.value) : v.value}</span>
                {v.ci && <span className="param-ci" title={result.ci_note || HOW_CI}>95% {v.ci}</span>}
              </span>
            </div>
          );
        })}
        {(result.extra_params || []).map((p) => (
          <div className="gofr" key={p.name}>
            <span className="gk">{p.name}</span>
            <span className="gv">{formatNumber(p.value)}</span>
          </div>
        ))}
        {data && (
          <div className="gofr">
            <span className="gk">Data</span>
            <span className="gv">{data}</span>
          </div>
        )}
      </div>
      {caveat && <div className="life-reading caveat">{result.fit_warning}</div>}
      {reading && (
        <div className="life-reading">
          <div className="life-reading-title">{reading.title}</div>
          <div>{reading.text}</div>
        </div>
      )}
      <p className="life-method">
        {method} fit. The line is the model, the points the data
        {result.plot?.bounds ? ", the band and intervals 95%" : ""}.
      </p>
    </div>
  );
}
