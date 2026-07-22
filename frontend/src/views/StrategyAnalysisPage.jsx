import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import CopyId from "../components/CopyId.jsx";
import ReplacementResult from "../components/ReplacementResult.jsx";
import CompareResult from "../components/CompareResult.jsx";
import FfiResult from "../components/FfiResult.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getStrategyAnalysis } from "../api.js";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
};

// A saved strategy analysis, rendered read-only from its stored results.
export default function StrategyAnalysisPage() {
  const { id } = useParams();
  const navigate = useNavigate();
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
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/strategy/analyses")}>Saved analyses</button> /{" "}
            <b>{doc.name}</b>
          </div>
          <h1>
            {doc.name}
            {doc.is_sample && <span className="sample-tag" style={{ verticalAlign: "middle" }}>Sample</span>}
            {doc.shared_by && <span className="sample-tag shared" style={{ verticalAlign: "middle" }} title={`Shared by ${doc.shared_by}`}>Shared</span>}
          </h1>
          <p>{KIND_LABEL[doc.kind] || doc.kind} — computed when saved; results are stored, not refreshed.</p>
          <CopyId id={doc.id} />
        </div>
        <ShareButton
          collection="strategy_analyses"
          artifactId={doc.id}
          name={doc.name}
          readOnly={doc.read_only}
        />
      </header>

      <div className="card">
        {doc.kind === "optimal_replacement" && <ReplacementResult result={doc.results} />}
        {doc.kind === "compare_two" && <CompareResult result={doc.results} />}
        {doc.kind === "failure_finding" && <FfiResult result={doc.results} />}
      </div>
    </div>
  );
}
