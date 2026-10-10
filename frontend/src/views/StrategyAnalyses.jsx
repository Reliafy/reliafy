import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listStrategyAnalyses, deleteStrategyAnalysis } from "../api.js";
import ListSearch, { matches } from "../components/ListSearch.jsx";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import PageHeader from "../components/ui/PageHeader.jsx";
import SafetyStarterCard from "../components/RbdSafetyStarter.jsx";
import { RowActions, SampleGroups, itemName } from "../components/LibRows.jsx";
import { CompareIcon, CostIcon, StrategyIcon, TestIcon } from "../components/icons.jsx";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
};

// The tools that make an analysis: the Strategy page starts with them.
const TOOLS = [
  { to: "/strategy/replacement", icon: <CostIcon />, label: "Optimal replacement" },
  { to: "/strategy/compare", icon: <CompareIcon />, label: "Compare two models" },
  { to: "/strategy/failure-finding", icon: <StrategyIcon />, label: "Failure finding" },
  { to: "/strategy/demonstration-test", icon: <TestIcon />, label: "Demonstration test" },
];

// The Strategy section's root: its tools, then the saved analyses —
// persistent calculations that RCM decisions can link to as evidence.
export default function StrategyAnalyses() {
  const navigate = useNavigate();
  const [analyses, setAnalyses] = useState(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState(null);

  const refresh = useCallback(() => {
    listStrategyAnalyses()
      .then((d) => setAnalyses(d.analyses))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => refresh(), [refresh]);

  const onDelete = async (a) => {
    const msg = a.is_sample
      ? `Remove the sample “${itemName(a)}” from your workspace? It stays available to other users and you won't see it again.`
      : `Delete analysis “${a.name}”?`;
    if (!window.confirm(msg)) return;
    try {
      await deleteStrategyAnalysis(a.id);
      refresh();
    } catch (err) {
      setError(err.message);
    }
  };

  const open = (id) => navigate(`/strategy/analyses/${id}`);
  const visible = (analyses || []).filter((a) => matches(query, a.name, a.kind, a.headline, a.id));

  return (
    <div className="app">
      <PageHeader
        title="Strategy"
        meta="Turn fitted models into maintenance decisions. Saved analyses can be cited as evidence in RCM studies."
      />

      <nav className="tool-strip" aria-label="Strategy tools">
        {TOOLS.map((t) => (
          <Link key={t.to} className="tool-link" to={t.to}>
            {t.icon}
            {t.label}
          </Link>
        ))}
      </nav>

      <SafetyStarterCard />

      {error && <div className="card error">{error}</div>}

      {analyses === null ? (
        <div className="card empty">Loading…</div>
      ) : analyses.length === 0 ? (
        <div className="card empty">
          <h2>No saved analyses</h2>
          <p>Run one of the tools above and save its result to see it here.</p>
        </div>
      ) : (
        <>
          <div className="tablebar">
            <span className="count">{visible.length} of {analyses.length} saved analyses</span>
            <span className="grow" />
            <ListSearch value={query} onChange={setQuery} placeholder="Search analyses…" />
          </div>
          <div className="lib">
            <table className="lib-table">
              <thead>
                <tr>
                  <th style={{ width: "34%" }}>Analysis</th>
                  <th className="lib-opt" style={{ width: 180 }}>Kind</th>
                  <th>Result</th>
                  <th className="lib-opt">Saved</th>
                  <th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                <SampleGroups rows={visible} cols={5} render={(a) => (
                  <tr key={a.id} className="lib-row" onClick={() => open(a.id)}>
                    <td>
                      <div className="lib-name">
                        {itemName(a)}
                        {a.shared_by && <Chip title={`Shared by ${a.shared_by}`}>Shared</Chip>}
                      </div>
                    </td>
                    <td className="lib-opt">{KIND_LABEL[a.kind] || a.kind}</td>
                    <td className="lib-date">{a.headline}</td>
                    <td className="lib-date lib-opt">{relativeTime(a.updated_at || a.created_at)}</td>
                    <RowActions item={a} onOpen={() => open(a.id)} onDelete={() => onDelete(a)} />
                  </tr>
                )} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
