import { useState } from "react";
import Plot from "./Plot.jsx";
import { NEUTRAL_BAND_FILL, band, dataPoints, fitLine } from "../plotTheme.js";
import RecurrentCalculator from "./RecurrentCalculator.jsx";
import { unitInText } from "./unitText.js";
import ResultSummary from "./ui/ResultSummary.jsx";
import { formatNumber } from "../format.js";

const fmt = (v, d = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });
// Significant figures, for rates and intervals that can be very small.
const sig = (v, n = 4) => formatNumber(v, { sig: n });
const ciText = (ci, n = 3) => (ci ? `${sig(ci[0], n)}–${sig(ci[1], n)}` : null);
// Plain names for the power-law parameters.
const PARAM_LABEL = { alpha: "Scale α", beta: "Shape β" };
const pText = (p) => (p < 0.001 ? "p < 0.001" : `p = ${sig(p, 2)}`);

// ``summary``: the answer card's tone — green for the good verdict, amber
// for the one to act on.
const GROWTH = {
  improving: { label: "Improving", note: "failures are slowing", summary: "good" },
  stable: { label: "Stable", note: "no clear trend in the failure rate", summary: "neutral" },
  deteriorating: { label: "Deteriorating", note: "failures are accelerating", summary: "caveat" },
};

// Why the verdict is what it is (#81): β's 95% interval against 1 (a slope
// against 0 for Cox-Lewis), or the value itself for a model built from
// parameters.
function basisText(b) {
  if (!b) return null;
  const sym = b.symbol || "β";
  const nul = b.no_trend;
  if (b.ci) {
    const [lo, hi] = b.ci;
    const where = lo > nul ? `wholly above ${nul}` : hi < nul ? `wholly below ${nul}` : `includes ${nul}`;
    return `${sym}'s 95% interval, ${ciText(b.ci)}, ${where}`;
  }
  return `${sym} = ${sig(b.estimate)} (no interval — the value decides)`;
}

const TABS = [
  { id: "mcf", label: "MCF plot" },
  { id: "calc", label: "Calculator" },
  { id: "detail", label: "Trend & fit" },
];

