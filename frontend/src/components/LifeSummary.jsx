import { useEffect, useState } from "react";
import Modal from "./Modal.jsx";
import GoodnessOfFit from "./GoodnessOfFit.jsx";
import Select from "./Select.jsx";
import Chip from "./ui/Chip.jsx";
import { openGuide } from "./HelpButton.jsx";
import { lifeAt } from "../api.js";
import { formatNumber } from "../format.js";
import { bestFitSentence, boundWords, compareRows, criterionLabel, timeAtValue } from "../lifeResults.js";
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
function lifeFromCurve(result, q) {
  const c = result.functions?.curves;
  return timeAtValue(c?.x, c?.sf, 1 - q);
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
  // B50 from the fit when it carries its B-lives (#288); else off the curve.
  const median = result.life?.b_lives?.find((b) => b.label === "B50")?.value ?? lifeFromCurve(result, 0.5);
  if (median != null && id === "lognormal") {
    // μ and σ are on log time (#292): say what they mean in time.
    return {
      title: "Median life",
      text: <><b>{formatNumber(median)}{unit}</b> (e<sup>μ</sup>): half have failed by then. μ and σ are the
        mean and spread of log(time), not of time.</>,
    };
  }
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

// B-lives and MTTF at a confidence the viewer picks (#288). The fit carries
// them at 90%; another level is fetched from the model's life path and kept
// here, so going back to a level (or tab) doesn't ask again.
const lifeCache = new Map();
export const LIFE_LEVELS = [80, 90, 95, 99];

function useLife(result, level, tau = null) {
  const path = result.functions?.life_path;
  const stored = result.life;
  // A non-parametric mean life's horizon (#85): the stored one is the default.
  const storedFits = stored && Math.abs(stored.confidence * 100 - level) < 1e-6 && tau == null;
  const key = path ? `${path}|${level}|${tau ?? ""}` : null;
  const [fetched, setFetched] = useState(() => (key && lifeCache.has(key) ? { key, data: lifeCache.get(key) } : null));
  useEffect(() => {
    if (!key || storedFits || !(level > 0 && level < 100)) return undefined;
    if (lifeCache.has(key)) {
      setFetched({ key, data: lifeCache.get(key) });
      return undefined;
    }
    let live = true;
    const id = setTimeout(() => {
      lifeAt(path, { confidence: level / 100, ...(tau != null ? { tau } : {}) })
        .then((data) => {
          lifeCache.set(key, data);
          if (live) setFetched({ key, data });
        })
        .catch(() => live && setFetched({ key, data: null }));
    }, 250);
    return () => {
      live = false;
      clearTimeout(id);
    };
  }, [key, storedFits, level, path, tau]);
  if (storedFits) return { life: stored, pending: false };
  if (fetched?.key === key && fetched.data) return { life: fetched.data, pending: false };
  if (stored) {
    // While another level loads, the estimates stand; their bounds wait.
    return { life: { ...stored, b_lives: stored.b_lives.map((b) => ({ ...b, lower: null })),
                     mttf: tau == null ? { ...stored.mttf, lower: null } : { value: null, lower: null, tau } },
             pending: !!key };
  }
  if (fetched?.data) {
    // Another level or horizon loading: the last answer's estimates stand.
    const last = fetched.data;
    return { life: { ...last, b_lives: last.b_lives.map((b) => ({ ...b, lower: null })),
                     mttf: { value: null, lower: null, tau: tau ?? last.mttf?.tau } }, pending: true };
  }
  if (path && fetched?.key !== key) return { life: null, pending: true };
  // A model saved without them and no live path: the estimates off the curve.
  const fromCurve = [[0.01, "B1"], [0.05, "B5"], [0.1, "B10"], [0.5, "B50"]].map(([p, label]) => ({
    p, label, value: lifeFromCurve(result, p), lower: null,
  }));
  if (fromCurve.every((b) => b.value == null)) return { life: null, pending: false };
  return { life: { b_lives: fromCurve, mttf: { value: null, lower: null }, bounds_note: null }, pending: false };
}

const LIFE_NAMES = { B50: "B50 (median)" };

// The horizon of a non-parametric mean life (#85), typed in place. The value
// is sent when it is a time above zero; the card refetches after a pause.
function TauInput({ tau, unit, onChange }) {
  const [text, setText] = useState(tau != null ? String(+Number(tau).toPrecision(6)) : "");
  const [prevTau, setPrevTau] = useState(tau);
  if (tau !== prevTau) {
    setPrevTau(tau);
    if (Number(text) !== Number(tau)) setText(tau != null ? String(+Number(tau).toPrecision(6)) : "");
  }
  return (
    <input
      className="life-tau"
      type="number"
      min="0"
      step="any"
      value={text}
      aria-label={`Count the mean life up to this time${unit ? ` (${unit})` : ""}`}
      title={`Count the mean life up to this time${unit ? ` (${unit})` : ""}`}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(v) && v > 0) onChange(v);
      }}
    />
  );
}

