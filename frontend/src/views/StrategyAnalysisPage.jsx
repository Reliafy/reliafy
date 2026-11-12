import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import LoadFailed from "../components/LoadFailed.jsx";
import ReplacementResult from "../components/ReplacementResult.jsx";
import CompareResult from "../components/CompareResult.jsx";
import FfiResult from "../components/FfiResult.jsx";
import DemoTestResult from "../components/DemoTestResult.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getStrategyAnalysis } from "../api.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import IntervalAnalysisResult from "../components/IntervalAnalysisResult.jsx";
import { itemName } from "../components/LibRows";
import { PageTitle } from "../components/usePageTitle.js";
import CalendarReplacementResult from "../components/CalendarReplacementResult.jsx";
import { ResultDetails } from "../components/ui/ResultSummary.jsx";
import { inputRows, reopenLink } from "../analysisInputs.js";
import { useCurrency } from "../WorkspaceProvider.jsx";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
  on_condition_interval: "Check interval (P-F)",
  failure_finding_interval: "Test interval",
  calendar_replacement: "Shutdown calendar",
};

// A saved strategy analysis, rendered read-only from its stored results.
export default function StrategyAnalysisPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);
  const currency = useCurrency();

  useEffect(() => {
    getStrategyAnalysis(id).then(setDoc).catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="app">
        <header><h1>Saved analysis</h1></header>
        <LoadFailed error={error} to="/strategy" label="See all saved analyses" />
      </div>
    );
  }
  if (!doc) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <PageTitle name={doc && itemName(doc)} />
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title={itemName(doc)}
        badges={
          <>
            {doc.is_sample && <Chip>Sample</Chip>}
            {doc.shared_by && <Chip title={`Shared by ${doc.shared_by}`}>Shared</Chip>}
          </>
        }
        meta={<>{KIND_LABEL[doc.kind] || doc.kind} · results as computed when it was saved.</>}
        id={doc.id}
        menu={
          <ShareButton
            collection="strategy_analyses"
            artifactId={doc.id}
            name={doc.name}
            readOnly={doc.read_only}
            className="ovm-item"
          />
        }
      />

      <AnalysisInputs doc={doc} currency={currency} />

      <div className="card">
        {doc.kind === "calendar_replacement" && <CalendarReplacementResult result={doc.results} name={doc.name} />}
        {doc.kind === "optimal_replacement" && <ReplacementResult result={doc.results} name={doc.name} />}
        {doc.kind === "compare_two" && <CompareResult result={doc.results} name={doc.name} />}
        {doc.kind === "failure_finding" && <FfiResult result={doc.results} />}
        {doc.kind === "demonstration_test" && <DemoTestResult result={doc.results} />}
        {(doc.kind === "on_condition_interval" || doc.kind === "failure_finding_interval") && (
          <IntervalAnalysisResult kind={doc.kind} result={doc.results} />
        )}
      </div>
    </div>
  );
}

// What gave the answer: the model and figures it was worked out from, and the
// tool again on the same model to rerun with a new price.
function AnalysisInputs({ doc, currency }) {
  const rows = inputRows(doc.kind, doc.inputs, currency);
  if (!rows.length) return null;
  const reopen = reopenLink(doc.kind, doc.inputs);
  return (
    <section className="card analysis-inputs" aria-labelledby="analysis-inputs-h">
      <h2 id="analysis-inputs-h">Inputs</h2>
      <ResultDetails summary="What this was worked out from" rows={rows} open />
      {reopen && (
        <div className="analysis-inputs-actions">
          <Link className="evidence-link" to={reopen.to}>{reopen.label} →</Link>
        </div>
      )}
    </section>
  );
}
