import { useRef, useState } from "react";
import Plot from "./Plot.jsx";
import ProbabilityPlot from "./ProbabilityPlot.jsx";
import SurvivalPlot from "./SurvivalPlot.jsx";
import Calculator, { initCalcState } from "./Calculator.jsx";
import NoMaximumNotice from "./NoMaximumNotice.jsx";
import CompetingRisksResult from "./CompetingRisksResult.jsx";
import LifeAside, { paramView } from "./LifeSummary.jsx";
import ModelCharacteristics from "./ModelCharacteristics.jsx";
import { distColor } from "../instrument.js";
import Chip from "./ui/Chip.jsx";
import { TvcCalculator, initTvcState } from "./TvcResult.jsx";
import { FlexibleSurvival } from "./MoreModelPanels.jsx";
import ScrollCue from "./ui/ScrollCue.jsx";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { PlotCard, PlotPanel } from "./model/ModelLayouts.jsx";
import Effects from "./model/Effects.jsx";
import Diagnostics from "./model/Diagnostics.jsx";
import DataTab from "./model/DataTab.jsx";
import { COLORWAY } from "../plotTheme.js";
import { modelTabs, pmfFromCurves, resolveTab } from "../modelFrame.js";
import { unitInText } from "./unitText.js";

const pct = (v) => `${(v * 100).toFixed(v < 0.1 ? 2 : 1)}%`;

// A regression result read as its baseline distribution ("weibull_ph" →
// "weibull"), so its parameters get their plain names ("Scale α (hours)").
const baselineOf = (result) => ({
  ...result, distribution_id: String(result.distribution_id || "").replace(/_(ph|aft|po|ah)$/, ""),
});

// Per-demand (Binomial) reliability: a probability, not a curve over time.
// Models saved before #233 carry a Wilson 95% interval and no confidence /
// method; newer ones carry exact (Clopper-Pearson) bounds at their confidence,
// the one-sided reliability bound and, from several batches, the batches.
// What a per-demand figure is for. Failure finding takes a non-repairable model over
// time, not a per-demand probability, so do not point there.
const PER_DEMAND_USE = "For one-shot and protective equipment: the chance it works when called on. "
  + "A failure-finding interval needs a non-repairable model over time instead.";

export function PerDemandPanel({ result }) {
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
        <ScrollCue className="pd-batch-table">
          <table className="mini-table">
            <thead><tr><th>Batch</th><th>Demands</th><th>Failures</th><th>Failures / demand</th></tr></thead>
            <tbody>
              {batches.map((b, i) => (
                <tr key={i}><td>{b.label}</td><td>{b.demands}</td><td>{b.failures}</td><td>{pct(b.p)}</td></tr>
              ))}
            </tbody>
          </table>
        </ScrollCue>
      )}
      {d.success_run ? (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Success run — {d.demands} demand{d.demands === 1 ? "" : "s"} with zero failures
          demonstrates reliability <b>≥ {pct(d.success_run.reliability_lower)}</b> at{" "}
          {Math.round(d.success_run.confidence * 100)}% confidence (one-sided lower bound,
          R ≥ (1 − C)<sup>1/n</sup>). {PER_DEMAND_USE}
        </p>
      ) : exact ? (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Estimated from {d.failures} failure{d.failures === 1 ? "" : "s"} in {d.demands} demands
          {batches.length > 1 ? `, pooled over ${batches.length} batches (one failure probability for all)` : ""}.
          Bounds are exact (Clopper-Pearson) at {c}% confidence. {PER_DEMAND_USE}
        </p>
      ) : (
        <p className="muted-line" style={{ margin: "0.5rem 0 0" }}>
          Estimated from {d.failures} failure{d.failures === 1 ? "" : "s"} in {d.demands} demands
          (Binomial, Wilson 95% interval). {PER_DEMAND_USE}
        </p>
      )}
    </>
  );
}


// A discrete fit's first tab: the chance of failing at each count, the
// model's against the data's own (the Kaplan-Meier step at that count),
// beside the usual panel.
function ChanceByCount({ result, split, modelId, onStats, name }) {
  const k = result.counts;
  const model = k ? k.k.map((c, i) => ({ k: c, p: k.pmf[i] })) : pmfFromCurves(result.functions?.curves);
  const u = result.unit ? unitInText(result.unit) : "count";
  const traces = [
    ...(k ? [{ type: "bar", x: k.k, y: k.observed, name: "The data", marker: { color: "rgba(20,23,28,0.3)" },
               hovertemplate: "%{x}: %{y:.1%} (data)<extra></extra>" }] : []),
    { type: "scatter", mode: "lines+markers", x: model.map((m) => m.k), y: model.map((m) => m.p), name: "The model",
      line: { color: COLORWAY[0], width: 2 }, marker: { size: 6, color: COLORWAY[0] },
      hovertemplate: "%{x}: %{y:.1%} (model)<extra></extra>" },
  ];
  return (
    <PlotPanel
      plot={
        <PlotCard title={`Chance of failing at each ${u.replace(/s$/, "")}`}>
          <Plot fill data={traces} download={`${name || result.distribution} — chance by count`}
                layout={{ bargap: 0.25, showlegend: true, xaxis: { title: { text: `Failed at (${u})` } },
                          yaxis: { title: { text: "Chance of failing there" }, tickformat: ".0%", rangemode: "tozero" },
                          legend: { x: 1, xanchor: "right", y: 1, yanchor: "top", bgcolor: "rgba(255,255,255,0.85)" } }} />
        </PlotCard>
      }
      side={<LifeAside result={result} split={split} modelId={modelId} onStats={onStats} showUse={false} />}
    />
  );
}

