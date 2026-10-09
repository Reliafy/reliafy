import PageHeader from "../components/ui/PageHeader.jsx";
import Card from "../components/ui/Card.jsx";
import DemonstrationTest from "../components/DemonstrationTest.jsx";

// Strategy › Demonstration test.
export default function StrategyDemonstration() {
  return (
    <div className="app">
      <PageHeader
        crumbs={[{ label: "Strategy", to: "/strategy" }]}
        title="Demonstration test"
        meta="Plan a reliability demonstration test: how many units to test, for how long, and how many failures to allow, to show a reliability target at a confidence level."
      />
      <Card>
        <DemonstrationTest />
      </Card>
    </div>
  );
}
