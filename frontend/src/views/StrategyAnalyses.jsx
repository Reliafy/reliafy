import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listStrategyAnalyses, deleteStrategyAnalysis } from "../api.js";
import { relativeTime } from "../instrument.js";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
};

const OpenIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 17 17 7M9 7h8v8" />
  </svg>
);
const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

// Saved strategy analyses — persistent calculations that RCM decisions can
// link to as evidence.
export default function StrategyAnalyses() {
  const navigate = useNavigate();
  const [analyses, setAnalyses] = useState(null);
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listStrategyAnalyses()
      .then((d) => setAnalyses(d.analyses))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onDelete = async (a) => {
    const msg = a.is_sample
      ? `Remove the sample “${a.name}” from your workspace? It stays available to other users.`
      : `Delete analysis “${a.name}”?`;
    if (!window.confirm(msg)) return;
    await deleteStrategyAnalysis(a.id);
    refresh();
  };

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/strategy")}>Strategy</button> / <b>Saved analyses</b>
          </div>
          <h1>Saved analyses</h1>
          <p>
            Persisted strategy calculations. Run a tool, hit "Save analysis",
            and link the result as evidence in an RCM study.
          </p>
        </div>
      </header>

      {error && <div className="card error">{error}</div>}

      {analyses === null ? (
        <div className="card empty">Loading…</div>
      ) : analyses.length === 0 ? (
        <div className="card empty">
          <h2>No saved analyses</h2>
          <p>Run Optimal replacement, Compare two models, or Failure finding and save the result.</p>
        </div>
      ) : (
        <div className="lib">
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Analysis</th>
                <th style={{ width: 180 }}>Kind</th>
                <th>Result</th>
                <th>Saved</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {analyses.map((a) => (
                <tr key={a.id} className="lib-row" onClick={() => navigate(`/strategy/analyses/${a.id}`)}>
                  <td>
                    <div className="lib-name">
                      {a.name}
                      {a.is_sample && <span className="sample-tag">Sample</span>}
                      {a.shared_by && <span className="sample-tag shared" title={`Shared by ${a.shared_by}`}>Shared</span>}
                    </div>
                  </td>
                  <td>{KIND_LABEL[a.kind] || a.kind}</td>
                  <td className="lib-date">{a.headline}</td>
                  <td className="lib-date">{relativeTime(a.updated_at || a.created_at)}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      <button className="act" title="Open" onClick={(e) => { e.stopPropagation(); navigate(`/strategy/analyses/${a.id}`); }}>
                        <OpenIcon />
                      </button>
                      <button className="act del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(a); }}>
                        <TrashIcon />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