// Presentational result for a fit (fresh, saved, shared or a sample): the
// model frame's tab row and the tab's body (components/model/). The page
// around it gives the header (ModelFrame).
// ``modelId`` (a saved model) lets a regression model saved before its
// validation scores existed fetch them. ``split`` ({ failed, running, other })
// is the data's failure / still-running count when the caller has the data.
// ``compare`` (() => Promise<selection>) runs Best fit's comparison on the
// same data; ``onPick(distributionId)`` refits with another distribution
// (#293) — both optional. ``onUse`` (() => Promise<saved id>, a fit not
// saved yet) lets "Use this model" save it first (#294). ``datasetId``: the
// data it was fitted to, for the Data tab. ``tab`` / ``onTab``: the open tab
// (a page keeps it in its address); without them the view keeps its own.
export default function ResultView(props) {
  if (props.result.kind === "per_demand") {
    return <ModelTabs tabs={[]}><PerDemandPanel result={props.result} /></ModelTabs>;
  }
  // Life data by failure mode (#177) has tabs of its own in the same frame; a
  // separate component, so a change of kind remounts rather than reorders hooks.
  if (props.result.kind === "competing_risks") {
    return <CompetingRisksResult result={props.result} name={props.name} datasetId={props.datasetId || null}
                                 tab={props.tab} onTab={props.onTab || null} />;
  }
  return <LifeResult {...props} />;
}

function LifeResult({ result, modelId = null, name = null, split = null, compare = null, onPick = null,
                     datasetId = null, tab: wanted = undefined, onTab = null }) {
  const isRegression = result.kind === "regression";
  const tabs = modelTabs(result) || [];
  const [own, setOwn] = useState(() => resolveTab(tabs, wanted));
  const tab = resolveTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const setTab = (id) => {
    setOwn(id);
    onTab?.(id);
  };

  // The Calculator tab unmounts when you switch away, so its inputs live here
  // and survive tab switches. When the result itself changes in place (e.g.
  // fitting another model in the workspace) reset them for the new model.
  const [calc, setCalc] = useState(() => initCalcState(result.functions));
  const calcNextId = useRef(1);
  // One confidence for the calculator's bounds and the mean life's (#288).
  const level = Number(calc.ci.level);
  const setLevel = (v) => setCalc((st) => ({ ...st, ci: { ...st.ci, level: v } }));
  // Covariates that change over time (#60): the schedule calculator's inputs.
  const [tvcCalc, setTvcCalc] = useState(() => (result.tvc ? initTvcState(result) : null));
  const [prevResult, setPrevResult] = useState(result);
  if (result !== prevResult) {
    setPrevResult(result);
    setTvcCalc(result.tvc ? initTvcState(result) : null);
    setCalc(initCalcState(result.functions));
    calcNextId.current = 1;
    setOwn(resolveTab(modelTabs(result) || [], null));
  }

  const has = (id) => tabs.some((t) => t.id === id);
  // "B-lives: use Time at reliability": the Calculator in that mode.
  const showBLives = has("calc") && !result.tvc ? () => { setCalc((st) => ({ ...st, mode: "time" })); setTab("calc"); } : null;
  const toCalc = has("calc") ? () => setTab("calc") : null;
  const onStats = has("diag") ? () => setTab("diag") : null;
  const bestFit = (result.selection?.candidates?.length || 0) > 1;
  const label = name || result.distribution;

  let body = null;
  switch (tab) {
    case "plot":
      body = (
        <PlotPanel
          plot={<PlotCard><ProbabilityPlot fill plot={result.plot} unit={result.unit} download={`${label} — probability plot`} /></PlotCard>}
          side={<LifeAside result={result} split={split} bestFit={bestFit} compare={compare} onPick={onPick}
                           modelId={modelId} onStats={onStats} showUse={false} />}
        />
      );
      break;
    case "survival":
      body = result.kind === "flexible" ? (
        <FlexibleSurvival result={result} split={split} name={name} modelId={modelId} onStats={onStats} />
      ) : (
        <PlotPanel
          plot={<PlotCard><SurvivalPlot fill estimate={result.estimate} unit={result.unit} download={`${label} — survival curve`} /></PlotCard>}
          side={<LifeAside result={result} split={split} modelId={modelId} showUse={false} />}
        />
      );
      break;
    case "chance":
      body = <ChanceByCount result={result} split={split} modelId={modelId} onStats={onStats} name={name} />;
      break;
    case "effects":
      body = <Effects result={result} name={label} split={split} />;
      break;
    case "calc":
      body = result.tvc ? (
        <TvcCalculator result={result} state={tvcCalc} setState={setTvcCalc} name={label} fill />
      ) : (
        <Calculator
          fill
          functions={result.functions}
          unit={result.unit}
          params={result.params_only ? result.params : null}
          state={calc}
          setState={setCalc}
          nextIdRef={calcNextId}
          name={label}
          paramLabel={isRegression ? (p) => paramView(baselineOf(result), p).label : null}
        />
      );
      break;
    case "chars":
      body = (
        <ModelCharacteristics result={result} level={level} onLevel={setLevel} onBLives={showBLives}
                              calc={calc} tvc={tvcCalc} onCalc={toCalc} />
      );
      break;
    case "diag":
      body = <Diagnostics result={result} name={label} compare={compare} onPick={onPick} modelId={modelId} />;
      break;
    case "data":
      body = <DataTab result={result} split={split} datasetId={datasetId} />;
      break;
    default:
  }

  return (
    <ModelTabs
      tabs={tabs}
      value={tab}
      onChange={setTab}
      before={result.no_finite_maximum && (
        <div className="mf-before"><NoMaximumNotice notice={result.no_finite_maximum} style={{ margin: 0 }} /></div>
      )}
    >
      {body}
    </ModelTabs>
  );
}