function LifeCard({ result, level, onLevel }) {
  const [tau, setTau] = useState(null);
  const { life, pending } = useLife(result, level, tau);
  if (!life) return null;
  const unit = result.unit ? unitInText(result.unit) : "";
  // A non-parametric estimate's mean is the area under its curve to a
  // horizon (#85): the whole mean (MTTF) only where the curve reaches zero.
  const np = result.kind === "nonparametric" && life.mttf?.tau != null;
  // Once a horizon is typed, the row keeps its input (and says "to").
  const restricted = np && (life.mttf.restricted !== false || tau != null);
  const canPick = !!result.functions?.life_path && !!onLevel;
  const levels = LIFE_LEVELS.includes(level) ? LIFE_LEVELS : [...LIFE_LEVELS, level].sort((a, b) => a - b);
  const rows = [
    ...life.b_lives.map((b) => ({
      key: b.label, label: LIFE_NAMES[b.label] || b.label, value: b.value, lower: b.lower,
      what: `${b.label}: ${Math.round(b.p * 100)}% have failed by then`,
    })),
    { key: "MTTF", label: restricted ? "Mean life to" : "MTTF (mean)", value: life.mttf?.value,
      lower: life.mttf?.lower,
      what: restricted
        ? `Mean life to ${formatNumber(life.mttf.tau)}${unit ? ` ${unit}` : ""}: the average time to failure, `
          + "counting only up to then — the data don't reach the end of life, so the full mean can't be estimated"
        : life.mttf?.value == null && result.extras?.p != null
        ? "MTTF: none — some units never fail"
        : "MTTF: the mean time to failure" },
  ];
  const hasBounds = rows.some((r) => r.lower != null);
  return (
    <div className="gof-card life-card">
      <div className="gofh life-card-head">
        <span>Life{unit ? <span className="gof-sub">{unit}</span> : null}</span>
        {canPick ? (
          <Select
            value={level}
            onChange={(v) => onLevel(Number(v))}
            className="life-conf"
            title="The confidence of the lower bounds (one-sided)"
            options={levels.map((l) => ({ value: l, label: `${l}% lower bound` }))}
          />
        ) : (
          hasBounds && <span className="gof-sub">{Math.round((life.confidence ?? 0.9) * 100)}% lower bound</span>
        )}
      </div>
      {rows.map((r) => (
        <div
          className="gofr life-row"
          key={r.key}
          title={r.lower != null
            ? `${r.what}. ${boundWords(level, "lower", r.lower, null, (v) => `${formatNumber(v)}${unit ? ` ${unit}` : ""}`)}.`
            : `${r.what}.`}
        >
          <span className="gk">
            {r.label}
            {restricted && r.key === "MTTF" && (
              <TauInput tau={life.mttf.tau} unit={unit} onChange={setTau} />
            )}
          </span>
          <span className="gv">{formatNumber(r.value)}</span>
          <span className="life-lo">{r.lower != null ? `≥ ${formatNumber(r.lower)}` : pending ? "…" : ""}</span>
        </div>
      ))}
      {life.bounds_note && <p className="param-ci-note">{life.bounds_note}</p>}
    </div>
  );
}

