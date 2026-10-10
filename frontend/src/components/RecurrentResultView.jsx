import { useState } from "react";
import RecurrentCalculator from "./RecurrentCalculator.jsx";
import RecurrentAside from "./RecurrentAside.jsx";
import { CausePanel, CovariatePanel, McfPlot, NextFailurePanel } from "./RecurrentCharts.jsx";
import { familyOf } from "../recurrentResults.js";

// A fitted recurrent-event (repairable-system) model, laid out like the life
// model page (#65, #311): the tabs first; the MCF plot beside a panel with the
// parameters, the rates now and a quiet reading, the fit statistics in a
// dialog from that panel. A covariate model adds its covariates' effects, an
// imperfect-repair model each system's next failure, and data with a cause
// column the MCF of each cause. ``extraTabs`` ([{ id, label, render() }]) are
// the saved model's own tools (overhaul, growth projection), after the rest.
// Handles both data fits and models built from parameters.
export default function RecurrentResultView({ results, name = null, extraTabs = [] }) {
  const r = results || {};
  const fam = familyOf(r);
  const tabs = [
    { id: "mcf", label: "MCF plot" },
    { id: "calc", label: "Calculator" },
    (r.by_cause?.causes || []).length > 0 && { id: "cause", label: "By cause" },
    fam === "regression" && (r.coefficients || []).length > 0 && { id: "cov", label: "Covariates" },
    fam === "renewal" && (r.next_failure?.units || []).length > 0 && { id: "next", label: "Next failure" },
    ...extraTabs,
  ].filter(Boolean);
  const [tab, setTab] = useState("mcf");
  const active = tabs.find((t) => t.id === tab) ? tab : "mcf";

  return (
    <>
      <div className="tabs" role="tablist">
        {tabs.map((tb) => (
          <button
            key={tb.id}
            role="tab"
            aria-selected={active === tb.id}
            className={"tab" + (active === tb.id ? " active" : "")}
            onClick={() => setTab(tb.id)}
          >
            {tb.label}
          </button>
        ))}
      </div>

      <div className="tab-panel">
        {active === "mcf" && (
          <div className="detail-panel life-panel">
            <div className="plotwrap">
              <McfPlot r={r} name={name} />
            </div>
            <RecurrentAside r={r} />
          </div>
        )}
        {active === "calc" && <RecurrentCalculator r={r} name={name} />}
        {active === "cause" && <CausePanel r={r} name={name} />}
        {active === "cov" && <CovariatePanel r={r} name={name} />}
        {active === "next" && <NextFailurePanel r={r} name={name} />}
        {/* Kept mounted, so a tool's inputs survive a look at another tab. */}
        {extraTabs.map((t) => <div key={t.id} hidden={active !== t.id}>{t.render()}</div>)}
      </div>
    </>
  );
}
