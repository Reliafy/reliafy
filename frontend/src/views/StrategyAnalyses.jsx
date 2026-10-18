import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listStrategyAnalyses, deleteStrategyAnalysis } from "../api.js";
import { relativeTime } from "../instrument.js";
import Chip from "../components/ui/Chip.jsx";
import OverflowMenu from "../components/OverflowMenu.jsx";
import { SectionHeader, SectionList } from "../components/SectionPage.jsx";
import SafetyStarterCard from "../components/RbdSafetyStarter.jsx";
import { PlusIcon, RowActions, itemName } from "../components/LibRows.jsx";
import { CompareIcon, CostIcon, StrategyIcon, TestIcon } from "../components/icons.jsx";

const KIND_LABEL = {
  optimal_replacement: "Optimal replacement",
  compare_two: "Two-model comparison",
  failure_finding: "Failure finding",
  demonstration_test: "Demonstration test",
};

const HELP = { walkthrough: "replacement", guide: "optimal-replacement-interval" };

// The tools that make an analysis: the menu's Strategy children, and the
// "New analysis" menu here.
const TOOLS = [
  { to: "/strategy/replacement", icon: <CostIcon />, label: "Optimal replacement" },
  { to: "/strategy/compare", icon: <CompareIcon />, label: "Compare two models" },
  { to: "/strategy/failure-finding", icon: <StrategyIcon />, label: "Failure finding" },
  { to: "/strategy/test-planning", icon: <TestIcon />, label: "Test planning" },
];

// The Strategy section's landing page: the saved analyses — persistent
// calculations that RCM decisions can link to as evidence. The tools that
// make them are its children in the menu, and under "New analysis".
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

  const newAnalysis = (
    <OverflowMenu label={<><PlusIcon /> New analysis</>}>
      {TOOLS.map((t) => (
        <Link key={t.to} className="ovm-item ovm-tool" to={t.to}>{t.icon}{t.label}</Link>
      ))}
    </OverflowMenu>
  );

  return (
    <div className="app">
      <SectionHeader
        title="Strategy"
        purpose="Turn fitted models into maintenance decisions. Saved analyses can be cited as evidence in RCM studies."
        help={HELP}
        primary={newAnalysis}
      />

      <SafetyStarterCard />

      {error && <div className="card error">{error}</div>}

      <SectionList
        rows={analyses}
        noun={["saved analysis", "saved analyses"]}
        placeholder="Search analyses…"
        fields={(a) => [a.name, a.kind, KIND_LABEL[a.kind], a.headline]}
        types={Object.entries(KIND_LABEL).map(([value, label]) => ({ value, label }))}
        typeOf={(a) => a.kind}
        help={HELP}
        empty={{
          title: "No saved analyses yet",
          body: <>Run a tool and save its result to see it here:{" "}
            {TOOLS.map((t, i) => (
              <span key={t.to}>{i > 0 && " · "}<Link to={t.to}>{t.label}</Link></span>
            ))}.</>,
        }}
        head={[
          <th key="n" style={{ width: "34%" }}>Analysis</th>,
          <th key="k" className="lib-opt" style={{ width: 180 }}>Kind</th>,
          <th key="r">Result</th>,
          <th key="s" className="lib-opt">Saved</th>,
          <th key="a"><span className="sr-only">Actions</span></th>,
        ]}
        render={(a) => (
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
        )}
      />
    </div>
  );
}
