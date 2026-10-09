import { useRef, useState } from "react";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import SurvivalPlot from "./SurvivalPlot.jsx";
import Calculator, { initCalcState } from "./Calculator.jsx";
import GoodnessOfFit from "./GoodnessOfFit.jsx";
import Coefficients from "./Coefficients.jsx";
import ModelValidation from "./ModelValidation.jsx";
import NoMaximumNotice from "./NoMaximumNotice.jsx";
import CiNote from "./CiNote.jsx";
import LifeSummary, { paramView } from "./LifeSummary.jsx";
import { ResultDetails } from "./ui/ResultSummary.jsx";
import { distColor } from "../instrument.js";
import { formatNumber } from "../format.js";
import Chip from "./ui/Chip.jsx";

const DISTRIBUTION_TABS = [
  { id: "plot", label: "Probability plot" },
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Fit quality" },
];
const NONPARAMETRIC_TABS = [
  { id: "survival", label: "Survival curve" },
  { id: "calc", label: "Calculator" },
];
// Discrete distributions have no probability paper, so no probability plot.
const DISCRETE_TABS = [
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Fit quality" },
];

const pct = (v) => `${(v * 100).toFixed(v < 0.1 ? 2 : 1)}%`;

// Per-demand (Binomial) reliability: a probability, not a curve over time.
// Models saved before #233 carry a Wilson 95% interval and no confidence /
// method; newer ones carry exact (Clopper-Pearson) bounds at their confidence,
// the one-sided reliability bound and, from several batches, the batches.
function PerDemandPanel({ result }) {
  const d = result.per_demand || {};
  const color = distColor(result.distribution);
  const exact = d.method === "exact";
  const c = Math.round((d.confidence ?? 0.95) * 100);
  const level = exact ? `${c}%` : "95%";
  const batches = d.batches || [];
  return (
    <>
      <div className="result-head">
        <Chip dot={color}>Per-demand</Chip>
      </div>
      <div className="params">
        <div className="stat">
          <div className="value">{pct(d.p)}</div>
          <div className="name">failure probability / demand</div>
          {d.ci && <div className="param-ci">{level} CI [{pct(d.ci[0])}, {pct(d.ci[1])}]</div>}
        </div>
        <div className="stat">
          <div className="value">{pct(d.reliability)}</div>
          <div className="name">reliability / demand</div>
          {d.reliability_ci && (
            <div className="param-ci">{level} CI [{pct(d.reliability_ci[0])}, {pct(d.reliability_ci[1])}]</div>
          )}
        </div>
        {exact && d.reliability_lower != null && (
          <div className="stat">
            <div className="value">≥ {pct(d.reliability_lower)}</div>
            <div className="name">reliability @ {c}% conf. (one-sided)</div>
          </div>
        )}
        <div className="stat">
          <div className="value">{d.failures} / {d.demands}</div>
          <div className="name">failures / demands{batches.length > 1 ? ` · ${batches.length} batches` : ""}</div>
        </div>
        {!exact && d.success_run && (
          <div className="stat">
            <div className="value">≥ {pct(d.success_run.reliability_lower)}</div>
            <div className="name">demonstrated @ {Math.round(d.success_run.confidence * 100)}% conf.</div>
          </div>
        )}
      </div>
      {batches.length > 1 && (
        <div className="pd-batch-table">
          <table className="mini-table">
            <thead><tr><th>Batch</th><th>Demands</th><th>Failures</th><th>Failures / demand</th></tr></thead>
            <tbody>
              {batches.map((b, i) => (
                <tr key={i}><td>{b.label}</td><td>{b.demands}</td><td>{b.failures}</td><td>{pct(b.p)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {d.success_run ? (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Success run — {d.demands} demand{d.demands === 1 ? "" : "s"} with zero failures
          demonstrates reliability <b>≥ {pct(d.success_run.reliability_lower)}</b> at{" "}
          {Math.round(d.success_run.confidence * 100)}% confidence (one-sided lower bound,
          R ≥ (1 − C)<sup>1/n</sup>). For one-shot and protective equipment — feeds
          failure-finding intervals.
        </p>
      ) : exact ? (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Estimated from {d.failures} failure{d.failures === 1 ? "" : "s"} in {d.demands} demands
          {batches.length > 1 ? `, pooled over ${batches.length} batches (one failure probability for all)` : ""}.
          Bounds are exact (Clopper-Pearson) at {c}% confidence. For one-shot and protective
          equipment — feeds failure-finding intervals.
        </p>
      ) : (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Estimated from {d.failures} failure{d.failures === 1 ? "" : "s"} in {d.demands} demands
          (Binomial, Wilson 95% interval). For one-shot and protective equipment — feeds
          failure-finding intervals.
        </p>
      )}
    </>
  );
}

const REGRESSION_TABS = [
  { id: "coef", label: "Coefficients" },
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Fit quality" },
  { id: "check", label: "Validation" },
];

// Presentational result panel for a fit (used for both fresh and saved
// models). Answer first (#311): the verdict and up to four tiles, then the
// tabs (plot, calculator, fit quality), then the rest folded under Details.
// ``modelId`` (a saved model) lets a regression model saved before its
// validation scores existed fetch them. ``split`` ({ failed, running, other })
// is the data's failure / still-running count when the caller has the data.
export default function ResultView({ result, modelId = null, name = null, split = null }) {
  if (result.kind === "per_demand") return <PerDemandPanel result={result} />;

  const isRegression = result.kind === "regression";
  const isNonparametric = result.kind === "nonparametric";
  const isDiscrete = result.kind === "discrete";
  // Params-only models (created from parameters, no data) have no probability
  // plot or goodness-of-fit — just the functions.
  const hasPlot = !!result.plot;
  const defaultTab = isRegression
    ? (result.functions ? "calc" : "coef")
    : isNonparametric
    ? "survival"
    : isDiscrete
    ? "calc"
    : hasPlot
    ? "plot"
    : "calc";
  const [tab, setTab] = useState(defaultTab);

  // The Calculator tab unmounts when you switch away, so its inputs live here
  // and survive tab switches. When the result itself changes in place (e.g.
  // fitting another model in the workspace) reset them for the new model.
  const [calc, setCalc] = useState(() => initCalcState(result.functions));
  const calcNextId = useRef(1);
  const [prevResult, setPrevResult] = useState(result);
  if (result !== prevResult) {
    setPrevResult(result);
    setCalc(initCalcState(result.functions));
    calcNextId.current = 1;
    setTab(defaultTab);
  }

  let tabs = isNonparametric
    ? NONPARAMETRIC_TABS
    : isRegression
    ? REGRESSION_TABS
    : isDiscrete
    ? DISCRETE_TABS
    : DISTRIBUTION_TABS;
  if (!result.functions) tabs = tabs.filter((t) => t.id !== "calc");
  if (!isNonparametric && !isDiscrete && !hasPlot)
    tabs = tabs.filter((t) => t.id !== "plot" && t.id !== "gof");

  // PH models show their baseline parameters in the calculator's side rail;
  // every other kind leads with the answer card.
  const paramsInRail = isRegression && !!result.functions;
  const bestFit = (result.selection?.candidates?.length || 0) > 1;

  // The adjustments a fit used, in words (a mixture's own settings aren't).
  const optionWords = result.options
    ? [
        result.options.offset && "3-parameter offset",
        result.options.lfp && "limited failure population",
        result.options.zi && "zero-inflated",
        result.options.fixed &&
          `fixed ${Object.entries(result.options.fixed).map(([k, v]) => `${k} = ${v}`).join(", ")}`,
      ].filter(Boolean)
    : [];
  let selectionNote = null;
  if (bestFit) {
    const key = result.selection.criterion || "aic";
    const label = key === "bic" ? "BIC" : key === "aic_c" ? "AICc" : "AIC";
    const [first, second] = result.selection.candidates;
    // Mixtures on (#236): the summary says which criterion decided — BIC
    // between the best mixture and the best single, AIC among the singles.
    selectionNote = result.selection.summary || (
      `Selected by lowest ${label} over ${result.selection.candidates.length} candidates` +
      `${result.selection.include_mixtures ? ", two-mode mixtures included" : ""} — next best: ` +
      `${second.name} (Δ${label} +${(second[key] - first[key]).toFixed(1)})`
    );
  }

  // Everything the answer card leaves out, folded under Details: parameters
  // past the two tiles (with their intervals), how the model was chosen and
  // fitted, and what this kind of model can't show.
  const params = result.params || [];
  const extra = result.extra_params || [];
  const moreParams = !isRegression && (params.length > 2 || extra.length > 0);
  const details = !isRegression && (
    moreParams || optionWords.length > 0 || selectionNote || isNonparametric || isDiscrete ||
    result.params_only || result.mixture > 1
  );

  const method = result.options?.how && result.options.how !== "MLE"
    ? `Fitted by ${result.options.how}` : "Maximum-likelihood fit";

  return (
    <>
      <NoMaximumNotice notice={result.no_finite_maximum} style={{ margin: "0 0 12px" }} />
      {!isRegression && <LifeSummary result={result} split={split} />}
      {/* Best fit picked a two-mode mixture (#236): say what the modes are. */}
      {result.mixture_summary && (
        <p className="mixture-summary">{result.mixture_summary}</p>
      )}
      {isRegression && !paramsInRail && (
        <>
          <div className="params">
            {params.map((p) => (
              <div className="stat" key={p.name}>
                <div className="value">{formatNumber(p.value, { sig: 4 })}</div>
                <div className="name">{p.name}</div>
                {p.ci && (
                  <div className="param-ci">
                    95% CI [{formatNumber(p.ci[0])}, {formatNumber(p.ci[1])}]
                  </div>
                )}
              </div>
            ))}
          </div>
          <CiNote params={params} note={result.ci_note} />
        </>
      )}
      <div className="tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            className={"tab" + (tab === t.id ? " active" : "")}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="tab-panel">
        {tab === "survival" && (
          <div className="plotwrap">
            <div className="plottitle">{result.distribution} — empirical survival</div>
            <SurvivalPlot estimate={result.estimate} unit={result.unit}
                          download={`${name || result.distribution} — survival curve`} />
          </div>
        )}
        {tab === "plot" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <div className="plottitle">{result.distribution} probability plot</div>
              <ProbabilityPlot plot={result.plot} unit={result.unit}
                               download={`${name || result.distribution} — probability plot`} />
              <p className="plot-caption">
                {method} to {result.n?.toLocaleString()} observations: the line is the model, the
                points the data{result.plot?.bounds ? ", the band its 95% confidence" : ""}.
              </p>
            </div>
          </div>
        )}
        {tab === "calc" && (
          <Calculator
            functions={result.functions}
            unit={result.unit}
            params={paramsInRail ? result.params : null}
            state={calc}
            setState={setCalc}
            nextIdRef={calcNextId}
            name={name || result.distribution}
          />
        )}
        {tab === "coef" && <Coefficients coefficients={result.coefficients} ratioLabel={result.ratio_label} />}
        {tab === "gof" && (
          <GoodnessOfFit gof={result.gof} n={result.n} note={result.gof_note} bestFit={bestFit} />
        )}
        {tab === "check" && (
          <ModelValidation validation={result.validation} modelId={modelId} unit={result.unit} />
        )}
      </div>

      {details && (
        <ResultDetails>
          {moreParams && (
            <div className="rs-table-wrap">
              <table className="mini-table">
                <thead><tr><th>Parameter</th><th>Estimate</th><th>95% interval</th></tr></thead>
                <tbody>
                  {params.map((p) => {
                    const v = paramView(result, p);
                    return <tr key={p.name}><td>{v.label}</td><td>{v.value}</td><td>{v.ci || "—"}</td></tr>;
                  })}
                  {extra.map((p) => (
                    <tr key={p.name}><td>{p.name}</td><td>{formatNumber(p.value)}</td><td>—</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selectionNote && <p className="rs-note">{selectionNote}</p>}
          {optionWords.length > 0 && <p className="rs-note">Fit options: {optionWords.join(" · ")}</p>}
          {result.mixture > 1 && (
            <p className="rs-note">
              A mixture has no covariance matrix, so it reports no confidence bounds — judge it on
              the AIC against a single fit.
            </p>
          )}
          {isNonparametric && (
            <p className="rs-note">
              Non-parametric empirical estimate — no distribution assumed, so no fitted parameters
              or goodness-of-fit.
            </p>
          )}
          {isDiscrete && (
            <p className="rs-note">
              Discrete distribution — fitted to whole-count life data (cycles, shocks or demands to
              failure). There's no probability plot.
            </p>
          )}
          {result.params_only && (
            <p className="rs-note">
              Created from parameters — reliability functions and life metrics are available;
              there's no probability plot without data.
            </p>
          )}
        </ResultDetails>
      )}
    </>
  );
}