// A fitted recurrent-event (repairable-system) model, laid out like the life-
// data result view (#311): the growth verdict and four tiles first, then the
// mean-cumulative-function plot, the calculator and a "Trend & fit" tab with
// the parameters, intervals and tests. Handles both data fits and models built
// from parameters (no observed step, trend tests, bounds or goodness of fit).
export default function RecurrentResultView({ results, name = null }) {
  const r = results || {};
  const [tab, setTab] = useState("mcf");
  const unit = r.unit ? ` ${unitInText(r.unit)}` : "";
  const xTitle = r.unit ? `Time (${r.unit})` : "Time";
  const obs = r.mcf?.observed || {};
  const fit = r.mcf?.fitted || {};
  const growth = GROWTH[r.growth] || null;
  const basis = basisText(r.growth_basis);
  const dm = r.demonstrated_mtbf;
  const crow = r.bounds_method === "crow";
  const tests = r.trend_tests || (r.trend ? [r.trend] : []);
  const cvm = r.gof_test;
  const systems = (r.system_residuals || []).slice(0, 5);
  const at = r.end_of_observation ?? r.horizon;

  const traces = [];
  if (obs.lower && obs.upper) {
    // The band is on the observed MCF, so it is neutral, like the steps.
    traces.push(band({
      x: [...obs.x, ...[...obs.x].reverse()],
      y: [...obs.upper, ...[...obs.lower].reverse()],
      fillcolor: NEUTRAL_BAND_FILL, name: "95% band",
    }));
  }
  if (obs.x?.length) {
    traces.push(dataPoints({
      x: obs.x, y: obs.mcf, mode: "lines+markers",
      line: { color: "rgba(20, 23, 28, 0.7)", width: 1.25, shape: "hv" },
      marker: { size: 5, line: { width: 0 } }, name: "Observed (MCF)",
    }));
  }
  if (fit.x) {
    traces.push(fitLine({ x: fit.x, y: fit.mcf, name: `${r.model?.name || "Fitted"}` }));
  }

  const layout = {
    height: 420,
    xaxis: { title: { text: xTitle }, rangemode: "tozero" },
    yaxis: { title: { text: "Cumulative failures (MCF)" }, rangemode: "tozero" },
  };

  const anyCi = (r.params || []).some((p) => p.ci);
  const hasBeta = (r.params || []).some((p) => p.name === "beta");
  const perUnit = r.unit ? ` per ${unitInText(r.unit).replace(/s$/, "")}` : "";

  return (
    <>
      <ResultSummary
        tone={growth?.summary || "neutral"}
        sentence={growth
          ? <><b>{growth.label}</b> — {growth.note}{basis ? `: ${basis}` : ""}.</>
          : <><b>{r.model?.name || "Recurrent model"}</b> fitted.</>}
        stats={[
          r.mtbf != null && {
            label: `MTBF now${r.unit ? ` (${unitInText(r.unit)})` : ""}`,
            value: sig(r.mtbf, 3),
            hint: dm && dm.lower != null
              ? `at least ${sig(dm.lower, 3)} at ${Math.round((dm.confidence || 0.9) * 100)}% confidence`
              : null,
          },
          r.rocof != null && { label: "Failure rate now", value: sig(r.rocof, 3), hint: perUnit.trim() || null },
          r.n_systems != null && { label: "Systems / failures", value: `${r.n_systems} / ${r.n_events}` },
          { label: "Model", value: r.model?.name || "—" },
        ]}
      />
      <div className="tabs">
        {TABS.map((tb) => (
          <button
            key={tb.id}
            className={"tab" + (tab === tb.id ? " active" : "")}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      <div className="tab-panel">
        {tab === "mcf" && (
          <div className="detail-panel">
            <div className="plotwrap">
              <div className="plottitle">{r.model?.name || "Recurrent"} — mean cumulative function</div>
              <Plot data={traces} layout={layout} download={`${name || r.model?.name || "Recurrent model"} — mean cumulative function`} />
              <p className="plot-caption">
                {r.n_systems != null
                  ? <>Fitted to {r.n_events} failures across {r.n_systems} systems: the step is the observed MCF with its 95% band, the line the fitted {r.model?.name || "model"}.</>
                  : <>Built from parameters: the line is the {r.model?.name || "model"}; there's no observed data.</>}
              </p>
            </div>
          </div>
        )}

        {tab === "calc" && <RecurrentCalculator r={r} name={name} />}

        {tab === "detail" && (
          <div className="detail-panel" style={{ flexWrap: "wrap", alignItems: "flex-start" }}>
            {(r.params || []).length > 0 && (
              <div className="gof-card rec-detail-card">
                <div className="gofh">Parameters</div>
                {r.params.map((p) => (
                  <div className="gofr" key={p.name}>
                    <span className="gk">{PARAM_LABEL[p.name] || p.name}{p.name === "alpha" && r.unit ? ` (${unitInText(r.unit)})` : ""}</span>
                    <span className="gv-col">
                      <span className="gv">{sig(p.value)}</span>
                      {p.ci && <span className="param-ci">95% {ciText(p.ci)}</span>}
                    </span>
                  </div>
                ))}
                {r.beta != null && !hasBeta && (
                  <div className="gofr">
                    <span className="gk">Shape β</span>
                    <span className="gv-col">
                      <span className="gv">{sig(r.beta)}</span>
                      {r.beta_ci && <span className="param-ci">95% {ciText(r.beta_ci)}</span>}
                    </span>
                  </div>
                )}
                {anyCi && (
                  <p className="param-ci-note">95% intervals from the fit's observed information.</p>
                )}
              </div>
            )}
            <div className="gof-card rec-detail-card">
              <div className="gofh">Rates{at != null ? ` at ${fmt(at, 1)}${unit}` : ""}</div>
              <div className="gofr">
                <span className="gk" title="1 ÷ the failure rate at the end of observation. If the system is deteriorating this is below the average over the test.">MTBF now (end of test)</span>
                <span className="gv-col">
                  <span className="gv">{fmt(r.mtbf, 1)}{unit}</span>
                  {r.mtbf_ci && <span className="param-ci">95% {ciText(r.mtbf_ci)}</span>}
                </span>
              </div>
              {dm && dm.lower != null && (
                <div className="gofr">
                  <span className="gk" title="One-sided lower bound on the MTBF at the end of the test (MIL-HDBK-189C).">MTBF now, lower bound</span>
                  <span className="gv-col">
                    <span className="gv">≥ {fmt(dm.lower, 1)}{unit}</span>
                    <span className="param-ci">demonstrated, at {Math.round((dm.confidence || 0.9) * 100)}% · {dm.method === "crow" ? "Crow exact (MIL-HDBK-189C)" : "Wald"}</span>
                  </span>
                </div>
              )}
              <div className="gofr">
                <span className="gk">ROCOF</span>
                <span className="gv-col">
                  <span className="gv">{sig(r.rocof)}</span>
                  {r.rocof_ci && <span className="param-ci">95% {ciText(r.rocof_ci)}</span>}
                </span>
              </div>
              {r.n_systems != null && (
                <div className="gofr"><span className="gk">Systems / failures</span><span className="gv">{r.n_systems} / {r.n_events}</span></div>
              )}
              {r.bounds_method && (
                <p className="param-ci-note" style={{ padding: "0 16px 10px" }}>
                  {crow
                    ? "Crow's exact bounds: a time-terminated test (or one system run to its last failure)."
                    : "Wald (delta-method) bounds. Crow's exact bounds need a Crow-AMSAA fit to a time-terminated test."}
                </p>
              )}
            </div>

            <div className="gof-card rec-detail-card">
              <div className="gofh">Trend tests</div>
              {tests.length > 0 ? (
                <>
                  {tests.map((t) => (
                    <div className="gofr" key={t.id || t.test}>
                      <span className="gk">{t.test}</span>
                      <span className="gv-col">
                        <span className="gv">{t.significant && t.trend !== "no trend" ? t.trend : "no trend"}</span>
                        <span className="param-ci">
                          {pText(t.p_value)} · statistic {sig(t.statistic, 3)}{t.dof != null ? ` (${t.dof} dof)` : ""}
                        </span>
                      </span>
                    </div>
                  ))}
                  <p className="param-ci-note" style={{ padding: "0 16px 10px" }}>
                    Null hypothesis: a constant failure rate (HPP). A trend is named at p &lt; 0.05; each system is tested over its own observation window.
                  </p>
                </>
              ) : (
                <div className="detail-note" style={{ margin: 0, padding: "11px 16px" }}>
                  Not available for a model built from parameters — the trend tests need event data.
                </div>
              )}
            </div>

            {((r.gof || []).length > 0 || cvm) && (
              <div className="gof-card rec-detail-card">
                <div className="gofh">Goodness of fit</div>
                {(r.gof || []).map((g) => (
                  <div className="gofr" key={g.id}><span className="gk">{g.label}</span><span className="gv">{fmt(g.value, 2)}</span></div>
                ))}
                {cvm && (
                  <div className="gofr">
                    <span className="gk">Cramér-von Mises</span>
                    <span className="gv-col">
                      {cvm.p_value != null ? (
                        <>
                          <span className="gv">{cvm.adequate ? "fits" : "poor fit"}</span>
                          <span className="param-ci">{pText(cvm.p_value)} · {cvm.n_boot} bootstrap samples</span>
                        </>
                      ) : (
                        <span className="param-ci">{cvm.reason || "—"}</span>
                      )}
                    </span>
                  </div>
                )}
                {cvm && cvm.p_value != null && (
                  <p className="param-ci-note" style={{ padding: "0 16px 10px" }}>
                    {cvm.adequate
                      ? "No evidence against the fitted intensity (p ≥ 0.05)."
                      : "The event times don't follow the fitted intensity (p < 0.05): try another model."}
                  </p>
                )}
              </div>
            )}

            {systems.length > 1 && (
              <div className="gof-card rec-detail-card">
                <div className="gofh">Systems vs the model</div>
                {systems.map((s) => (
                  <div className="gofr" key={s.system}>
                    <span className="gk">{s.system}</span>
                    <span className="gv-col">
                      <span className="gv">{fmt(s.failures, 0)} failures</span>
                      <span className="param-ci">
                        {fmt(s.expected, 1)} expected · {s.excess >= 0 ? "+" : "−"}{fmt(Math.abs(s.excess), 1)}
                      </span>
                    </span>
                  </div>
                ))}
                <p className="param-ci-note" style={{ padding: "0 16px 10px" }}>
                  Most excess failures first: observed against what the model expects over each system's own window.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

    </>
  );
}
