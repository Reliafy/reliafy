import { useState } from "react";
import Modal from "./Modal.jsx";
import GoodnessOfFit from "./GoodnessOfFit.jsx";
import Chip from "./ui/Chip.jsx";
import ModelNextSteps, { ReplacementLink } from "./ModelNextSteps.jsx";
import { openGuide } from "./HelpButton.jsx";
import { formatNumber } from "../format.js";
import { bestFitSentence, compareRows, criterionLabel, timeAtValue } from "../lifeResults.js";
import { unitInText } from "./unitText.js";
import { PARAMS, paramLabel } from "../paramLabels.js";
import ScrollCue from "./ui/ScrollCue.jsx";

// The side panel beside a fitted life distribution's plot (#311): its
// parameters by their plain names with their intervals, the data, and a quiet
// row with what the fit says (the failure pattern or the median life) that
// opens its reading in words — the answer next to the chart, not stacked
// above the tabs. B-lives are read on the Calculator tab ("Time at
// reliability": R = 90% is the B10 life).

function distId(result) {
  if (result.distribution_id && result.distribution_id !== "best") return result.distribution_id;
  const name = String(result.distribution || "").toLowerCase();
  return Object.keys(PARAMS).find((k) => name === k || name.replace(/[^a-z]/g, "") === k) || null;
}

// A parameter with its plain label (unit included) and formatted value.
export function paramView(result, p) {
  return {
    label: paramLabel(distId(result), p.name, result.unit),
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
// ``label`` and ``short`` are the panel row that opens it ("Failure pattern ·
// Wear-out", "Median life · 1,240 hours").
export function verdict(result) {
  const v = verdictText(result);
  if (!v) return null;
  return { label: "Failure pattern", short: v.title, ...v };
}

function verdictText(result) {
  const id = distId(result);
  const unit = result.unit ? ` ${unitInText(result.unit)}` : "";
  const byName = Object.fromEntries((result.params || []).map((p) => [p.name, p]));
  if (id === "weibull" && byName.beta) {
    const beta = byName.beta.value;
    const v = result.randomness?.verdict;
    if (v === "wear_out")
      return { title: "Wear-out", text: "β is above 1 at 95% confidence: the failure rate rises with age, so preventive replacement can pay off.",
               action: "replacement" };
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
      title: "Median life", label: "Median life", short: `${formatNumber(median)}${unit}`,
      text: <><b>{formatNumber(median)}{unit}</b> (e<sup>μ</sup>): half have failed by then. μ and σ are the
        mean and spread of log(time), not of time.</>,
    };
  }
  if (median != null) {
    return { title: "Median life", label: "Median life", short: `${formatNumber(median)}${unit}`,
             text: <><b>{formatNumber(median)}{unit}</b>: half have failed by then.</> };
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
      <ScrollCue className="rs-table-wrap">
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
      </ScrollCue>
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
// ``compare`` / ``onPick``: see CompareDistributions. ``modelId``: the saved
// model, for "Use this model" (#294); ``onUse`` (a fit not saved yet) saves it
// first.
export default function LifeAside({ result, split = null, bestFit = false, compare = null, onPick = null,
                                   modelId = null, onUse = null }) {
  const [statsOpen, setStatsOpen] = useState(false);
  const [readingOpen, setReadingOpen] = useState(false);
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
        {/* What the fit says, one quiet row; its reading in words opens on click. */}
        {reading && (
          <button type="button" className="gofr gofr-link life-reading-row" onClick={() => setReadingOpen(true)}
                  aria-haspopup="dialog" aria-label={`${reading.label}: ${reading.short}. What this means`}>
            <span className="gk">{reading.label}</span>
            <span className="gv">{reading.short} ›</span>
          </button>
        )}
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
      {caveat && <div className="life-reading caveat">{result.fit_warning}</div>}
      <ModelNextSteps result={result} modelId={modelId} onUse={onUse} />
      {method && <p className="life-method">{method} fit.</p>}
      {readingOpen && reading && (
        <Modal title={reading.title} className="modal-sm reading-modal" onClose={() => setReadingOpen(false)}
               footer={<div className="row" style={{ margin: 0, marginLeft: "auto" }}>
                 <button type="button" onClick={() => setReadingOpen(false)}>Done</button></div>}>
          <p className="reading-text">{reading.text}</p>
          {reading.action === "replacement" && <ReplacementLink result={result} modelId={modelId} onUse={onUse} />}
        </Modal>
      )}
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