// Every distribution on the same data, best first (#293): ΔAIC and a verdict
// in words. A Best fit carries the ranking; any other fit can run it
// (``compare``: () => Promise<selection>). ``onPick(id)`` (a fit not yet
// saved) refits with the chosen distribution.
function CompareDistributions({ result, compare, onPick }) {
  const own = (result.selection?.candidates?.length || 0) > 1 ? result.selection : null;
  const [ran, setRan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const selection = own || ran;
  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setRan(await compare());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  if (!selection) {
    if (!compare) return null;
    return (
      <div className="compare-dists">
        <div className="gofh">Compare distributions</div>
        <p className="muted-line">Fit every distribution to the same data and rank them by AIC.</p>
        <button type="button" className="secondary" onClick={run} disabled={busy}>
          {busy ? "Comparing…" : "Compare with other distributions"}
        </button>
        {error && <p className="error" style={{ marginTop: 8 }}>{error}</p>}
      </div>
    );
  }
  const key = selection.criterion || "aic";
  const label = criterionLabel(key);
  const current = result.distribution_id === "mixture" ? null : result.distribution_id;
  const rows = compareRows(selection.candidates, key, current);
  return (
    <div className="compare-dists">
      <div className="gofh">Compare distributions</div>
      <p className="compare-sentence">{bestFitSentence(rows)}</p>
      {selection.summary && <p className="muted-line">{selection.summary}</p>}
      <div className="rs-table-wrap">
        <table className="mini-table compare-table">
          <thead>
            <tr><th>Distribution</th><th>{label}</th><th>Δ{label}</th><th>Verdict</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const pick = onPick && !r.current && !String(r.id).includes(":");
              return (
                <tr key={r.id} className={r.current ? "current" : undefined}>
                  <td>
                    {pick ? (
                      <button type="button" className="link" onClick={() => onPick(r.id)}
                              title={`Fit ${r.name} to these data instead`}>{r.name}</button>
                    ) : r.name}
                    {r.current && <span className="gof-sub"> · this fit</span>}
                  </td>
                  <td>{formatNumber(r.value, { sig: 5 })}</td>
                  <td>{r.delta === 0 ? "—" : `+${r.delta.toFixed(1)}`}</td>
                  <td>
                    {r.verdict === "best" ? <Chip tone="success">Best</Chip>
                      : <span className={r.verdict === "about" ? "" : "compare-worse"}>{r.verdictLabel}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted-line">
        Lower {label} is better. Under 2 apart, the data can't tell two distributions apart.
        {onPick ? " Pick a name to fit that one instead." : ""}
      </p>
      {selection.failed?.length > 0 && (
        <p className="muted-line">Couldn't fit: {selection.failed.map((f) => f.name).join(", ")}.</p>
      )}
    </div>
  );
}

// ``split`` ({ failed, running, other }) when the caller can count the data.
// ``children`` (the plot) goes on the left; the panel sits on the right.
// ``level`` / ``onLevel``: the confidence (%) of the life card's lower bounds,
// shared with the calculator. ``compare`` / ``onPick``: see CompareDistributions.
export default function LifeAside({ result, split = null, bestFit = false, level = 90, onLevel = null,
                                   compare = null, onPick = null }) {
  const [statsOpen, setStatsOpen] = useState(false);
  const aic = (result.gof || []).find((g) => g.id === "aic") || (result.gof || [])[0];
  const id = distId(result);
  // Shape before scale: the reading turns on the shape.
  const order = id === "weibull" || id === "loglogistic" || id === "expo_weibull" ? ["beta", "alpha", "mu"] : null;
  const params = [...(result.params || [])].sort((a, b) =>
    order ? order.indexOf(a.name) - order.indexOf(b.name) : 0
  );
  const data = dataText(result, split);
  const reading = verdict(result);
  // Maximum likelihood goes without saying; another method is named.
  const method = result.options?.how && result.options.how !== "MLE" ? result.options.how : null;
  const caveat = result.fit_warning && !result.no_finite_maximum;
  const nonparametric = result.kind === "nonparametric";
  const showLife = (result.kind === "distribution" || nonparametric) && !result.no_finite_maximum;
  return (
    <div className="aside">
      <div className="gof-card">
        {nonparametric ? (
          // No parameters to name (#85): the estimator and the data.
          <>
            <div className="gofh">Estimate</div>
            <div className="gofr">
              <span className="gk">Method</span>
              <span className="gv">{result.distribution}</span>
            </div>
          </>
        ) : (
          <div className="gofh life-card-head">
            <span>Parameters</span>
            {/* #292: the guide to reading a fit, in the help drawer. */}
            <button type="button" className="link life-help" onClick={() => openGuide("fit-your-first-model")}>
              What do these mean?
            </button>
          </div>
        )}
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
        {aic && (
          <button type="button" className="gofr gofr-link" onClick={() => setStatsOpen(true)}>
            <span className="gk">Fit statistics</span>
            <span className="gv">AIC {formatNumber(aic.value, { sig: 5 })} ›</span>
          </button>
        )}
      </div>
      {showLife && <LifeCard result={result} level={level} onLevel={onLevel} />}
      {caveat && <div className="life-reading caveat">{result.fit_warning}</div>}
      {reading && (
        <div className="life-reading">
          <div className="life-reading-title">{reading.title}</div>
          <div>{reading.text}</div>
        </div>
      )}
      {method && <p className="life-method">{method} fit.</p>}
      {statsOpen && (
        <Modal title="Fit statistics" onClose={() => setStatsOpen(false)}
               footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}>
                 <button onClick={() => setStatsOpen(false)}>Done</button></div>}>
          <GoodnessOfFit gof={result.gof} n={result.n} note={result.gof_note} bestFit={bestFit || !!compare} />
          {result.kind === "distribution" && (
            <CompareDistributions result={result} compare={compare}
                                  onPick={onPick && ((id) => { setStatsOpen(false); onPick(id); })} />
          )}
        </Modal>
      )}
    </div>
  );
}
