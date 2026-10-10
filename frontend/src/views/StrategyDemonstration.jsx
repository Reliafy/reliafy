import { useMemo } from "react";
import { useLocation } from "react-router-dom";
import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import DemonstrationTest from "../components/DemonstrationTest.jsx";
import { parseDemoPrefill } from "../requirement.js";

// Strategy › Demonstration test. A model's "Plan a test to demonstrate this"
// (#295) opens it with the requirement in the query string.
export default function StrategyDemonstration() {
  const { search } = useLocation();
  const initial = useMemo(() => parseDemoPrefill(search), [search]);
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Demonstration test"
        meta="Plan a reliability demonstration test: how many units to test, for how long, and how many failures to allow, to show a reliability target at a confidence level."
      />
      <Card>
        <DemonstrationTest key={search} initial={initial} />
      </Card>
    </div>
  );
}
