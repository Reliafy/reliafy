import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import ReplacementResult from "../components/ReplacementResult.jsx";
import CompareResult from "../components/CompareResult.jsx";
import FfiResult from "../components/FfiResult.jsx";
import DemoTestResult from "../components/DemoTestResult.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getStrategyAnalysis } from "../api.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
};

// A saved strategy analysis, rendered read-only from its stored results.
export default function StrategyAnalysisPage() {
  const { id } = useParams();
  const [doc, setDoc] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getStrategyAnalysis(id).then(setDoc).catch((e) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <div className="app">
        <header><h1>Saved analysis</h1></header>
        <div className="card error">{error}</div>
      </div>
    );
  }
  if (!doc) return <div className="app"><div className="card empty">Loading…</div></div>;

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title={doc.name}
        badges={
          <>
            {doc.is_sample && <Chip>Sample</Chip>}
            {doc.shared_by && <Chip title={`Shared by ${doc.shared_by}`}>Shared</Chip>}
          </>
        }
        meta={<>{KIND_LABEL[doc.kind] || doc.kind} · computed when saved; results are stored, not refreshed.</>}
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

      <div className="card">
        {doc.kind === "optimal_replacement" && <ReplacementResult result={doc.results} name={doc.name} />}
        {doc.kind === "compare_two" && <CompareResult result={doc.results} name={doc.name} />}
        {doc.kind === "failure_finding" && <FfiResult result={doc.results} />}
        {doc.kind === "demonstration_test" && <DemoTestResult result={doc.results} />}
      </div>
    </div>
  );
}
