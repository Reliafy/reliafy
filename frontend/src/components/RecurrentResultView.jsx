import { useState } from "react";
import RecurrentCalculator from "./RecurrentCalculator.jsx";
import RecurrentAside, { CausesSide } from "./RecurrentAside.jsx";
import RecurrentOverhaul from "./RecurrentOverhaul.jsx";
import RecurrentProjection from "./RecurrentProjection.jsx";
import RecurrentDiagnostics from "./RecurrentDiagnostics.jsx";
import RecurrentData from "./RecurrentData.jsx";
import { CausesPlot, McfPlot, NextFailureView, RecurrentEffects } from "./RecurrentCharts.jsx";
import SegmentedControl from "./ui/SegmentedControl.jsx";
import { ModelTabs } from "./model/ModelFrame.jsx";
import { PlotCard, PlotPanel } from "./model/ModelLayouts.jsx";
import { planViews, recurrentTabs, resolveRecurrentTab } from "../recurrentResults.js";

// A fitted recurrent-event (repairable-system) model in the model frame's
// tabs (components/model/), those that apply:
//   Failures over time  the MCF with the fitted curve [All failures | By cause]
//                       beside the failure rate and MTBF now and the model in words
//   Effects             what changes the failure rate (covariate models)
//   Calculator          expected failures, failure rate and MTBF, at a time or over a window
//   Plan ahead          [Next failure | Growth projection | Overhaul interval]
//   Diagnostics         the trend, growth and fit checks (a fit to data)
//   Data                what it was fitted to, and every parameter
// ``modelId`` (a saved model) adds the tools that ask the server (the growth
// projection, the overhaul interval); ``paramsOnly``: a model built from
// parameters. ``datasetId`` links the Data tab to its data. ``tab`` /
// ``onTab``: the open tab (a page keeps it in its address); without them the
// view keeps its own. Handles data fits and models built from parameters.
export default function RecurrentResultView({
  results, name = null, modelId = null, paramsOnly = false, datasetId = null, tab: wanted = undefined, onTab = null,
}) {
  const r = results || {};
  const ctx = { modelId, paramsOnly };
  const tabs = recurrentTabs(r, ctx);
  const plans = planViews(r, ctx);
  const first = resolveRecurrentTab(tabs, wanted);
  const [own, setOwn] = useState(first.tab);
  const asked = resolveRecurrentTab(tabs, wanted !== undefined && onTab ? wanted : own);
  const tab = asked.tab;
  const [causeView, setCauseView] = useState(first.view === "cause" ? "cause" : "all");
  const [plan, setPlan] = useState(() => (plans.some((p) => p.value === first.view) ? first.view : plans[0]?.value));
  const setTab = (id) => {
    setOwn(id);
    onTab?.(id);
  };
  const label = name || r.model?.name || "Recurrent model";
  const causes = (r.by_cause?.causes || []).length > 0;
  const [chosen, setChosen] = useState(() => r.by_cause?.causes?.[0]?.label ?? null);
  const onStats = tabs.some((t) => t.id === "diag") ? () => setTab("diag") : null;
  const onData = () => setTab("data");

  const planView = plans.some((p) => p.value === plan) ? plan : plans[0]?.value;
  let body = null;
  switch (tab) {
    case "failures": {
      const byCause = causes && causeView === "cause";
      const controls = causes && (
        <SegmentedControl size="sm" label="Which failures" value={causeView} onChange={setCauseView}
                          options={[{ value: "all", label: "All failures" }, { value: "cause", label: "By cause" }]} />
      );
      body = (
        <PlotPanel
          sideClassName="rec-side"
          plot={
            <PlotCard controls={controls}>
              {byCause ? <CausesPlot r={r} name={label} chosen={chosen} /> : <McfPlot r={r} name={label} />}
            </PlotCard>
          }
          side={byCause ? <CausesSide r={r} chosen={chosen} onChoose={setChosen} />
            : <RecurrentAside r={r} onStats={onStats} onData={onData} onNext={plans.some((p) => p.value === "next")
              ? () => { setPlan("next"); setTab("plan"); } : null} />}
        />
      );
      break;
    }
    case "effects":
      body = <RecurrentEffects r={r} name={label} />;
      break;
    case "calc":
      body = <RecurrentCalculator r={r} name={label} />;
      break;
    case "plan":
      if (planView === "next") body = <NextFailureView r={r} name={label} />;
      break;
    case "diag":
      body = <RecurrentDiagnostics r={r} name={label} />;
      break;
    case "data":
      body = <RecurrentData r={r} datasetId={datasetId} />;
      break;
    default:
  }

  // The server tools stay mounted, so their inputs survive a look at another
  // view or tab.
  const tools = modelId && (
    <>
      {plans.some((p) => p.value === "projection") && (
        <div className="rec-plan-tool" hidden={!(tab === "plan" && planView === "projection")}>
          <RecurrentProjection modelId={modelId} unit={r.unit} />
        </div>
      )}
      {plans.some((p) => p.value === "overhaul") && (
        <div className="rec-plan-tool" hidden={!(tab === "plan" && planView === "overhaul")}>
          <RecurrentOverhaul modelId={modelId} unit={r.unit} name={label} />
        </div>
      )}
    </>
  );

  return (
    <ModelTabs
      tabs={tabs}
      value={tab}
      onChange={setTab}
      before={(
        <>
          {r.fit_warning && <div className="mf-before life-reading caveat" role="note">{r.fit_warning}</div>}
          {tab === "plan" && plans.length > 1 && (
            <div className="mf-before rec-plan-bar">
              <SegmentedControl size="sm" label="Plan ahead" value={planView} onChange={setPlan} options={plans} />
            </div>
          )}
        </>
      )}
    >
      {body}
      {tools}
    </ModelTabs>
  );
}

