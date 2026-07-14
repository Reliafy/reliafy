import { useRef, useState } from "react";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import SurvivalPlot from "./SurvivalPlot.jsx";
import Calculator, { initCalcState } from "./Calculator.jsx";
import GoodnessOfFit from "./GoodnessOfFit.jsx";
import Coefficients from "./Coefficients.jsx";
import { distColor } from "../instrument.js";

const DISTRIBUTION_TABS = [
  { id: "plot", label: "Probability plot" },
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Goodness of fit" },
];
const NONPARAMETRIC_TABS = [
  { id: "survival", label: "Survival curve" },
  { id: "calc", label: "Calculator" },
];
// Discrete distributions have no probability paper, so no probability plot.
const DISCRETE_TABS = [
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Goodness of fit" },
];

const pct = (v) => `${(v * 100).toFixed(v < 0.1 ? 2 : 1)}%`;

// Per-demand (Binomial) reliability: a probability, not a curve over time.
function PerDemandPanel({ result }) {
  const d = result.per_demand || {};
  const color = distColor(result.distribution);
  return (
    <>
      <div className="result-head">
        <span className="dpill"><span className="dot" style={{ background: color }} />Per-demand</span>
      </div>
      <div className="params">
        <div className="stat">
          <div className="value">{pct(d.p)}</div>
          <div className="name">failure probability / demand</div>
          {d.ci && <div className="param-ci">95% CI [{pct(d.ci[0])}, {pct(d.ci[1])}]</div>}
        </div>
        <div className="stat">
          <div className="value">{pct(d.reliability)}</div>
          <div className="name">reliability / demand</div>
        </div>
        <div className="stat">
          <div className="value">{d.failures} / {d.demands}</div>
          <div className="name">failures / demands</div>
        </div>
      </div>
      <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
        Estimated from {d.failures} failure{d.failures === 1 ? "" : "s"} in {d.demands} demands
        (Binomial, Wilson 95% interval). For one-shot and protective equipment — feeds
        failure-finding intervals.
      </p>
    </>
  );
}
const REGRESSION_TABS = [
  { id: "coef", label: "Coefficients" },
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Goodness of fit" },
];

const fmtGof = (v) =>
  Math.abs(v) >= 1e-4 || v === 0 ? Number(v).toFixed(2) : Number(v).toExponential(2);

// One-line interpretation of the failure pattern — the statistical evidence an
// RCM run-to-failure decision leans on.
function RandomnessVerdict({ r }) {
  if (r.basis === "memoryless") {
    return (
      <p className="verdict-line">
        Exponential model — memoryless by construction: failures occur at a
        constant rate (<b>random</b>). Time-based replacement won't help.
      </p>
    );
  }
  const ci = r.beta_ci ? `[${r.beta_ci[0].toPrecision(3)}, ${r.beta_ci[1].toPrecision(3)}]` : null;
  const beta = `β = ${Number(r.beta).toPrecision(3)}${ci ? ` ${ci}` : ""}`;
  const text = {
    random: <>the CI contains 1 — failures are <b>consistent with a random</b> (constant-rate) process.</>,
    wear_out: <>the CI excludes 1 — this is <b>wear-out</b>; preventive replacement can pay off.</>,
    infant_mortality: <>the CI is below 1 — <b>infant mortality</b>; failures decrease with age.</>,
    inconclusive: <>no confidence interval available — the failure pattern is <b>inconclusive</b>.</>,
  }[r.verdict];
  return <p className="verdict-line">{beta}: {text}</p>;
}

