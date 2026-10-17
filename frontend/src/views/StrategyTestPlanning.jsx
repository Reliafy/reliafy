import { useMemo } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import Tabs from "../components/ui/Tabs.jsx";
import DemonstrationTest from "../components/DemonstrationTest.jsx";
import SequentialTestPlan from "../components/SequentialTestPlan.jsx";
import LifeTestPlan from "../components/LifeTestPlan.jsx";
import AcceleratedTestPlan from "../components/AcceleratedTestPlan.jsx";
import ComparisonPlan from "../components/ComparisonPlan.jsx";
import { parseDemoPrefill } from "../requirement.js";
import { TEST_PLAN_TABS, tabFromPath } from "../testPlanning.js";
import "./StrategyTestPlanning.css";

const INTRO = {
  demonstration: "Show a design meets a reliability or MTBF target: how many units to test, for how long, and how many failures to allow.",
  sequential: "Decide as failures come in: stop as soon as the evidence is clear, usually well before a fixed-length test would.",
  life: "How precisely a life test will estimate a B-life or the mean life, and the units or test time a precision needs.",
  accelerated: "The stresses to test at, the units at each, and the failures to expect, to estimate the life at use.",
  comparison: "Did the change work? The operating time or units it takes to tell a real improvement from luck.",
};

// Strategy › Test planning: planning reliability tests before they're run,
// one tab per kind of test (each tab its own path, so it can be linked).
// The Demonstration tab keeps the old Demonstration test page's links: a
// model's "Plan a test to demonstrate this" (#295) opens it with the
// requirement in the query string.
export default function StrategyTestPlanning() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPath(pathname);
  const initial = useMemo(() => parseDemoPrefill(search), [search]);
  const altModel = useMemo(() => new URLSearchParams(search).get("model"), [search]);

  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Test planning"
        meta={INTRO[tab]}
      />
      <Tabs
        label="Kind of test"
        tabs={TEST_PLAN_TABS.map((t) => ({ id: t.id, label: t.label }))}
        value={tab}
        onChange={(id) => navigate(TEST_PLAN_TABS.find((t) => t.id === id).path)}
      />
      <Card>
        {tab === "demonstration" && <DemonstrationTest key={search} initial={initial} />}
        {tab === "sequential" && <SequentialTestPlan />}
        {tab === "life" && <LifeTestPlan />}
        {tab === "accelerated" && <AcceleratedTestPlan key={altModel || ""} modelId={altModel} />}
        {tab === "comparison" && <ComparisonPlan />}
      </Card>
    </div>
  );
}
