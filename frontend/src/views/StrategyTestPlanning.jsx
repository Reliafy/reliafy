import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { SectionHeader } from "../components/SectionPage.jsx";
import { SavedOfKind } from "../components/StrategyTool.jsx";
import { STRATEGY_TOOLS } from "../strategyTools.js";
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
// requirement in the query string (b, life, conf, unit; #295) pre-fills it,
// and "Use this model" (#294) brings a model's β and unit.
export default function StrategyTestPlanning() {
  const { pathname, search } = useLocation();
  const navigate = useNavigate();
  const tab = tabFromPath(pathname);
  const query = useMemo(() => new URLSearchParams(search), [search]);
  // Each tab stays open once visited (hidden when another is shown), so what
  // was typed on one survives a look at another. A link's prefill (a
  // requirement, an ALT model) is kept by the tab it was for.
  const [visited, setVisited] = useState(() => new Set([tab]));
  useEffect(() => { setVisited((v) => (v.has(tab) ? v : new Set([...v, tab]))); }, [tab]);
  const demoSearch = useRef(search);
  if (tab === "demonstration") demoSearch.current = search;
  const altLink = useRef({ model: query.get("model"), use: query.get("use") });
  if (tab === "accelerated") altLink.current = { model: query.get("model"), use: query.get("use") };
  const initial = useMemo(() => parseDemoPrefill(demoSearch.current), [demoSearch.current]); // eslint-disable-line react-hooks/exhaustive-deps
  // A chart drawn while its tab was hidden has no width: redraw on showing it.
  useEffect(() => { window.dispatchEvent(new Event("resize")); }, [tab]);
  const show = (id) => tab === id || visited.has(id);

  const tool = STRATEGY_TOOLS[tab === "accelerated" ? "accelerated" : "testPlanning"];
  return (
    <div className="app">
      <SectionHeader
        section="strategy"
        title="Test planning"
        help={tool.help}
        purpose={INTRO[tab]}
      />
      <Tabs
        label="Kind of test"
        tabs={TEST_PLAN_TABS.map((t) => ({ id: t.id, label: t.label }))}
        value={tab}
        onChange={(id) => navigate(TEST_PLAN_TABS.find((t) => t.id === id).path)}
      />
      <Card>
        {show("demonstration") && (
          <div hidden={tab !== "demonstration"}><DemonstrationTest key={demoSearch.current} initial={initial} /></div>
        )}
        {show("sequential") && <div hidden={tab !== "sequential"}><SequentialTestPlan /></div>}
        {show("life") && <div hidden={tab !== "life"}><LifeTestPlan /></div>}
        {show("accelerated") && (
          <div hidden={tab !== "accelerated"}>
            <AcceleratedTestPlan key={`${altLink.current.model || ""}|${altLink.current.use || ""}`}
                                 modelId={altLink.current.model} useStress={altLink.current.use} />
          </div>
        )}
        {show("comparison") && <div hidden={tab !== "comparison"}><ComparisonPlan /></div>}
      </Card>
      {tab === "demonstration" && <SavedOfKind kind={tool.kind} noun={tool.noun} />}
    </div>
  );
}
