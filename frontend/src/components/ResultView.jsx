import { useState } from "react";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import Calculator from "./Calculator.jsx";
import GoodnessOfFit from "./GoodnessOfFit.jsx";
import Coefficients from "./Coefficients.jsx";
import { distColor } from "../instrument.js";

const DISTRIBUTION_TABS = [
  { id: "plot", label: "Probability plot" },
  { id: "calc", label: "Calculator" },
  { id: "gof", label: "Goodness of fit" },
];
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
export default function ResultView({ result }) {
  const isRegression = result.kind === "regression";
  const [tab, setTab] = useState(isRegression ? "coef" : "plot");

  let tabs = isRegression ? REGRESSION_TABS : DISTRIBUTION_TABS;
  if (!result.functions) tabs = tabs.filter((t) => t.id !== "calc");

  const color = distColor(result.distribution);
  const gof = result.gof || [];

  return (
    <>
      <div className="result-head">
        <span className="dpill">
          <span className="dot" style={{ background: color }} />
          {result.distribution}
        </span>
      </div>
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
        <div className="stat">
          <div className="value">{result.n}</div>
          <div className="name">observations</div>
        </div>
      </div>
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
        {tab === "plot" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <div className="plottitle">{result.distribution} probability plot</div>
              <ProbabilityPlot plot={result.plot} unit={result.unit} />
            </div>
            <div className="aside">
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
          <Calculator functions={result.functions} unit={result.unit} />
        )}
        {tab === "coef" && <Coefficients coefficients={result.coefficients} />}
        {tab === "gof" && <GoodnessOfFit gof={result.gof} n={result.n} />}
      </div>
    </>
  );
}