// Presentational result panel for a fit (used for both fresh and saved models).
// ``hideHead`` drops the distribution pill when the surrounding page already
// shows it (e.g. the saved-model page header) to avoid stating it twice.
export default function ResultView({ result, hideHead = false }) {
  if (result.kind === "per_demand") return <PerDemandPanel result={result} />;

  const isRegression = result.kind === "regression";
  const isNonparametric = result.kind === "nonparametric";
  const isDiscrete = result.kind === "discrete";
  // Params-only models (created from parameters, no data) have no probability
  // plot or goodness-of-fit — just the functions.
  const hasPlot = !!result.plot;
  const defaultTab = isRegression
    ? "coef"
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

  const color = distColor(result.distribution);
  const gof = result.gof || [];
  const metrics = result.metrics || {};

  return (
    <>
      {!hideHead && (
        <div className="result-head">
          <span className="dpill">
            <span className="dot" style={{ background: color }} />
            {result.distribution}
          </span>
        </div>
      )}
      {/* Distributions with a probability plot move their parameters into the
          plot's side rail (below); other kinds keep the top summary bar. The
          observation count is no longer shown as a stat. */}
      {!hasPlot && (
        <div className="params">
          {result.params.map((p) => (
            <div className="stat" key={p.name}>
              <div className="value">{p.value.toPrecision(4)}</div>
              <div className="name">{p.name}</div>
              {p.ci && (
                <div className="param-ci">
                  95% CI [{p.ci[0].toPrecision(3)}, {p.ci[1].toPrecision(3)}]
                </div>
              )}
            </div>
          ))}
          {(result.extra_params || []).map((p) => (
            <div className="stat" key={p.name}>
              <div className="value">{p.value.toPrecision(4)}</div>
              <div className="name">{p.name}</div>
            </div>
          ))}
          {(isNonparametric || isDiscrete) && metrics.median != null && (
            <div className="stat"><div className="value">{Number(metrics.median).toPrecision(4)}</div><div className="name">median life</div></div>
          )}
          {(isNonparametric || isDiscrete) && metrics.mttf != null && (
            <div className="stat"><div className="value">{Number(metrics.mttf).toPrecision(4)}</div><div className="name">MTTF</div></div>
          )}
        </div>
      )}
      {isNonparametric && (
        <p className="muted-line" style={{ margin: "0.4rem 0 0" }}>
          Non-parametric empirical estimate — no distribution assumed, so no
          fitted parameters or goodness-of-fit.
        </p>
      )}
      {isDiscrete && (
        <p className="muted-line" style={{ margin: "0.4rem 0 0" }}>
          Discrete distribution — fitted to whole-count life data (cycles, shocks
          or demands to failure). There's no probability plot; the fitted
          reliability functions and goodness-of-fit are shown.
        </p>
      )}
      {result.params_only && (
        <p className="muted-line" style={{ margin: "0.4rem 0 0" }}>
          Created from parameters — reliability functions and life metrics are
          available; there's no probability plot without data.
        </p>
      )}
      {result.selection && result.selection.candidates?.length > 1 && (
        <p className="muted-line" style={{ margin: "0.4rem 0 0" }}>
          Selected by lowest AIC over {result.selection.candidates.length}{" "}
          candidates — next best:{" "}
          {result.selection.candidates[1].name} (ΔAIC +
          {(result.selection.candidates[1].aic - result.selection.candidates[0].aic).toFixed(1)})
        </p>
      )}
      {result.options && (
        <p className="muted-line" style={{ margin: "0.4rem 0 0" }}>
          Fit options:{" "}
          {[
            result.options.offset && "3-parameter offset",
            result.options.lfp && "limited failure population",
            result.options.zi && "zero-inflated",
            result.options.fixed &&
              `fixed ${Object.entries(result.options.fixed).map(([k, v]) => `${k} = ${v}`).join(", ")}`,
          ].filter(Boolean).join(" · ")}
        </p>
      )}

      {result.randomness && <RandomnessVerdict r={result.randomness} />}

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
            <SurvivalPlot estimate={result.estimate} unit={result.unit} />
          </div>
        )}
        {tab === "plot" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <div className="plottitle">{result.distribution} probability plot</div>
              <ProbabilityPlot plot={result.plot} unit={result.unit} />
            </div>
            <div className="aside">
              {result.params.length > 0 && (
                <div className="gof-card">
                  <div className="gofh">Parameters</div>
                  {result.params.map((p) => (
                    <div className="gofr" key={p.name}>
                      <span className="gk">{p.name}</span>
                      <span className="gv-col">
                        <span className="gv">{p.value.toPrecision(4)}</span>
                        {p.ci && (
                          <span className="param-ci">
                            95% CI [{p.ci[0].toPrecision(3)}, {p.ci[1].toPrecision(3)}]
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
                  {(result.extra_params || []).map((p) => (
                    <div className="gofr" key={p.name}>
                      <span className="gk">{p.name}</span>
                      <span className="gv">{p.value.toPrecision(4)}</span>
                    </div>
                  ))}
                </div>
              )}
              {gof.length > 0 && (
                <div className="gof-card">
                  <div className="gofh">Goodness of fit</div>
                  {gof.map((g) => (
                    <div className="gofr" key={g.id}>
                      <span className="gk">{g.label}</span>
                      <span className="gv">{fmtGof(g.value)}</span>
                    </div>
                  ))}
                </div>
              )}
              <div className="detail-note">
                Maximum-likelihood fit over <b>{result.n} observations</b>. The
                line is the fitted model; points are the data on{" "}
                {result.distribution} probability paper, with a 95% confidence
                band.
              </div>
            </div>
          </div>
        )}
        {tab === "calc" && (
          <Calculator
            functions={result.functions}
            unit={result.unit}
            state={calc}
            setState={setCalc}
            nextIdRef={calcNextId}
          />
        )}
        {tab === "coef" && <Coefficients coefficients={result.coefficients} />}
        {tab === "gof" && <GoodnessOfFit gof={result.gof} n={result.n} />}
      </div>
    </>
  );
}
